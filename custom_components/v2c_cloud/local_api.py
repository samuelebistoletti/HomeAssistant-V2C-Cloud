"""Helpers for interacting with the V2C charger local HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
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
from .const import (
    CLOUD_ONLY_UPDATE_INTERVAL,
    CONF_LOCAL_UPDATE_INTERVAL,
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
# LightLED and LogoLED are LED intensity (0-100%) and need explicit /read/.
_READ_ONLY_KEYWORDS: tuple[str, ...] = ("LogoLED", "LightLED")

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

    Cloud-only devices (no ``fallback_ip``) keep ``CLOUD_ONLY_UPDATE_INTERVAL``;
    LAN devices honour ``options[CONF_LOCAL_UPDATE_INTERVAL]`` when set, falling
    back to ``DEFAULT_LOCAL_INTERVAL``. Always returns a ``timedelta``.
    """
    fip = entry_data.get("fallback_ip")
    if "fallback_ip" in entry_data and (not fip or fip == "0.0.0.0"):  # noqa: S104 — sentinel, not bind  # nosec B104
        return CLOUD_ONLY_UPDATE_INTERVAL
    seconds = options.get(CONF_LOCAL_UPDATE_INTERVAL)
    if not isinstance(seconds, int) or seconds <= 0:
        seconds = DEFAULT_LOCAL_INTERVAL
    return timedelta(seconds=seconds)


# Mapping: cloud reported key (lowercase) → (local RealTimeData key, needs_scale)
#
# Sources confirmed against real `/device/reported` + `/device/currentstatecharge`
# payloads on a Trydan XQUXDU running firmware 2.4.6 (see docs/cloud-payload-keys
# for the dump used during the 2026-05-19 audit).
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
    "voltage": ("VoltageInstallation", True),
    "voltageinstallation": ("VoltageInstallation", True),
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
    "cp_level": ("CpLevel", False),
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

_INT_FIELDS = frozenset(
    {
        "ChargeState",
        "ChargeTime",
        "SlaveError",
        "Intensity",
        "Phases",
        "Paused",
        "CpLevel",
        "ReadyState",
        "Timer",
        "Dynamic",
        "PhotovoltaicOn",
        "Locked",
    }
)


def _detect_cloud_scale(reported: dict[str, object]) -> float:
    """Detect if cloud values are in kW/kV vs W/V using voltage as indicator."""
    for key in ("voltage", "voltageinstallation"):
        raw = reported.get(key)
        if raw is not None:
            try:
                v = float(str(raw))
                if 0 < v < 10:  # noqa: PLR2004 — voltage in kV would be < 10 V
                    return 1000  # kV → V
            except (ValueError, TypeError):
                pass
    return 1


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
    scale = _detect_cloud_scale(reported_lower)
    result: dict[str, Any] = {"_data_source": "cloud_reported"}

    for cloud_key, (local_key, needs_scale) in _REPORTED_TO_REALTIME.items():
        if local_key in result:
            continue
        raw = reported_lower.get(cloud_key)
        if raw is None:
            continue
        try:
            value = float(str(raw))
        except (ValueError, TypeError):
            continue
        if needs_scale:
            value = value * scale
        result[local_key] = int(value) if local_key in _INT_FIELDS else round(value, 2)

    # Augment with currentstatecharge data for missing real-time fields
    csc = device_state.get("additional", {}).get("currentstatecharge")
    if isinstance(csc, dict):
        csc_lower = {k.lower(): v for k, v in csc.items()}
        csc_scale = _detect_cloud_scale(csc_lower)
        for cloud_key, (local_key, needs_scale) in _REPORTED_TO_REALTIME.items():
            if local_key in result:
                continue
            raw = csc_lower.get(cloud_key)
            if raw is None:
                continue
            try:
                value = float(str(raw))
            except (ValueError, TypeError):
                continue
            if needs_scale:
                value = value * csc_scale
            result[local_key] = (
                int(value) if local_key in _INT_FIELDS else round(value, 2)
            )

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


