"""Helpers for interacting with the V2C charger local HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import async_timeout
from aiohttp import ClientError, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._net import validate_private_ip
from ._pairings import _persist_lan_observed_ip
from .const import (
    CLOUD_ONLY_UPDATE_INTERVAL,
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MANUAL_IPS,
    DEFAULT_LOCAL_INTERVAL,
    LOCAL_HTTP_TIMEOUT,
    LOCAL_MAX_RETRIES,
    LOCAL_RETRY_BACKOFF,
    LOCAL_WRITE_RETRY_DELAY,
)
from .entity import get_device_state_from_coordinator

if TYPE_CHECKING:
    from . import V2CEntryRuntimeData

_LOGGER = logging.getLogger(__name__)

# Local HTTP timeout (seconds) for /RealTimeData, /write/, /read/ calls.
LOCAL_TIMEOUT = LOCAL_HTTP_TIMEOUT
_HTTP_ERROR_THRESHOLD = 400

# Keywords writable via /write/ but absent from /RealTimeData.
# Must be read individually via GET /read/<KeyWord>.
# Per V2C Datamanager doc + live verification on FW 2.4.6 (10.35.0.50):
#   /RealTimeData omits ChargeMode, LightLED, LogoLED — all three return a
#   plain numeric value via /read/<KeyWord> and feed the corresponding
#   Select / Number / Switch entity.
_READ_ONLY_KEYWORDS: tuple[str, ...] = ("LogoLED", "LightLED", "ChargeMode")

# Whitelist of keywords accepted by /write/. The list mirrors the keys
# documented as "WRITE ENABLED = Y" in the Trydan Datamanager spec.
WRITEABLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "VoltageInstallation",
        "ChargeMode",
        "Paused",
        "Locked",
        "Timer",
        "Intensity",
        "Dynamic",
        "MinIntensity",
        "MaxIntensity",
        "PauseDynamic",
        "LightLED",
        "LogoLED",
        "DynamicPowerMode",
        "ContractedPower",
    }
)


def _build_local_interval(
    entry_data: dict[str, Any], options: dict[str, Any]
) -> timedelta:
    """
    Resolve the effective local poll interval from entry options.

    Cloud-only entries (``entry_data['cloud_only'] is True``) keep
    ``CLOUD_ONLY_UPDATE_INTERVAL``; LAN entries honour
    ``options[CONF_LOCAL_UPDATE_INTERVAL]`` when set, falling back to
    ``DEFAULT_LOCAL_INTERVAL``. Always returns a ``timedelta``.
    """
    if entry_data.get(CONF_CLOUD_ONLY):
        return CLOUD_ONLY_UPDATE_INTERVAL
    seconds = options.get(CONF_LOCAL_UPDATE_INTERVAL)
    if not isinstance(seconds, int) or seconds <= 0:
        seconds = DEFAULT_LOCAL_INTERVAL
    return timedelta(seconds=seconds)


# Mapping: cloud reported key (lowercase) → (local RealTimeData key, is_power_kw)
#
# Sources confirmed against real `/device/reported` + `/device/currentstatecharge`
# payloads on a Trydan XQUXDU running firmware 2.4.6 (see docs/cloud-payload-keys
# for the dump used during the 2026-05-19 audit). The cloud always reports power
# measurements in kW; `is_power_kw` marks the fields that need the unconditional
# kW → W conversion applied (see `_CLOUD_POWER_KW_TO_W` below).
_REPORTED_TO_REALTIME: dict[str, tuple[str, bool]] = {
    "charge_state": ("ChargeState", False),
    "chargestate": ("ChargeState", False),
    "intensity": ("Intensity", False),
    "currentintensity": ("Intensity", False),
    "power": ("ChargePower", True),
    "chargepower": ("ChargePower", True),
    "charge_power": ("ChargePower", True),
    "energy": ("ChargeEnergy", False),
    "chargeenergy": ("ChargeEnergy", False),
    "charge_energy": ("ChargeEnergy", False),
    "seconds": ("ChargeTime", False),
    "chargetime": ("ChargeTime", False),
    "charge_time": ("ChargeTime", False),
    # NOTE: cloud's `voltage` field in /currentstatecharge is NOT mains voltage —
    # it carries a small internal signal (e.g. 0.077350 on a 230V EU install) that
    # does not correspond to any user-visible electrical quantity. The actual mains
    # / installation voltage is carried in `cp_level` (see below) and we map that
    # to VoltageInstallation instead. `voltage` is intentionally NOT mapped here.
    "house_power": ("HousePower", True),
    "housepower": ("HousePower", True),
    "sun_power": ("FVPower", True),
    "fvpower": ("FVPower", True),
    "fv_power": ("FVPower", True),
    "battery": ("BatteryPower", True),
    "batterypower": ("BatteryPower", True),
    "battery_power": ("BatteryPower", True),
    "grid_power": ("GridPower", True),
    "gridpower": ("GridPower", True),
    "error": ("SlaveError", False),
    "slaveerror": ("SlaveError", False),
    "slave_error": ("SlaveError", False),
    "pause": ("Paused", False),
    "paused": ("Paused", False),
    "phases": ("Phases", False),
    # cp_level carries the actual installation/mains voltage in V (e.g. 248 on a
    # 230V EU install). Maps to VoltageInstallation, the user-visible voltage
    # sensor. Not scaled — cloud already reports it in V.
    "cp_level": ("VoltageInstallation", False),
    "ready_state": ("ReadyState", False),
    "readystate": ("ReadyState", False),
    "timer": ("Timer", False),
    "dynamic": ("Dynamic", False),
    "photovoltaic_on": ("PhotovoltaicOn", False),
    "locked": ("Locked", False),
    # 2026-05-19 — Number/Switch entities that read `local_key` failed in
    # cloud-only mode because the corresponding cloud keys weren't in the
    # synthesis map. Adding the cloud aliases verified against the real
    # /reported payload.
    "min_car_int": ("MinIntensity", False),
    "min_car_int_fb": ("MinIntensity", False),
    "max_car_int": ("MaxIntensity", False),
    "max_car_int_fb": ("MaxIntensity", False),
    "light_led": ("LightLED", False),
    "logo_led": ("LogoLED", False),
    "contract_power": ("ContractedPower", False),
    "contractedpower": ("ContractedPower", False),
    "contracted_power": ("ContractedPower", False),
}

# String-only fields (no float coercion).
# These pass through unchanged when present in /reported.
_REPORTED_STRING_FIELDS: dict[str, str] = {
    "device_id": "ID",
    "deviceid": "ID",
    "version": "FirmwareVersion",
    "firmware_version": "FirmwareVersion",
    "mac": "MAC",
}

# Keys (matching the LAN /RealTimeData payload) whose data is structurally
# absent from the V2C Cloud /reported and /currentstatecharge payloads.
# Entities backed by these keys cannot produce a useful value in cloud-only
# mode — they should advertise themselves as unavailable so the UI shows
# "Unavailable" rather than the misleading "Unknown" state.
LAN_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "ReadyState",
        "SignalStatus",
        "Timer",
        "ChargeMode",
        "DynamicPowerMode",
        "PauseDynamic",
        # Per-phase measurements exist only in the LAN /RealTimeData payload;
        # neither /device/reported nor /device/currentstatecharge carries them.
        "IntensityMeasure_L1",
        "IntensityMeasure_L2",
        "IntensityMeasure_L3",
        "VoltageMeasure_L1",
        "VoltageMeasure_L2",
        "VoltageMeasure_L3",
    }
)

# The published LAN /RealTimeData sample payload spells the first-phase current
# as `IntensityMeasure_L1y` while the keyword table documents
# `IntensityMeasure_L1`. Normalise the stray spelling onto the documented key
# before the entity layer reads it (entities look keys up exactly).
_REALTIME_KEY_ALIASES: dict[str, str] = {
    "IntensityMeasure_L1y": "IntensityMeasure_L1",
}


def _normalise_realtime_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Map stray key spellings onto the documented /RealTimeData keyword names.

    Mutates ``payload`` in place and returns it. An already-present documented
    key always wins over its alias.
    """
    for alias, documented in _REALTIME_KEY_ALIASES.items():
        if alias in payload and documented not in payload:
            payload[documented] = payload[alias]
    return payload


