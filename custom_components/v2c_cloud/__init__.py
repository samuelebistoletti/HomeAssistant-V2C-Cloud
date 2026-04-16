"""Home Assistant integration setup for V2C Cloud."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

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
    ATTR_UPDATED_AT,
    ATTR_VOLTAGE,
    ATTR_WIFI_PASSWORD,
    ATTR_WIFI_SSID,
    CONF_API_KEY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_RATE_LIMIT_INTERVAL,
    RATE_LIMIT_COMMAND_RESERVE,
    RATE_LIMIT_LOW_THRESHOLD,
    EVENT_DEVICE_STATISTICS,
    EVENT_GLOBAL_STATISTICS,
    EVENT_POWER_PROFILES,
    EVENT_WIFI_SCAN,
    INSTALLATION_VOLTAGE_MAX,
    INSTALLATION_VOLTAGE_MIN,
    MIN_UPDATE_INTERVAL,
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
    TARGET_DAILY_BUDGET,
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


def _build_synthetic_fallback(device_id: str, ip: str) -> dict[str, object]:
    """Return minimal coordinator data for LAN-only startup when cloud is unavailable."""
    pairing: dict[str, object] = {"deviceId": device_id, "ip": ip}
    return {
        "pairings": [pairing],
        "devices": {
            device_id: {
                "device_id": device_id,
                "pairing": pairing,
                "connected": None,
                "current_state": None,
                "reported_raw": None,
                "reported": {},
                "rfid_cards": None,
                "version": None,
                "additional": {"static_ip": ip},
            }
        },
    }


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: C901
    """Set up V2C Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api_key: str = entry.data[CONF_API_KEY]

    session = async_get_clientsession(hass)
    client = V2CClient(session, api_key)

    initial_pairings = entry.data.get("initial_pairings")
    if initial_pairings:
        client.preload_pairings(initial_pairings)

    fallback_ip: str | None = entry.data.get("fallback_ip")
    fallback_device_id: str | None = entry.data.get("fallback_device_id")
    has_fallback = bool(fallback_ip and fallback_device_id)

    # Validate credentials and initial connectivity by requesting pairings.
    try:
        pairings = await client.async_get_pairings()
    except V2CAuthError as err:
        raise ConfigEntryAuthFailed("Invalid V2C Cloud API key") from err
    except V2CRequestError as err:
        if not has_fallback:
            raise ConfigEntryNotReady(f"Unable to contact V2C Cloud: {err}") from err
        if isinstance(err, V2CRateLimitError):
            _LOGGER.warning(
                "V2C Cloud rate-limited at startup; will retry via polling. "
                "Proceeding with local fallback.",
            )
        else:
            _LOGGER.warning(
                "V2C Cloud unreachable at startup; proceeding with local fallback: %s",
                type(err).__name__,
            )
        pairings = []

    if not pairings and not has_fallback:
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
        # 2 API calls per device per cycle (reported + currentstatecharge)
        seconds = math.ceil((device_count * 2 * 86400) / budget)
        seconds = max(seconds, min_seconds)
        return timedelta(seconds=seconds)

    async def _async_update_data() -> dict[str, object]:  # noqa: PLR0911
        """Fetch the latest data from the API."""

        def _restore_default_interval(reason: str) -> None:
            """Switch back to the default polling cadence after long outages."""
            if coordinator.update_interval == DEFAULT_UPDATE_INTERVAL:
                return
            _LOGGER.debug(
                "Restoring polling interval to %s after %s", DEFAULT_UPDATE_INTERVAL, reason
            )
            coordinator.update_interval = DEFAULT_UPDATE_INTERVAL

        def _back_off_on_rate_limit() -> None:
            """Double the polling interval after a 429, up to MAX_RATE_LIMIT_INTERVAL.

            Each retry on a 429 wastes one call from an already-exhausted budget.
            Backing off here gives the daily quota window time to reset instead of
            hammering the API at full speed until tomorrow.
            """
            current = coordinator.update_interval or DEFAULT_UPDATE_INTERVAL
            backed_off = min(current * 2, MAX_RATE_LIMIT_INTERVAL)
            if backed_off != current:
                _LOGGER.debug(
                    "Rate limited — backing off poll interval to %s", backed_off
                )
                coordinator.update_interval = backed_off

        # --- Step 1: fetch pairings ---
        latest_pairings: list[dict[str, object]] | None = None
        try:
            latest_pairings = await client.async_get_pairings()
        except V2CAuthError as err:
            _restore_default_interval("authentication failure")
            raise ConfigEntryAuthFailed("Authentication lost with V2C Cloud") from err
        except V2CRateLimitError as err:
            _back_off_on_rate_limit()
            _LOGGER.warning("V2C Cloud rate limit reached; keeping previous data")
            if coordinator.data is not None:
                return coordinator.data
            if has_fallback:
                _LOGGER.warning(
                    "V2C Cloud rate-limited at startup; using local fallback for %s",
                    fallback_device_id,
                )
                return _build_synthetic_fallback(fallback_device_id, fallback_ip)
            raise UpdateFailed("Rate limited by V2C Cloud API") from err
        except V2CError as err:
            if has_fallback:
                # Pairings inaccessible (e.g. 403) but other cloud endpoints may still
                # work. Build a synthetic pairing from the fallback device ID so that
                # async_gather_devices_state can still query /device/reported etc.
                _LOGGER.warning(
                    "Pairings unavailable (%s); falling back to device %s",
                    err,
                    fallback_device_id,
                )
                latest_pairings = [{"deviceId": fallback_device_id, "ip": fallback_ip}]
            else:
                raise UpdateFailed(f"Failed to update V2C data: {err}") from err

        # --- Step 2: fetch per-device state ---
        previous_devices = None
        if coordinator.data and isinstance(coordinator.data, dict):
            previous_devices = coordinator.data.get("devices")
        try:
            devices = await async_gather_devices_state(
                client,
                latest_pairings,
                previous_devices=previous_devices if isinstance(previous_devices, dict) else None,
            )
        except V2CAuthError as err:
            _restore_default_interval("authentication failure")
            raise ConfigEntryAuthFailed("Authentication lost with V2C Cloud") from err
        except V2CRateLimitError as err:
            _back_off_on_rate_limit()
            _LOGGER.warning("V2C Cloud rate limit reached; keeping previous data")
            if coordinator.data is not None:
                return coordinator.data
            if has_fallback:
                _LOGGER.warning(
                    "V2C Cloud rate-limited at startup; using local fallback for %s",
                    fallback_device_id,
                )
                return _build_synthetic_fallback(fallback_device_id, fallback_ip)
            raise UpdateFailed("Rate limited by V2C Cloud API") from err
        except V2CError as err:
            _restore_default_interval("communication failure")
            if coordinator.data is not None:
                _LOGGER.warning("V2C Cloud device fetch failed; keeping previous data: %s", err)
                return coordinator.data
            if has_fallback:
                _LOGGER.warning(
                    "V2C Cloud unavailable at first refresh; using local fallback for %s: %s",
                    fallback_device_id,
                    err,
                )
                return _build_synthetic_fallback(fallback_device_id, fallback_ip)
            raise UpdateFailed(f"Failed to update V2C data: {err}") from err

        device_count = len(devices)
        new_interval = _calculate_update_interval(device_count)

        # Proactive pacing: if the API reports that remaining calls are running low,
        # stretch the interval to avoid exhausting the daily budget before reset.
        # We do not know when the window resets, so we assume worst-case (24 h away)
        # and reserve RATE_LIMIT_COMMAND_RESERVE calls for user-initiated commands.
        rl_info = client.last_rate_limit
        if rl_info:
            remaining = rl_info.get("remaining")
            if remaining is not None and remaining < RATE_LIMIT_LOW_THRESHOLD:
                available = max(remaining - RATE_LIMIT_COMMAND_RESERVE, 1)
                pacing_interval = timedelta(seconds=math.ceil(86400 / available))
                if pacing_interval > new_interval:
                    _LOGGER.warning(
                        "RateLimit-Remaining is %s — pacing poll interval to %s",
                        remaining,
                        pacing_interval,
                    )
                    new_interval = pacing_interval

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
        runtime_data: V2CEntryRuntimeData | None = hass.data[DOMAIN].get(entry.entry_id)
        if runtime_data is not None:
            # Cancel the scheduled polling task for every local coordinator so that
            # orphaned asyncio handles do not keep the objects alive after removal.
            for coord in runtime_data.local_coordinators.values():
                if hasattr(coord, "async_shutdown"):
                    coord.async_shutdown()
                elif hasattr(coord, "_unsub_refresh") and coord._unsub_refresh:  # noqa: SLF001
                    coord._unsub_refresh()  # noqa: SLF001
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not any(isinstance(v, V2CEntryRuntimeData) for v in hass.data[DOMAIN].values()):
            _async_unregister_services(hass)
    return unload_ok


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all V2C services when the last config entry is removed."""
    for service in (
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
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _async_register_services(hass: HomeAssistant) -> None:  # noqa: C901
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
        entry_data: V2CEntryRuntimeData | None,
        call_coroutine: Any,
        *,
        refresh: bool = True,
    ) -> Any:
        try:
            result = await call_coroutine
        except V2CAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed during service call") from err
        except V2CRequestError as err:
            raise HomeAssistantError(str(err)) from err
        except V2CLocalApiError as err:
            raise HomeAssistantError(str(err)) from err

        if refresh and entry_data is not None:
            await entry_data.coordinator.async_request_refresh()
        return result

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
                vol.Required(ATTR_TIME_START): cv.matches_regex(r"^([01]\d|2[0-3]):[0-5]\d$"),
                vol.Required(ATTR_TIME_END): cv.matches_regex(r"^([01]\d|2[0-3]):[0-5]\d$"),
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
                vol.Required(ATTR_RFID_TAG): vol.All(cv.string, vol.Length(min=1, max=64)),
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
                vol.Required(ATTR_RFID_CODE): vol.All(cv.string, vol.Length(min=1, max=64)),
                vol.Required(ATTR_RFID_TAG): vol.All(cv.string, vol.Length(min=1, max=64)),
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
                vol.Required(ATTR_RFID_CODE): vol.All(cv.string, vol.Length(min=1, max=64)),
                vol.Required(ATTR_RFID_TAG): vol.All(cv.string, vol.Length(min=1, max=64)),
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
                vol.Required(ATTR_RFID_CODE): vol.All(cv.string, vol.Length(min=1, max=64)),
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
                vol.Required(ATTR_OCPP_URL): cv.matches_regex(r"^wss?://[a-zA-Z0-9][a-zA-Z0-9\-\.]{1,252}[a-zA-Z0-9](:[0-9]{1,5})?(/[^\s]*)?$"),
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
                vol.Required(ATTR_IP_ADDRESS): cv.matches_regex(
                    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
                ),
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
                round(float(voltage)),
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
        result = await _execute_and_refresh(
            None, entry_data.client.async_get_wifi_list(device_id), refresh=False
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
        result = await _execute_and_refresh(
            None,
            entry_data.client.async_get_personal_power_profile(device_id, timestamp),
            refresh=False,
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
        result = await _execute_and_refresh(
            None,
            entry_data.client.async_list_personal_power_profiles(device_id),
            refresh=False,
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
        result = await _execute_and_refresh(
            None,
            entry_data.client.async_get_device_statistics(
                device_id,
                start=date_start,
                end=date_end,
            ),
            refresh=False,
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
                vol.Optional(ATTR_DATE_START): cv.matches_regex(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
                vol.Optional(ATTR_DATE_END): cv.matches_regex(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
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
        result = await _execute_and_refresh(
            None,
            first_entry.client.async_get_global_statistics(
                start=date_start,
                end=date_end,
            ),
            refresh=False,
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
                vol.Optional(ATTR_DATE_START): cv.matches_regex(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
                vol.Optional(ATTR_DATE_END): cv.matches_regex(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
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