def resolve_static_ip(runtime_data: V2CEntryRuntimeData, device_id: str) -> str | None:
    """Return the static IP address associated with a charger, if known."""
    device_state = get_device_state_from_coordinator(
        runtime_data.coordinator, device_id
    )
    additional = device_state.get("additional")
    if isinstance(additional, dict):
        static_ip = additional.get("static_ip")
        if isinstance(static_ip, str) and static_ip:
            return static_ip

    local_coordinator = runtime_data.local_coordinators.get(device_id)
    if local_coordinator and isinstance(local_coordinator.data, dict):
        ip_value = local_coordinator.data.get(
            "_static_ip"
        ) or local_coordinator.data.get("IP")
        if isinstance(ip_value, str) and ip_value:
            return ip_value

    reported = device_state.get("reported")
    if isinstance(reported, dict):
        candidate = reported.get("ip") or reported.get("wifi_ip")
        if isinstance(candidate, str) and candidate:
            return candidate

    pairings = (
        runtime_data.coordinator.data.get("pairings")
        if runtime_data.coordinator.data
        else []
    )
    if isinstance(pairings, list):
        for item in pairings:
            if item.get("deviceId") == device_id:
                maybe_ip = item.get("ip")
                if isinstance(maybe_ip, str) and maybe_ip:
                    return maybe_ip

    return None


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
        # Cloud-only shortcut: if the config entry explicitly has an empty
        # or placeholder fallback_ip, this is a known cloud-only device
        # (e.g. 4G Trydan with no local API). Skip local fetch entirely.
        entry_data = runtime_data.coordinator.config_entry.data
        if "fallback_ip" in entry_data:
            fip = entry_data["fallback_ip"]
            if not fip or fip == "0.0.0.0":  # noqa: S104 — sentinel, not bind  # nosec B104
                return _build_realtime_from_reported(runtime_data, device_id)

        static_ip = resolve_static_ip(runtime_data, device_id)
        if not static_ip:
            # No IP found anywhere → cloud-only fallback
            return _build_realtime_from_reported(runtime_data, device_id)
        is_safe, _err = validate_private_ip(static_ip)
        if not is_safe:
            # Invalid / non-routable IP → cloud-only fallback
            return _build_realtime_from_reported(runtime_data, device_id)

        url = f"http://{static_ip}/RealTimeData"
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

            if attempt >= LOCAL_MAX_RETRIES:
                failure_count += 1
                # Fall back to cloud data instead of failing entirely
                cloud_payload = _build_realtime_from_reported(runtime_data, device_id)
                if cloud_payload.get("_data_source") != "cloud_reported_empty":
                    _LOGGER.debug(
                        "Local API unreachable for %s after %s attempt(s), "
                        "falling back to cloud reported data",
                        device_id,
                        LOCAL_MAX_RETRIES,
                    )
                    return cloud_payload
                raise UpdateFailed(
                    f"{error_message} after {LOCAL_MAX_RETRIES} attempt(s)"
                ) from last_error

            delay = LOCAL_RETRY_BACKOFF * attempt
            _LOGGER.debug(
                "Local realtime fetch failed for %s (attempt %s/%s): %s. Retrying in %.1f s",
                device_id,
                attempt,
                LOCAL_MAX_RETRIES,
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

        payload["_static_ip"] = static_ip

        # Pre-build a lowercase-key → original-key index for O(1) case-insensitive lookups.
        payload["_lower_index"] = {
            k.lower(): k for k in payload if not k.startswith("_")
        }

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

        return payload

    # Detect cloud-only to use longer poll interval and log once
    entry_obj = runtime_data.coordinator.config_entry
    _entry_data = entry_obj.data
    _options = entry_obj.options or {}
    _explicit_cloud = "fallback_ip" in _entry_data and (
        not _entry_data["fallback_ip"] or _entry_data["fallback_ip"] == "0.0.0.0"  # noqa: S104 — sentinel, not bind  # nosec B104
    )
    if not _explicit_cloud:
        _ip = resolve_static_ip(runtime_data, device_id)
        _is_safe, _ = validate_private_ip(_ip) if _ip else (False, None)
        _explicit_cloud = not _is_safe

    if _explicit_cloud:
        interval = CLOUD_ONLY_UPDATE_INTERVAL
        _LOGGER.info(
            "V2C %s: cloud-only mode (4G), sensors from cloud reported data", device_id
        )
    else:
        interval = _build_local_interval(_entry_data, _options)

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
