"""Helpers for interacting with the V2C charger local HTTP API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import async_timeout
from aiohttp import ClientError, ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .entity import get_device_state_from_coordinator

_LOGGER = logging.getLogger(__name__)

LOCAL_TIMEOUT = 10
LOCAL_MAX_RETRIES = 3
LOCAL_RETRY_BACKOFF = 1.5
LOCAL_UPDATE_INTERVAL = timedelta(seconds=30)
LOCAL_WRITE_RETRY_DELAY = 5

# Keywords writable via /write/ but absent from /RealTimeData.
# Must be read individually via GET /read/<KeyWord>.
_READ_ONLY_KEYWORDS: tuple[str, ...] = ("LogoLED",)


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
            if response.status >= 400:  # noqa: PLR2004
                return keyword, None
            text = (await response.text()).strip()
            return keyword, float(text)
    except (TimeoutError, ClientError, ValueError):
        return keyword, None


def resolve_static_ip(runtime_data, device_id: str) -> str | None:
    """Return the static IP address associated with a charger, if known."""
    device_state = get_device_state_from_coordinator(runtime_data.coordinator, device_id)
    additional = device_state.get("additional")
    if isinstance(additional, dict):
        static_ip = additional.get("static_ip")
        if isinstance(static_ip, str) and static_ip:
            return static_ip

    local_coordinator = runtime_data.local_coordinators.get(device_id)
    if local_coordinator and isinstance(local_coordinator.data, dict):
        ip_value = local_coordinator.data.get("_static_ip") or local_coordinator.data.get("IP")
        if isinstance(ip_value, str) and ip_value:
            return ip_value

    reported = device_state.get("reported")
    if isinstance(reported, dict):
        candidate = reported.get("ip") or reported.get("wifi_ip")
        if isinstance(candidate, str) and candidate:
            return candidate

    pairings = runtime_data.coordinator.data.get("pairings") if runtime_data.coordinator.data else []
    if isinstance(pairings, list):
        for item in pairings:
            if item.get("deviceId") == device_id:
                maybe_ip = item.get("ip")
                if isinstance(maybe_ip, str) and maybe_ip:
                    return maybe_ip

    return None


def get_local_data(runtime_data, device_id: str) -> dict[str, Any] | None:
    """Return the latest cached local real-time payload for a charger."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if coordinator and isinstance(coordinator.data, dict):
        return coordinator.data
    return None


def get_local_value(local_data: dict[str, Any], key: str) -> tuple[bool, Any]:
    """
    Case-insensitive key lookup in a local RealTimeData payload.

    Returns (found, value). Tries exact match first, then falls back to a
    case-insensitive scan so that keys like ``LogoLED`` / ``Logoled`` are
    treated as equivalent regardless of what casing the device firmware uses.
    """
    if key in local_data:
        return True, local_data[key]
    lower = key.lower()
    for k, v in local_data.items():
        if k.lower() == lower:
            return True, v
    return False, None


async def async_request_local_refresh(runtime_data, device_id: str) -> None:
    """Trigger an immediate refresh of the local data coordinator if available."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if coordinator:
        try:
            await coordinator.async_request_refresh()
        except UpdateFailed as err:
            _LOGGER.debug("Failed to refresh local data for %s: %s", device_id, err)


async def async_write_keyword(
    hass: HomeAssistant,
    runtime_data,
    device_id: str,
    keyword: str,
    value: str | int | float | bool,
    *,
    refresh_local: bool = True,
) -> None:
    """Send a write command to the local API."""
    static_ip = resolve_static_ip(runtime_data, device_id)
    if not static_ip:
        raise V2CLocalApiError("Static IP for device is unavailable")

    try:
        ipaddress.ip_address(static_ip)
    except ValueError as err:
        raise V2CLocalApiError(f"Invalid IP address for device: {static_ip!r}") from err

    keyword_clean = keyword.strip()
    value_str = str(int(value)) if isinstance(value, bool) else str(value)
    url = f"http://{static_ip}/write/{quote(keyword_clean, safe='')}={quote(value_str, safe='')}"

    session = async_get_clientsession(hass)
    try:
        async with async_timeout.timeout(LOCAL_TIMEOUT):
            async with session.get(url) as response:
                body = await response.text()
                if response.status >= 400:
                    raise V2CLocalApiError(
                        f"Local API returned HTTP {response.status} for {keyword_clean}: {body}"
                    )
    except asyncio.TimeoutError as err:
        _schedule_followup_refresh(hass, runtime_data, device_id)
        raise V2CLocalApiError(f"Timeout while calling local API for {keyword_clean}") from err
    except ClientError as err:
        _schedule_followup_refresh(hass, runtime_data, device_id)
        raise V2CLocalApiError(f"Error while calling local API for {keyword_clean}: {err}") from err

    if refresh_local:
        await async_request_local_refresh(runtime_data, device_id)


async def async_get_or_create_local_coordinator(
    hass: HomeAssistant,
    runtime_data,
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
        static_ip = resolve_static_ip(runtime_data, device_id)
        if not static_ip:
            raise UpdateFailed("Static IP for device is unavailable")

        url = f"http://{static_ip}/RealTimeData"
        attempt = 1
        last_error: Exception | None = None
        while True:
            try:
                async with async_timeout.timeout(LOCAL_TIMEOUT):
                    async with session.get(url) as response:
                        text = await response.text()
                break
            except asyncio.TimeoutError as err:
                last_error = err
                error_message = "Timeout while fetching local real-time data"
            except ClientError as err:
                last_error = err
                error_message = f"Error while fetching local real-time data: {err}"

            if attempt >= LOCAL_MAX_RETRIES:
                failure_count += 1
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
            raise UpdateFailed(f"Invalid JSON response from local endpoint: {payload_text}") from err

        if not isinstance(payload, dict):
            raise UpdateFailed("Unexpected payload type from local endpoint")

        payload["_static_ip"] = static_ip

        # Fetch writable keys absent from /RealTimeData (e.g. LogoLED)
        extra = await asyncio.gather(
            *(_async_read_keyword(session, static_ip, kw) for kw in _READ_ONLY_KEYWORDS),
            return_exceptions=True,
        )
        for result in extra:
            if isinstance(result, tuple):
                kw, val = result
                if val is not None:
                    payload[kw] = val

        device_state = get_device_state_from_coordinator(runtime_data.coordinator, device_id)
        if isinstance(device_state, dict):
            additional = device_state.setdefault("additional", {})
            for key in (
                "DynamicPowerMode",
                "ContractedPower",
                "Paused",
                "Locked",
            ):
                if key in payload:
                    additional[key.lower()] = payload[key]

        if failure_count:
            _LOGGER.debug("Local API for %s recovered after %s failure(s)", device_id, failure_count)
        failure_count = 0

        return payload

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"V2C local realtime {device_id}",
        update_method=_async_fetch_local_data,
        update_interval=LOCAL_UPDATE_INTERVAL,
    )

    runtime_data.local_coordinators[device_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, UpdateFailed) as err:
        _LOGGER.debug("Initial local fetch pending for %s: %s", device_id, err)

    return coordinator


def _schedule_followup_refresh(hass: HomeAssistant, runtime_data, device_id: str) -> None:
    """Schedule a follow-up refresh shortly after a failed write."""
    coordinator = runtime_data.local_coordinators.get(device_id)
    if not coordinator:
        return

    def _refresh_callback(_now):
        hass.async_create_task(coordinator.async_request_refresh())

    async_call_later(hass, LOCAL_WRITE_RETRY_DELAY, _refresh_callback)