# The cloud and the LAN disagree on the ChargeState enum for the same physical
# quantity. The LAN codes are canonical for the entity layer (see
# const.CHARGE_STATE_LABELS), so cloud codes are translated during synthesis:
#   cloud 3 (ventilation required)      -> LAN 6 (STATE D)
#   cloud 4 (control pilot short circuit) -> LAN 5 (STATE E, CP / ground fault)
#   cloud 5 (general fault)             -> LAN 4 (STATE F, system fail / leak)
# Codes 0/1/2 (disconnected / connected / charging) agree in both enums.
_CLOUD_TO_LAN_CHARGE_STATE: dict[int, int] = {3: 6, 4: 5, 5: 4}

_INT_FIELDS = frozenset(
    {
        "ChargeState",
        "ChargeTime",
        "SlaveError",
        "Intensity",
        "Phases",
        "Paused",
        "ReadyState",
        "Timer",
        "Dynamic",
        "PhotovoltaicOn",
        "Locked",
    }
)

# Local keys that need explicit multiplicative normalisation when synthesised
# from the cloud /reported payload. The cloud and the LAN /RealTimeData
# disagree on unit prefix for these fields; the entity layer is hard-coded to
# the LAN convention, so the synthesis must rescale.
#
# Why each entry:
#   ContractedPower: cloud encodes the contract power as W/100 (e.g. "7" =
#     700 W = 0.7 kW, confirmed against a live install where the V2C app
#     showed 0.7 kW for cloud value "7"). The LAN /RealTimeData and the
#     Number entity use W (700); the entity then divides by 1000 in
#     source_to_native to render kW. Without this override the UI shows
#     "0.007 kW" for a 0.7 kW contract.
#   LightLED:        cloud sends a 0.0-1.0 fraction (e.g. "1.000000" = 100 %);
#     LAN/entity uses 0-100 % integer (see local_api.py:43 + README "0-100 %").
#     Without this override a LED set to 100 % via the V2C app renders as
#     "1 %" in HA.
_CLOUD_TO_LAN_MULTIPLIERS: dict[str, int] = {
    "ContractedPower": 100,
    "LightLED": 100,
}

