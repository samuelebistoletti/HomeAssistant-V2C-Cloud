"""Home Assistant integration setup for V2C Cloud."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    ATTR_DEVICE_ID,
    ATTR_DAYS_OF_WEEK,
    ATTR_RFID_CODE,
    ATTR_RFID_TAG,
    ATTR_TIME_END,
    ATTR_TIME_START,
    ATTR_TIMER_ID,
    ATTR_WIFI_PASSWORD,
    ATTR_WIFI_SSID,
    CONF_API_KEY,
    CONF_BASE_URL,
    DEFAULT_BASE_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    SERVICE_DELETE_RFID,
    SERVICE_PROGRAM_TIMER,
    SERVICE_REGISTER_RFID,
    SERVICE_SET_WIFI,
    SERVICE_TRIGGER_UPDATE,
    SERVICE_UPDATE_RFID_TAG,
)
from .v2c_cloud import (
    V2CAuthError,
    V2CClient,
    V2CError,
    V2CRateLimitError,
    V2CRequestError,
    async_gather_devices_state,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


@dataclass(slots=True)
class V2CEntryRuntimeData:
    """Runtime data stored per ConfigEntry."""

    client: V2CClient
    coordinator: DataUpdateCoordinator


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    """Set up the integration from YAML (not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up V2C Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api_key: str = entry.data[CONF_API_KEY]
    base_url: str = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)

    session = async_get_clientsession(hass)
    client = V2CClient(session, api_key, base_url=base_url)

    initial_pairings = entry.data.get("initial_pairings")
    if initial_pairings:
        client.preload_pairings(initial_pairings)

    # Validate credentials and initial connectivity by requesting pairings.
    try:
        pairings = await client.async_get_pairings()
    except V2CAuthError as err:
        raise ConfigEntryAuthFailed("Invalid V2C Cloud API key") from err
    except V2CRequestError as err:
        raise ConfigEntryNotReady(f"Unable to contact V2C Cloud: {err}") from err

    if not pairings:
        _LOGGER.warning("No V2C devices associated with this API key")

    async def _async_update_data() -> dict[str, object]:
        """Fetch the latest data from the API."""
        try:
            latest_pairings = await client.async_get_pairings()
            previous_devices = None
            if coordinator.data and isinstance(coordinator.data, dict):
                previous_devices = coordinator.data.get("devices")
            devices = await async_gather_devices_state(
                client,
                latest_pairings,
                previous_devices=previous_devices if isinstance(previous_devices, dict) else None,
            )
            global_statistics = await client.async_get_global_statistics()
        except V2CAuthError as err:
            raise ConfigEntryAuthFailed("Authentication lost with V2C Cloud") from err
        except V2CRateLimitError as err:
            _LOGGER.warning("V2C Cloud rate limit reached; keeping previous data")
            if coordinator.data is not None:
                return coordinator.data
            raise UpdateFailed("Rate limited by V2C Cloud API") from err
        except V2CError as err:
            raise UpdateFailed(f"Failed to update V2C data: {err}") from err

        return {
            "pairings": latest_pairings,
            "devices": devices,
            "global_statistics": global_statistics,
        }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="V2C Cloud data",
        update_method=_async_update_data,
        update_interval=DEFAULT_UPDATE_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    if initial_pairings:
        new_data = dict(entry.data)
        new_data.pop("initial_pairings", None)
        hass.config_entries.async_update_entry(entry, data=new_data)

    hass.data[DOMAIN][entry.entry_id] = V2CEntryRuntimeData(
        client=client,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    """Register Home Assistant services for device management."""

    if hass.services.has_service(DOMAIN, SERVICE_SET_WIFI):
        # Already registered
        return

    async def _async_get_entry_for_device(device_id: str) -> V2CEntryRuntimeData:
        for data in _iter_entries(hass):
            coordinator = data.coordinator
            devices: dict[str, object] | None = None
            if coordinator.data and isinstance(coordinator.data, dict):
                devices = coordinator.data.get("devices")
            if isinstance(devices, dict) and device_id in devices:
                return data

        raise HomeAssistantError(f"Unknown V2C device id {device_id!r}")

    async def _execute_and_refresh(
        entry_data: V2CEntryRuntimeData,
        call_coroutine,
    ) -> None:
        try:
            await call_coroutine
        except V2CAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed during service call") from err
        except V2CRequestError as err:
            raise HomeAssistantError(str(err)) from err

        await entry_data.coordinator.async_request_refresh()

    async def async_handle_set_wifi(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        ssid = call.data[ATTR_WIFI_SSID]
        password = call.data[ATTR_WIFI_PASSWORD]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_wifi(device_id, ssid, password),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WIFI,
        async_handle_set_wifi,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_WIFI_SSID): cv.string,
                vol.Required(ATTR_WIFI_PASSWORD): cv.string,
            }
        ),
    )

    async def async_handle_program_timer(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        timer_id = call.data[ATTR_TIMER_ID]
        days_of_week = call.data[ATTR_DAYS_OF_WEEK]
        time_start = call.data[ATTR_TIME_START]
        time_end = call.data[ATTR_TIME_END]

        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_program_timer(
                device_id,
                timer_id,
                days_of_week=days_of_week,
                time_start=time_start,
                time_end=time_end,
            ),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PROGRAM_TIMER,
        async_handle_program_timer,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_TIMER_ID): vol.Coerce(int),
                vol.Required(ATTR_DAYS_OF_WEEK): cv.string,
                vol.Required(ATTR_TIME_START): cv.matches_regex(r"^\\d{2}:\\d{2}$"),
                vol.Required(ATTR_TIME_END): cv.matches_regex(r"^\\d{2}:\\d{2}$"),
            }
        ),
    )

    async def async_handle_register_rfid(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        tag = call.data[ATTR_RFID_TAG]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_register_rfid_card(device_id, tag),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REGISTER_RFID,
        async_handle_register_rfid,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_RFID_TAG): cv.string,
            }
        ),
    )

    async def async_handle_update_rfid_tag(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        code = call.data[ATTR_RFID_CODE]
        tag = call.data[ATTR_RFID_TAG]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_update_rfid_tag(device_id, code, tag),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_RFID_TAG,
        async_handle_update_rfid_tag,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_RFID_CODE): cv.string,
                vol.Required(ATTR_RFID_TAG): cv.string,
            }
        ),
    )

    async def async_handle_delete_rfid(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        code = call.data[ATTR_RFID_CODE]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_delete_rfid_card(device_id, code),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_RFID,
        async_handle_delete_rfid,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_RFID_CODE): cv.string,
            }
        ),
    )

    async def async_handle_trigger_update(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_trigger_update(device_id),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_UPDATE,
        async_handle_trigger_update,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
            }
        ),
    )


def _iter_entries(hass: HomeAssistant) -> Iterable[V2CEntryRuntimeData]:
    """Yield runtime data for all configured entries."""
    domain_data = hass.data.get(DOMAIN, {})
    for value in domain_data.values():
        if isinstance(value, V2CEntryRuntimeData):
            yield value
