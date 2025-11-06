"""Helpers for interacting with the V2C charger local HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import async_timeout
from aiohttp import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .entity import get_device_state_from_coordinator

_LOGGER = logging.getLogger(__name__)

LOCAL_TIMEOUT = 10


class V2CLocalApiError(Exception):
    """Error raised when interacting with the local API."""


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
        raise V2CLocalApiError(f"Timeout while calling local API for {keyword_clean}") from err
    except ClientError as err:
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
            await coordinator.async_refresh()
        return coordinator

    session = async_get_clientsession(hass)

    async def _async_fetch_local_data() -> dict[str, Any]:
        static_ip = resolve_static_ip(runtime_data, device_id)
        if not static_ip:
            raise UpdateFailed("Static IP for device is unavailable")

        url = f"http://{static_ip}/RealTimeData"
        try:
            async with async_timeout.timeout(LOCAL_TIMEOUT):
                async with session.get(url) as response:
                    text = await response.text()
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout while fetching local real-time data") from err
        except ClientError as err:
            raise UpdateFailed(f"Error while fetching local real-time data: {err}") from err

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

        return payload

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"V2C local realtime {device_id}",
        update_method=_async_fetch_local_data,
        update_interval=timedelta(seconds=30),
    )

    runtime_data.local_coordinators[device_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        _LOGGER.debug("Initial local fetch failed for %s: %s", device_id, err)

    return coordinator
