"""Home Assistant integration setup for V2C Cloud."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from datetime import timedelta
from dataclasses import dataclass, field

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
    ATTR_DATE_END,
    ATTR_DATE_START,
    ATTR_DEVICE_ID,
    ATTR_ENABLED,
    ATTR_IP_ADDRESS,
    ATTR_KWH,
    ATTR_MINUTES,
    ATTR_OCPP_ID,
    ATTR_OCPP_URL,
    ATTR_PROFILE_NAME,
    ATTR_PROFILE_PAYLOAD,
    ATTR_PROFILE_TIMESTAMP,
    ATTR_RFID_CODE,
    ATTR_RFID_TAG,
    ATTR_TIME_END,
    ATTR_TIME_START,
    ATTR_TIMER_ACTIVE,
    ATTR_TIMER_ID,
    ATTR_VOLTAGE,
    ATTR_UPDATED_AT,
    ATTR_WIFI_PASSWORD,
    ATTR_WIFI_SSID,
    CONF_API_KEY,
    CONF_BASE_URL,
    DEFAULT_BASE_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
    TARGET_DAILY_BUDGET,
    EVENT_DEVICE_STATISTICS,
    EVENT_GLOBAL_STATISTICS,
    EVENT_POWER_PROFILES,
    EVENT_WIFI_SCAN,
    INSTALLATION_VOLTAGE_MAX,
    INSTALLATION_VOLTAGE_MIN,
    SERVICE_ADD_RFID_CARD,
    SERVICE_CREATE_POWER_PROFILE,
    SERVICE_DELETE_POWER_PROFILE,
    SERVICE_DELETE_RFID,
    SERVICE_GET_DEVICE_STATISTICS,
    SERVICE_GET_GLOBAL_STATISTICS,
    SERVICE_GET_POWER_PROFILE,
    SERVICE_LIST_POWER_PROFILES,
    SERVICE_PROGRAM_TIMER,
    SERVICE_REGISTER_RFID,
    SERVICE_SCAN_WIFI,
    SERVICE_SET_INSTALLATION_VOLTAGE,
    SERVICE_SET_INVERTER_IP,
    SERVICE_SET_OCPP_ADDRESS,
    SERVICE_SET_OCPP_ENABLED,
    SERVICE_SET_OCPP_ID,
    SERVICE_SET_STOP_CHARGE_KWH,
    SERVICE_SET_STOP_CHARGE_MINUTES,
    SERVICE_SET_WIFI,
    SERVICE_START_CHARGE_KWH,
    SERVICE_START_CHARGE_MINUTES,
    SERVICE_TRIGGER_UPDATE,
    SERVICE_UPDATE_POWER_PROFILE,
    SERVICE_UPDATE_RFID_TAG,
)
from .local_api import V2CLocalApiError, async_write_keyword
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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class V2CEntryRuntimeData:
    """Runtime data stored per ConfigEntry."""

    client: V2CClient
    coordinator: DataUpdateCoordinator
    local_coordinators: dict[str, DataUpdateCoordinator] = field(default_factory=dict)


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

    def _calculate_update_interval(device_count: int) -> timedelta:
        """Compute a polling interval that honours the daily rate limit."""
        if device_count <= 0:
            return DEFAULT_UPDATE_INTERVAL
        min_seconds = max(
            DEFAULT_UPDATE_INTERVAL.total_seconds(),
            MIN_UPDATE_INTERVAL.total_seconds(),
        )
        budget = max(1, TARGET_DAILY_BUDGET)
        seconds = math.ceil((device_count * 86400) / budget)
        if seconds < min_seconds:
            seconds = min_seconds
        return timedelta(seconds=seconds)

    async def _async_update_data() -> dict[str, object]:
        """Fetch the latest data from the API."""

        def _restore_default_interval(reason: str) -> None:
            """Switch back to the default polling cadence after long outages."""
            if coordinator.update_interval == DEFAULT_UPDATE_INTERVAL:
                return
            _LOGGER.debug(
                "Restoring polling interval to %s after %s", DEFAULT_UPDATE_INTERVAL, reason
            )
            coordinator.update_interval = DEFAULT_UPDATE_INTERVAL

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
        except V2CAuthError as err:
            _restore_default_interval("authentication failure")
            raise ConfigEntryAuthFailed("Authentication lost with V2C Cloud") from err
        except V2CRateLimitError as err:
            _LOGGER.warning("V2C Cloud rate limit reached; keeping previous data")
            if coordinator.data is not None:
                return coordinator.data
            raise UpdateFailed("Rate limited by V2C Cloud API") from err
        except V2CError as err:
            _restore_default_interval("communication failure")
            raise UpdateFailed(f"Failed to update V2C data: {err}") from err

        device_count = len(devices)
        new_interval = _calculate_update_interval(device_count)
        if coordinator.update_interval != new_interval:
            _LOGGER.debug(
                "Adjusting polling interval to %s based on %s device(s) and %s daily budget",
                new_interval,
                device_count,
                TARGET_DAILY_BUDGET,
            )
            coordinator.update_interval = new_interval

        result: dict[str, object] = {
            "pairings": latest_pairings,
            "devices": devices,
        }
        if client.last_rate_limit is not None:
            result["rate_limit"] = client.last_rate_limit

        return result

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
        *,
        refresh: bool = True,
    ) -> None:
        try:
            await call_coroutine
        except V2CAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed during service call") from err
        except V2CRequestError as err:
            raise HomeAssistantError(str(err)) from err

        if refresh:
            await entry_data.coordinator.async_request_refresh()

    async def _call_with_error_handling(call_coroutine):
        try:
            return await call_coroutine
        except V2CAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed during service call") from err
        except V2CRequestError as err:
            raise HomeAssistantError(str(err)) from err

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
        time_start = call.data[ATTR_TIME_START]
        time_end = call.data[ATTR_TIME_END]
        active = call.data.get(ATTR_TIMER_ACTIVE, True)

        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_program_timer(
                device_id,
                timer_id,
                time_start=time_start,
                time_end=time_end,
                active=bool(active),
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
                vol.Required(ATTR_TIME_START): cv.matches_regex(r"^\\d{2}:\\d{2}$"),
                vol.Required(ATTR_TIME_END): cv.matches_regex(r"^\\d{2}:\\d{2}$"),
                vol.Optional(ATTR_TIMER_ACTIVE, default=True): cv.boolean,
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

    async def async_handle_add_rfid_card(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        code = call.data[ATTR_RFID_CODE]
        tag = call.data[ATTR_RFID_TAG]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_add_rfid_card(device_id, code, tag),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_RFID_CARD,
        async_handle_add_rfid_card,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_RFID_CODE): cv.string,
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

    async def async_handle_set_stop_energy(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        kwh = call.data[ATTR_KWH]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_charge_stop_energy(device_id, float(kwh)),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STOP_CHARGE_KWH,
        async_handle_set_stop_energy,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_KWH): vol.Coerce(float),
            }
        ),
    )

    async def async_handle_set_stop_minutes(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        minutes = call.data[ATTR_MINUTES]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_charge_stop_minutes(device_id, int(minutes)),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STOP_CHARGE_MINUTES,
        async_handle_set_stop_minutes,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_MINUTES): vol.Coerce(int),
            }
        ),
    )

    async def async_handle_start_charge_kwh(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        kwh = call.data[ATTR_KWH]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_start_charge_kwh(device_id, float(kwh)),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_CHARGE_KWH,
        async_handle_start_charge_kwh,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_KWH): vol.Coerce(float),
            }
        ),
    )

    async def async_handle_start_charge_minutes(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        minutes = call.data[ATTR_MINUTES]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_start_charge_minutes(device_id, int(minutes)),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_CHARGE_MINUTES,
        async_handle_start_charge_minutes,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_MINUTES): vol.Coerce(int),
            }
        ),
    )

    async def async_handle_set_ocpp_enabled(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        enabled = call.data[ATTR_ENABLED]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_ocpp_enabled(device_id, bool(enabled)),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OCPP_ENABLED,
        async_handle_set_ocpp_enabled,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_ENABLED): cv.boolean,
            }
        ),
    )

    async def async_handle_set_ocpp_id(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        ocpp_id = call.data[ATTR_OCPP_ID]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_ocpp_id(device_id, ocpp_id),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OCPP_ID,
        async_handle_set_ocpp_id,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_OCPP_ID): cv.string,
            }
        ),
    )

    async def async_handle_set_ocpp_address(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        url = call.data[ATTR_OCPP_URL]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_ocpp_address(device_id, url),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OCPP_ADDRESS,
        async_handle_set_ocpp_address,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_OCPP_URL): cv.string,
            }
        ),
    )

    async def async_handle_set_inverter_ip(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        address = call.data[ATTR_IP_ADDRESS]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_set_inverter_ip(device_id, address),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INVERTER_IP,
        async_handle_set_inverter_ip,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_IP_ADDRESS): cv.string,
            }
        ),
    )

    async def async_handle_set_installation_voltage(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        voltage = call.data[ATTR_VOLTAGE]
        entry_data = await _async_get_entry_for_device(device_id)
        try:
            await async_write_keyword(
                hass,
                entry_data,
                device_id,
                "VoltageInstallation",
                int(round(float(voltage))),
            )
        except V2CLocalApiError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INSTALLATION_VOLTAGE,
        async_handle_set_installation_voltage,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_VOLTAGE): vol.All(
                    vol.Coerce(float),
                    vol.Range(
                        min=INSTALLATION_VOLTAGE_MIN,
                        max=INSTALLATION_VOLTAGE_MAX,
                    ),
                ),
            }
        ),
    )

    async def async_handle_scan_wifi(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        entry_data = await _async_get_entry_for_device(device_id)
        result = await _call_with_error_handling(
            entry_data.client.async_get_wifi_list(device_id)
        )
        hass.bus.async_fire(
            EVENT_WIFI_SCAN,
            {
                ATTR_DEVICE_ID: device_id,
                "networks": result,
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_WIFI,
        async_handle_scan_wifi,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
            }
        ),
    )

    async def async_handle_create_power_profile(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        name = call.data[ATTR_PROFILE_NAME]
        update_at = call.data[ATTR_UPDATED_AT]
        profile = call.data[ATTR_PROFILE_PAYLOAD]
        if not isinstance(profile, dict):
            raise HomeAssistantError("Profile payload must be a JSON object")
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_save_personal_power_profile(
                device_id, name, update_at, profile
            ),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_POWER_PROFILE,
        async_handle_create_power_profile,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_PROFILE_NAME): cv.string,
                vol.Required(ATTR_UPDATED_AT): cv.string,
                vol.Required(ATTR_PROFILE_PAYLOAD): dict,
            }
        ),
    )

    async def async_handle_update_power_profile(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        name = call.data[ATTR_PROFILE_NAME]
        update_at = call.data[ATTR_UPDATED_AT]
        profile = call.data[ATTR_PROFILE_PAYLOAD]
        if not isinstance(profile, dict):
            raise HomeAssistantError("Profile payload must be a JSON object")
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_update_personal_power_profile(
                device_id, name, update_at, profile
            ),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_POWER_PROFILE,
        async_handle_update_power_profile,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_PROFILE_NAME): cv.string,
                vol.Required(ATTR_UPDATED_AT): cv.string,
                vol.Required(ATTR_PROFILE_PAYLOAD): dict,
            }
        ),
    )

    async def async_handle_get_power_profile(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        timestamp = call.data[ATTR_PROFILE_TIMESTAMP]
        entry_data = await _async_get_entry_for_device(device_id)
        result = await _call_with_error_handling(
            entry_data.client.async_get_personal_power_profile(device_id, timestamp)
        )
        hass.bus.async_fire(
            EVENT_POWER_PROFILES,
            {
                ATTR_DEVICE_ID: device_id,
                "profile": result,
                ATTR_PROFILE_TIMESTAMP: timestamp,
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_POWER_PROFILE,
        async_handle_get_power_profile,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_PROFILE_TIMESTAMP): cv.string,
            }
        ),
    )

    async def async_handle_delete_power_profile(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        name = call.data[ATTR_PROFILE_NAME]
        update_at = call.data[ATTR_UPDATED_AT]
        entry_data = await _async_get_entry_for_device(device_id)
        await _execute_and_refresh(
            entry_data,
            entry_data.client.async_delete_personal_power_profile(
                device_id, name, update_at
            ),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_POWER_PROFILE,
        async_handle_delete_power_profile,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Required(ATTR_PROFILE_NAME): cv.string,
                vol.Required(ATTR_UPDATED_AT): cv.string,
            }
        ),
    )

    async def async_handle_list_power_profiles(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        entry_data = await _async_get_entry_for_device(device_id)
        result = await _call_with_error_handling(
            entry_data.client.async_list_personal_power_profiles(device_id)
        )
        hass.bus.async_fire(
            EVENT_POWER_PROFILES,
            {
                ATTR_DEVICE_ID: device_id,
                "profiles": result,
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_POWER_PROFILES,
        async_handle_list_power_profiles,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
            }
        ),
    )

    async def async_handle_get_device_statistics(call: ServiceCall) -> None:
        device_id = call.data[ATTR_DEVICE_ID]
        date_start = call.data.get(ATTR_DATE_START)
        date_end = call.data.get(ATTR_DATE_END)
        entry_data = await _async_get_entry_for_device(device_id)
        result = await _call_with_error_handling(
            entry_data.client.async_get_device_statistics(
                device_id,
                start=date_start,
                end=date_end,
            )
        )
        hass.bus.async_fire(
            EVENT_DEVICE_STATISTICS,
            {
                ATTR_DEVICE_ID: device_id,
                "statistics": result,
                ATTR_DATE_START: date_start,
                ATTR_DATE_END: date_end,
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEVICE_STATISTICS,
        async_handle_get_device_statistics,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_DATE_START): cv.string,
                vol.Optional(ATTR_DATE_END): cv.string,
            }
        ),
    )

    async def async_handle_get_global_statistics(call: ServiceCall) -> None:
        date_start = call.data.get(ATTR_DATE_START)
        date_end = call.data.get(ATTR_DATE_END)
        # Use the first available entry to perform the call.
        first_entry = next(_iter_entries(hass), None)
        if first_entry is None:
            raise HomeAssistantError("V2C Cloud integration is not configured")
        result = await _call_with_error_handling(
            first_entry.client.async_get_global_statistics(
                start=date_start,
                end=date_end,
            )
        )
        hass.bus.async_fire(
            EVENT_GLOBAL_STATISTICS,
            {
                "statistics": result,
                ATTR_DATE_START: date_start,
                ATTR_DATE_END: date_end,
            },
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_GLOBAL_STATISTICS,
        async_handle_get_global_statistics,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_DATE_START): cv.string,
                vol.Optional(ATTR_DATE_END): cv.string,
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