# All power measurements (ChargePower, HousePower, FVPower, BatteryPower,
# GridPower) are reported by the cloud in kW, while the LAN /RealTimeData
# convention — and the entity layer hard-coded to it — uses W. Previously this
# was scaled via a heuristic that inferred kW vs W from the magnitude of the
# unrelated `voltage` field; that field doesn't correlate with the power unit
# and left the conversion unapplied whenever it was absent or out of range
# (e.g. issue #42, where ChargePower/HousePower stayed in kW but were labelled
# as W). The conversion is now applied unconditionally, like ContractedPower.
_CLOUD_POWER_KW_TO_W = 1000


def _build_realtime_from_reported(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> dict[str, Any]:
    """
    Convert cloud coordinator reported data to local /RealTimeData format.

    This allows sensors to work identically whether data comes from
    local HTTP or cloud API. No additional API calls are made —
    data is read from the cloud coordinator's cache.
    """
    device_state = get_device_state_from_coordinator(
        runtime_data.coordinator, device_id
    )
    reported = device_state.get("reported")
    if not isinstance(reported, dict) or not reported:
        _LOGGER.debug(
            "Cloud-only: no reported data for %s, returning empty payload", device_id
        )
        return {"_data_source": "cloud_reported_empty", "_lower_index": {}}

    reported_lower = {k.lower(): v for k, v in reported.items()}
    result: dict[str, Any] = {"_data_source": "cloud_reported"}

    for cloud_key, (local_key, is_power_kw) in _REPORTED_TO_REALTIME.items():
        if local_key in result:
            continue
        raw = reported_lower.get(cloud_key)
        if raw is None:
            continue
        try:
            value = float(str(raw))
        except (ValueError, TypeError):
            continue
        if is_power_kw:
            value = value * _CLOUD_POWER_KW_TO_W
        multiplier = _CLOUD_TO_LAN_MULTIPLIERS.get(local_key)
        if multiplier is not None:
            value = value * multiplier
        result[local_key] = int(value) if local_key in _INT_FIELDS else round(value, 2)

    # Augment with currentstatecharge data for missing real-time fields
    csc = device_state.get("additional", {}).get("currentstatecharge")
    if isinstance(csc, dict):
        csc_lower = {k.lower(): v for k, v in csc.items()}
        for cloud_key, (local_key, is_power_kw) in _REPORTED_TO_REALTIME.items():
            if local_key in result:
                continue
            raw = csc_lower.get(cloud_key)
            if raw is None:
                continue
            try:
                value = float(str(raw))
            except (ValueError, TypeError):
                continue
            if is_power_kw:
                value = value * _CLOUD_POWER_KW_TO_W
            multiplier = _CLOUD_TO_LAN_MULTIPLIERS.get(local_key)
            if multiplier is not None:
                value = value * multiplier
            result[local_key] = (
                int(value) if local_key in _INT_FIELDS else round(value, 2)
            )

    # Translate the cloud ChargeState enum onto the canonical LAN codes. Runs
    # exactly once, after both numeric loops, because the 4 <-> 5 mapping is a
    # swap and would cancel itself out if applied twice.
    charge_state = result.get("ChargeState")
    if isinstance(charge_state, int):
        translated = _CLOUD_TO_LAN_CHARGE_STATE.get(charge_state)
        if translated is not None:
            result["ChargeState"] = translated

    # String-only fields (device id, firmware version, MAC). Pass through
    # without numeric coercion — the synthesis loop above silently drops
    # these because float(str(...)) raises ValueError on non-numeric data.
    for cloud_key, local_key in _REPORTED_STRING_FIELDS.items():
        if local_key in result:
            continue
        raw = reported_lower.get(cloud_key)
        if raw is None or raw == "":
            continue
        result[local_key] = str(raw)

    # wifi_info is a JSON-encoded blob in /reported with the SSID + active
    # IP nested inside. Extract them so the wifi sensors work in cloud-only.
    wifi_raw = reported_lower.get("wifi_info")
    if isinstance(wifi_raw, str) and wifi_raw:
        try:
            wifi = json.loads(wifi_raw)
        except (ValueError, TypeError):
            wifi = None
        if isinstance(wifi, dict):
            ssid = wifi.get("ssid")
            if ssid and "SSID" not in result:
                result["SSID"] = str(ssid)
            ip = wifi.get("ip")
            if ip and "IP" not in result:
                result["IP"] = str(ip)

    result["_lower_index"] = {k.lower(): k for k in result if not k.startswith("_")}
    return result


class V2CLocalApiError(Exception):
    """Error raised when interacting with the local API."""


async def _async_read_keyword(
    session: ClientSession, ip: str, keyword: str
) -> tuple[str, float | None]:
    """
    Read a single keyword via GET /read/<keyword>.

    The endpoint returns a plain numeric value (e.g. ``1`` or ``50``).
    Returns ``(keyword, value)`` on success or ``(keyword, None)`` on any error
    so that failures never block the main coordinator update.
    """
    url = f"http://{ip}/read/{quote(keyword, safe='')}"
    try:
        async with async_timeout.timeout(LOCAL_TIMEOUT), session.get(url) as response:
            if response.status >= _HTTP_ERROR_THRESHOLD:
                return keyword, None
            text = (await response.text()).strip()
            return keyword, float(text)
    except (TimeoutError, ClientError, ValueError):
        return keyword, None


def _entry_data_of(runtime_data: V2CEntryRuntimeData) -> Mapping[str, Any]:
    """
    Return ``entry.data``, or an empty mapping when unavailable.

    The type check is against ``Mapping``, NOT ``dict``: Home Assistant hands
    out ``entry.data`` as a ``types.MappingProxyType``, which is a Mapping but
    is *not* a dict subclass. An ``isinstance(data, dict)`` guard here silently
    discarded the real config on every live instance — the manual IP overrides
    and the cached address book were never read — while passing every test,
    because the test doubles supplied plain dicts.
    """
    entry = getattr(runtime_data.coordinator, "config_entry", None)
    data = getattr(entry, "data", None)
    return data if isinstance(data, Mapping) else {}


def manual_ip_for(runtime_data: V2CEntryRuntimeData, device_id: str) -> str | None:
    """Return the user-supplied IP override for a charger, if any."""
    overrides = _entry_data_of(runtime_data).get(CONF_MANUAL_IPS)
    if isinstance(overrides, dict):
        candidate = overrides.get(device_id)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _ip_from_manual_override(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> str | None:
    """The address the user typed in the options flow."""
    return manual_ip_for(runtime_data, device_id)


def _ip_from_lan_verified(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> str | None:
    """
    The address that most recently answered ``/RealTimeData`` on the LAN.

    ``_static_ip`` is stamped onto the payload only by a successful local
    fetch, so its presence on a non-synthesised payload is direct evidence
    that this address reached this charger. Everything below this source is
    hearsay by comparison — the cloud repeats what it was last told, and the
    cache repeats what the cloud last said — which is why a DHCP move used to
    strand the integration on a dead address: the proven one was persisted
    into ``cached_pairings``, a source the stale cloud value outranks.
    """
    local_coordinator = runtime_data.local_coordinators.get(device_id)
    data = getattr(local_coordinator, "data", None) if local_coordinator else None
    if not isinstance(data, dict) or payload_is_cloud_synthesised(data):
        return None
    verified = data.get("_static_ip")
    return verified if isinstance(verified, str) and verified else None


def _ip_from_cloud_runtime(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> str | None:
    """The address currently advertised by the cloud coordinator."""
    device_state = get_device_state_from_coordinator(
        runtime_data.coordinator, device_id
    )
    # The charger re-uploads its own address on every cloud check-in, whereas
    # ``additional.static_ip`` is a registration field that only changes when
    # somebody edits it in the V2C portal. When the two disagree it is the
    # portal that has gone stale, so the self-report is consulted first.
    reported = device_state.get("reported")
    if isinstance(reported, dict):
        candidate = reported.get("ip") or reported.get("wifi_ip")
        if isinstance(candidate, str) and candidate:
            return candidate

    additional = device_state.get("additional")
    if isinstance(additional, dict):
        static_ip = additional.get("static_ip")
        if isinstance(static_ip, str) and static_ip:
            return static_ip

    data = getattr(runtime_data.coordinator, "data", None)
    pairings = data.get("pairings") if isinstance(data, dict) else None
    return _ip_in_records(pairings, device_id)


def _ip_from_offline_cache(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> str | None:
    """The address persisted in ``entry.data`` — survives a cloud outage."""
    return _ip_in_records(
        _entry_data_of(runtime_data).get(CONF_CACHED_PAIRINGS), device_id
    )


def _ip_from_local_payload(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> str | None:
    """The address reported by the charger itself on the last LAN poll."""
    local_coordinator = runtime_data.local_coordinators.get(device_id)
    if local_coordinator and isinstance(local_coordinator.data, dict):
        ip_value = local_coordinator.data.get(
            "_static_ip"
        ) or local_coordinator.data.get("IP")
        if isinstance(ip_value, str) and ip_value:
            return ip_value
    return None


def _ip_in_records(records: object, device_id: str) -> str | None:
    """Find ``device_id``'s ip in a list of ``{deviceId, ip}`` dicts."""
    if not isinstance(records, list):
        return None
    for item in records:
        if isinstance(item, dict) and item.get("deviceId") == device_id:
            maybe_ip = item.get("ip")
            if isinstance(maybe_ip, str) and maybe_ip:
                return maybe_ip
    return None


# Address sources in priority order. The user's explicit override wins, then
# an address that has actually answered on the LAN, then live cloud data, then
# the persisted cache, then whatever the charger last told us about itself.
# Steps 1, 2 and 4 are what keep the LAN transport alive during a total cloud
# outage: without them every source would be derived from live cloud data, so
# an authentication failure would leave the integration with no address at all
# and silently degrade a LAN install to cloud-only behaviour.
#
# Ordering rule: evidence outranks hearsay. Only the manual override sits above
# the LAN-verified address, because that override is a deliberate statement by
# the user rather than a guess the integration made on its own.
_IP_SOURCES: tuple[Callable[[V2CEntryRuntimeData, str], str | None], ...] = (
    _ip_from_manual_override,
    _ip_from_lan_verified,
    _ip_from_cloud_runtime,
    _ip_from_offline_cache,
    _ip_from_local_payload,
)


# Human-readable label per address source, for the diagnostic sensor.
_IP_SOURCE_LABELS: dict[str, str] = {
    "_ip_from_manual_override": "manual",
    "_ip_from_lan_verified": "lan",
    "_ip_from_cloud_runtime": "cloud",
    "_ip_from_offline_cache": "cache",
    "_ip_from_local_payload": "charger",
}


def describe_ip_source(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> tuple[str | None, str | None]:
    """Return ``(ip, source_label)`` naming which source supplied the address."""
    for source in _IP_SOURCES:
        candidate = source(runtime_data, device_id)
        if candidate:
            return candidate, _IP_SOURCE_LABELS.get(source.__name__)
    return None, None


def _looks_like_realtime(payload: dict[str, Any]) -> bool:
    """
    True when a parsed payload really came from a Trydan charger.

    Used before adopting an address that is not the charger's best-known one:
    any host can serve JSON, and a DHCP lease that has moved on to some other
    device must not be mistaken for the charger.
    """
    index = payload.get("_lower_index")
    return isinstance(index, dict) and "chargestate" in index


def payload_is_cloud_synthesised(data: object) -> bool:
    """
    True when a local payload was synthesised from cloud data, not fetched.

    `_build_realtime_from_reported` tags what it produces; a real
    ``/RealTimeData`` response carries no such marker. Entities use this to
    tell "the charger told us" from "we inferred it from the cloud".
    """
    return isinstance(data, dict) and str(data.get("_data_source", "")).startswith(
        "cloud_reported"
    )


def payload_is_empty(data: object) -> bool:
    """True when neither transport produced anything for this charger."""
    return isinstance(data, dict) and data.get("_data_source") == "cloud_reported_empty"


def active_transport(runtime_data: V2CEntryRuntimeData, device_id: str) -> str:
    """
    Return which transport is currently carrying this charger's data.

    ``lan``     the charger answered on the local network;
    ``cloud``   values are synthesised from the V2C Cloud;
    ``offline`` neither transport has produced anything.
    """
    local_coordinator = runtime_data.local_coordinators.get(device_id)
    data = getattr(local_coordinator, "data", None) if local_coordinator else None
    if isinstance(data, dict):
        if payload_is_empty(data):
            return "offline"
        if not payload_is_cloud_synthesised(data):
            return "lan"
        return "cloud"
    cloud_state = get_device_state_from_coordinator(runtime_data.coordinator, device_id)
    return "cloud" if cloud_state.get("reported") else "offline"


def resolve_static_ip(runtime_data: V2CEntryRuntimeData, device_id: str) -> str | None:
    """Return the static IP address associated with a charger, if known."""
    for source in _IP_SOURCES:
        candidate = source(runtime_data, device_id)
        if candidate:
            return candidate
    return None


def candidate_ips(runtime_data: V2CEntryRuntimeData, device_id: str) -> list[str]:
    """
    Return every address worth trying for a charger, best first.

    A manual override is returned alone. The user pinned that address on
    purpose, so quietly succeeding against a different one would hide the very
    misconfiguration the override exists to express — better to fail visibly.

    Otherwise the known addresses are returned in source order, de-duplicated
    and filtered through the SSRF guard. Having more than one matters when the
    charger's address changes under DHCP: the stale entry is tried first and
    fails, and the poll can still find the charger at one of the others
    instead of waiting for a human to notice.
    """
    manual = _ip_from_manual_override(runtime_data, device_id)
    if manual:
        is_safe, _err = validate_private_ip(manual)
        return [manual] if is_safe else []

    candidates: list[str] = []
    for source in _IP_SOURCES:
        candidate = source(runtime_data, device_id)
        if not candidate or candidate in candidates:
            continue
        is_safe, _err = validate_private_ip(candidate)
        if is_safe:
            candidates.append(candidate)
    return candidates


def get_local_data(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> dict[str, Any] | None:
    """Return the latest cached local real-time payload for a charger."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if coordinator and isinstance(coordinator.data, dict):
        return coordinator.data
    return None


def get_local_value(local_data: dict[str, Any], key: str) -> tuple[bool, Any]:
    """
    Case-insensitive key lookup in a local RealTimeData payload.

    Returns (found, value). Tries exact match first, then uses the pre-built
    ``_lower_index`` map (populated by the coordinator fetch) for O(1) lookup.
    Falls back to a linear scan when the index is absent.
    """
    if key in local_data:
        return True, local_data[key]
    lower = key.lower()
    index = local_data.get("_lower_index")
    if isinstance(index, dict):
        original = index.get(lower)
        if original is not None:
            return True, local_data.get(original)
        return False, None
    # Fallback O(n) scan for payloads without a pre-built index.
    for k, v in local_data.items():
        if not k.startswith("_") and k.lower() == lower:
            return True, v
    return False, None


async def async_request_local_refresh(
    runtime_data: V2CEntryRuntimeData, device_id: str
) -> None:
    """Trigger an immediate refresh of the local data coordinator if available."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if coordinator:
        try:
            await coordinator.async_request_refresh()
        except UpdateFailed as err:
            _LOGGER.debug("Failed to refresh local data for %s: %s", device_id, err)


async def async_write_keyword(  # noqa: PLR0913
    hass: HomeAssistant,
    runtime_data: V2CEntryRuntimeData,
    device_id: str,
    keyword: str,
    value: float | str | bool,
    *,
    refresh_local: bool = True,
) -> None:
    """Send a write command to the local API."""
    static_ip = resolve_static_ip(runtime_data, device_id)
    if not static_ip:
        raise V2CLocalApiError("Static IP for device is unavailable")

    # Distinguish parse failures from policy violations so the developer-facing
    # error is actionable. validate_private_ip groups both behind the
    # ``cannot_connect_local`` translation key for UI parity; the write path
    # benefits from the finer-grained distinction.
    import ipaddress as _ip_mod  # noqa: PLC0415

    try:
        _ip_mod.ip_address(static_ip)
    except ValueError as err:
        raise V2CLocalApiError(f"Invalid IP address for device: {static_ip!r}") from err
    is_safe, _error_key = validate_private_ip(static_ip)
    if not is_safe:
        raise V2CLocalApiError(
            f"Refusing write to non-private/loopback/link-local IP {static_ip} — possible SSRF"
        )

    keyword_clean = keyword.strip()
    # Reject keywords outside the documented writeable set to limit SSRF surface
    # and accidental misuse from automations.
    if keyword_clean not in WRITEABLE_KEYWORDS:
        raise V2CLocalApiError(
            f"Refusing to write unknown keyword {keyword_clean!r}; "
            "must be one of the documented writeable Trydan registers"
        )
    value_str = str(int(value)) if isinstance(value, bool) else str(value)
    url = f"http://{static_ip}/write/{quote(keyword_clean, safe='')}={quote(value_str, safe='')}"

    session = async_get_clientsession(hass)
    try:
        async with async_timeout.timeout(LOCAL_TIMEOUT), session.get(url) as response:
            body = await response.text()
            if response.status >= _HTTP_ERROR_THRESHOLD:
                raise V2CLocalApiError(
                    f"Local API returned HTTP {response.status} for {keyword_clean}: {body}"
                )
    except TimeoutError as err:
        _schedule_followup_refresh(hass, runtime_data, device_id)
        raise V2CLocalApiError(
            f"Timeout while calling local API for {keyword_clean}"
        ) from err
    except ClientError as err:
        _schedule_followup_refresh(hass, runtime_data, device_id)
        raise V2CLocalApiError(
            f"Error while calling local API for {keyword_clean}: {err}"
        ) from err

    if refresh_local:
        await async_request_local_refresh(runtime_data, device_id)


# ---------------------------------------------------------------------------
# Smart LAN-vs-cloud router
# ---------------------------------------------------------------------------
# Public helpers shared by services (__init__.py) and the entity platforms
# (number.py / switch.py / select.py). Previously defined privately in
# __init__.py; promoted to local_api.py so entity setters can use the same
# router without a circular import on the package's top-level module.


def is_cloud_only_device(entry_data: dict[str, Any]) -> bool:
    """Return True when the entry is configured as cloud-only (no LAN)."""
    return bool(entry_data.get(CONF_CLOUD_ONLY))


def config_data_for(runtime_data: V2CEntryRuntimeData) -> dict[str, Any]:
    """Return the underlying ConfigEntry.data for the given runtime data."""
    return dict(runtime_data.coordinator.config_entry.data)


async def async_route_local_or_cloud(  # noqa: PLR0913
    hass: HomeAssistant,
    runtime_data: V2CEntryRuntimeData,
    device_id: str,
    *,
    keyword: str,
    value: float | str | bool,
    cloud_call: Callable[[], Awaitable[Any]] | None,
    config_data: dict[str, Any] | None = None,
) -> None:
    """
    Send a control command via LAN when possible, otherwise via cloud.

    ``cloud_call`` is a zero-argument factory that returns the awaitable
    cloud-fallback coroutine when invoked, OR ``None`` for keywords that
    have no V2C Cloud endpoint — e.g. ``LightLED`` and ``ContractedPower``,
    which are LAN-write-only. The factory shape (rather than passing a
    pre-constructed coroutine) avoids the ``RuntimeWarning: coroutine
    was never awaited`` that otherwise pollutes logs on the LAN-success
    happy path. The router prefers LAN: it tries ``async_write_keyword``
    first, and only invokes the factory when the LAN write raises
    ``V2CLocalApiError`` (no IP, SSRF, timeout, HTTP error...). For
    explicitly cloud-only devices (4G), the LAN attempt is skipped
    entirely; if ``cloud_call`` is ``None`` in cloud-only mode the
    function raises a ``HomeAssistantError`` with a user-facing message
    stating that the control cannot be operated remotely.

    Lazy import of v2c_cloud exception classes keeps local_api.py importable
    by v2c_cloud.py (no cycle).
    """
    # Lazy import to avoid a circular dependency at module-load time:
    # local_api may be imported before v2c_cloud's exceptions are defined
    # in some testing scenarios.
    # HA exceptions are also imported lazily for symmetry.
    from homeassistant.exceptions import (  # noqa: PLC0415
        ConfigEntryAuthFailed,
        HomeAssistantError,
    )

    from .v2c_cloud import V2CAuthError, V2CRequestError  # noqa: PLC0415

    cfg = config_data if config_data is not None else config_data_for(runtime_data)
    cloud_only = is_cloud_only_device(cfg)
    if not cloud_only:
        try:
            await async_write_keyword(hass, runtime_data, device_id, keyword, value)
            _LOGGER.debug("V2C router: LAN path used for %s/%s", device_id, keyword)
        except V2CLocalApiError as err:
            _LOGGER.debug(
                "V2C router: LAN failed for %s/%s (%s) — falling back to cloud",
                device_id,
                keyword,
                err,
            )
        else:
            return

    if cloud_call is None:
        # Be precise about WHICH of the two conditions failed. Saying
        # "cloud-only mode" on a Wi-Fi entry whose LAN write just failed sends
        # users looking for a configuration problem that does not exist.
        if cloud_only:
            detail = (
                "this entry is configured as Cloud only (4G), and the V2C "
                "Cloud API exposes no remote setter for this control"
            )
        else:
            detail = (
                "the charger could not be reached on the LAN and the V2C "
                "Cloud API exposes no remote setter for this control, so "
                "there is no transport left to carry the change"
            )
        raise HomeAssistantError(
            f"Cannot set {keyword!r} from Home Assistant: {detail}. Adjust it "
            "via the V2C app (which uses a different transport), or restore "
            "LAN reachability — check that the charger is powered, on the "
            "same network, and that its IP is known (you can set it manually "
            "in the integration options)."
        )

    try:
        await cloud_call()
    except V2CAuthError as err:
        raise ConfigEntryAuthFailed(
            "Authentication failed during cloud control call"
        ) from err
    except V2CRequestError as err:
        raise HomeAssistantError(str(err)) from err
    _LOGGER.debug("V2C router: cloud path used for %s/%s", device_id, keyword)


async def _async_fetch_realtime(
    session: ClientSession, device_id: str, ip: str, retries: int
) -> dict[str, Any]:
    """
    GET and parse ``/RealTimeData`` from one address.

    Raises ``UpdateFailed`` when the address does not answer within ``retries``
    attempts, or answers with something that is not a usable RealTimeData
    document.
    """
    url = f"http://{ip}/RealTimeData"
    attempt = 1
    last_error: Exception | None = None
    while True:
        try:
            async with (
                async_timeout.timeout(LOCAL_TIMEOUT),
                session.get(url) as response,
            ):
                text = await response.text()
            break
        except TimeoutError as err:
            last_error = err
            error_message = "Timeout while fetching local real-time data"
        except ClientError as err:
            last_error = err
            error_message = f"Error while fetching local real-time data: {err}"

        if attempt >= retries:
            raise UpdateFailed(
                f"{error_message} after {retries} attempt(s)"
            ) from last_error

        delay = LOCAL_RETRY_BACKOFF * attempt
        _LOGGER.debug(
            "Local realtime fetch failed for %s at %s (attempt %s/%s): %s. "
            "Retrying in %.1f s",
            device_id,
            ip,
            attempt,
            retries,
            last_error,
            delay,
        )
        attempt += 1
        await asyncio.sleep(delay)

    payload_text = text.strip().rstrip("%").strip()
    if not payload_text:
        raise UpdateFailed("Empty response from local RealTimeData endpoint")

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as err:
        raise UpdateFailed(
            f"Invalid JSON response from local endpoint: {payload_text}"
        ) from err

    if not isinstance(payload, dict):
        raise UpdateFailed("Unexpected payload type from local endpoint")

    payload["_static_ip"] = ip

    # Normalise documented key spellings before anything reads the payload.
    _normalise_realtime_keys(payload)

    # Pre-build a lowercase-key → original-key index for O(1) case-insensitive lookups.
    payload["_lower_index"] = {k.lower(): k for k in payload if not k.startswith("_")}
    return payload


async def async_get_or_create_local_coordinator(
    hass: HomeAssistant,
    runtime_data: V2CEntryRuntimeData,
    device_id: str,
) -> DataUpdateCoordinator:
    """Return a coordinator fetching local real-time data, creating it if needed."""
    if device_id in runtime_data.local_coordinators:
        coordinator = runtime_data.local_coordinators[device_id]
        if not coordinator.last_update_success:
            await coordinator.async_request_refresh()
        return coordinator

    session = async_get_clientsession(hass)
    failure_count = 0

    async def _async_fetch_local_data() -> dict[str, Any]:
        nonlocal failure_count
        # Cloud-only shortcut: explicit ``cloud_only`` marker on the entry
        # means the device has no LAN reachability (e.g. 4G Trydan).
        # Skip the local fetch entirely.
        entry_data = runtime_data.coordinator.config_entry.data
        if entry_data.get("cloud_only"):
            return _build_realtime_from_reported(runtime_data, device_id)

        candidates = candidate_ips(runtime_data, device_id)
        if not candidates:
            # No usable IP found anywhere → cloud-only fallback
            return _build_realtime_from_reported(runtime_data, device_id)

        payload: dict[str, Any] | None = None
        static_ip = ""
        last_failure: UpdateFailed | None = None
        for index, ip in enumerate(candidates):
            # Only the best candidate gets the full retry budget. The rest are
            # long shots on an already-failing poll and are tried once each, so
            # a charger that moved is still found without the fetch outlasting
            # the poll interval.
            retries = LOCAL_MAX_RETRIES if index == 0 else 1
            try:
                found = await _async_fetch_realtime(session, device_id, ip, retries)
            except UpdateFailed as err:
                last_failure = err
                continue
            if not _looks_like_realtime(found):
                # Something answered, but it is not the charger. A vacated DHCP
                # lease gets handed to another device, and that device may well
                # serve JSON of its own — adopting it would fill the entities
                # with a stranger's data.
                _LOGGER.debug(
                    "V2C %s: %s answered but the payload is not RealTimeData; ignoring",
                    device_id,
                    ip,
                )
                continue
            if index:
                _LOGGER.info(
                    "V2C %s: %s stopped answering; found the charger at %s instead "
                    "and adopted the new address",
                    device_id,
                    candidates[0],
                    ip,
                )
            payload, static_ip = found, ip
            break

        if payload is None:
            failure_count += 1
            # Fall back to cloud data instead of failing entirely
            cloud_payload = _build_realtime_from_reported(runtime_data, device_id)
            if cloud_payload.get("_data_source") != "cloud_reported_empty":
                _LOGGER.debug(
                    "Local API unreachable for %s at %s, falling back to cloud "
                    "reported data",
                    device_id,
                    ", ".join(candidates),
                )
                return cloud_payload
            raise last_failure or UpdateFailed(
                "Local RealTimeData unreachable and no cloud data available"
            )

        # Fetch writable keys absent from /RealTimeData (e.g. LogoLED)
        extra = await asyncio.gather(
            *(
                _async_read_keyword(session, static_ip, kw)
                for kw in _READ_ONLY_KEYWORDS
            ),
            return_exceptions=True,
        )
        for result in extra:
            if isinstance(result, tuple):
                kw, val = result
                if val is not None:
                    payload[kw] = val

        if failure_count:
            _LOGGER.debug(
                "Local API for %s recovered after %s failure(s)",
                device_id,
                failure_count,
            )
        failure_count = 0

        # This address just proved it reaches the charger — persist it so the
        # entry keeps a usable LAN address across restarts even if the cloud
        # (the only other writer of the cache) never answers again.
        _persist_lan_observed_ip(
            hass, runtime_data.coordinator.config_entry, device_id, static_ip
        )

        return payload

    # Detect cloud-only to use longer poll interval and log once
    entry_obj = runtime_data.coordinator.config_entry
    _entry_data = entry_obj.data
    _options = entry_obj.options or {}
    # The entry's own flag is the ONLY thing that decides the transport. It
    # used to be ORed with "no usable IP right now", which silently demoted a
    # Wi-Fi install to cloud-only behaviour for as long as the cloud (the only
    # address source at the time) was unreachable.
    _explicit_cloud = bool(_entry_data.get(CONF_CLOUD_ONLY))
    _ip = resolve_static_ip(runtime_data, device_id)
    _is_safe, _ = validate_private_ip(_ip) if _ip else (False, None)
    _lan_address_known = bool(_is_safe)

    if _explicit_cloud:
        interval = CLOUD_ONLY_UPDATE_INTERVAL
        _LOGGER.info(
            "V2C %s: cloud-only mode (4G), sensors from cloud reported data", device_id
        )
    else:
        # A LAN entry keeps the LAN cadence even when the address is momentarily
        # unknown (e.g. the cloud is down and nothing has been cached yet), so
        # the charger recovers by itself the moment an address appears —
        # whether from cloud recovery, the persisted cache or a manual override.
        interval = _build_local_interval(_entry_data, _options)
        if not _lan_address_known:
            _LOGGER.warning(
                "V2C %s: no LAN address known yet (cloud unreachable and no "
                "cached or manual IP). Polling continues at the LAN cadence; "
                "set the charger IP in the integration options to recover "
                "immediately.",
                device_id,
            )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"V2C local realtime {device_id}",
        update_method=_async_fetch_local_data,
        update_interval=interval,
    )

    runtime_data.local_coordinators[device_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, UpdateFailed) as err:
        _LOGGER.debug("Initial local fetch pending for %s: %s", device_id, err)

    return coordinator


def _schedule_followup_refresh(
    hass: HomeAssistant, runtime_data: V2CEntryRuntimeData, device_id: str
) -> None:
    """Schedule a follow-up refresh shortly after a failed write."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if not coordinator:
        return

    def _refresh_callback(_now: Any) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    async_call_later(hass, LOCAL_WRITE_RETRY_DELAY, _refresh_callback)
