"""Switch platform for controlling V2C Cloud charger toggles."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Sequence
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import V2CEntity
from .local_api import (
    async_get_or_create_local_coordinator,
    async_request_local_refresh,
    async_write_keyword,
    get_local_data,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C switches for each configured charger."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}
    entities: list[SwitchEntity] = []

    for device_id in devices:
        entities.extend(
            (
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="dynamic_mode",
                    unique_suffix="dynamic",
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "Dynamic",
                        1 if state else 0,
                    ),
                    reported_keys=("dynamic",),
                    local_keys=("Dynamic",),
                    icon_on="mdi:flash-auto",
                    refresh_after_call=False,
                    trigger_local_refresh=True,
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="pause_dynamic",
                    unique_suffix="pause_dynamic",
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "PauseDynamic",
                        1 if state else 0,
                    ),
                    reported_keys=("pause_dynamic", "pausedynamic"),
                    local_keys=("PauseDynamic",),
                    icon_on="mdi:pause-octagon",
                    icon_off="mdi:play-circle",
                    refresh_after_call=False,
                    trigger_local_refresh=True,
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="locked",
                    unique_suffix="locked",
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "Locked",
                        1 if state else 0,
                    ),
                    reported_keys=("locked",),
                    local_keys=("Locked",),
                    icon_on="mdi:lock",
                    icon_off="mdi:lock-open",
                    refresh_after_call=False,
                    trigger_local_refresh=True,
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="charging_pause",
                    unique_suffix="charging_pause",
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "Paused",
                        1 if state else 0,
                    ),
                    reported_keys=("paused",),
                    local_keys=("Paused",),
                    icon_on="mdi:pause-circle",
                    icon_off="mdi:play-circle",
                    refresh_after_call=False,
                    trigger_local_refresh=True,
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="logo_led",
                    unique_suffix="logo_led",
                    setter=lambda state, _device_id=device_id: client.async_set_logo_led(
                        _device_id, state
                    ),
                    reported_keys=("logo_led", "logoled"),
                    icon_on="mdi:led-on",
                    icon_off="mdi:led-off",
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="rfid_reader",
                    unique_suffix="rfid_reader",
                    setter=lambda state, _device_id=device_id: client.async_set_rfid_mode(
                        _device_id, state
                    ),
                    reported_keys=("set_rfid", "rfid_enabled", "rfid"),
                    icon_on="mdi:card-account-details",
                    icon_off="mdi:card-off",
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="ocpp_enabled",
                    unique_suffix="ocpp_enabled",
                    setter=lambda state, _device_id=device_id: client.async_set_ocpp_enabled(
                        _device_id, state
                    ),
                    reported_keys=(
                        "ocpp",
                        "ocpp_enabled",
                        "ocppactive",
                        "ocppenabled",
                    ),
                    icon_on="mdi:protocol",
                    icon_off="mdi:protocol",
                ),
            )
        )

    async_add_entities(entities)


def _to_bool(value: Any) -> bool | None:
    """Convert V2C API values to Python booleans."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "on", "yes", "enabled"}:
            return True
        if lowered in {"0", "false", "off", "no", "disabled"}:
            return False
    return None


class V2CBooleanSwitch(V2CEntity, SwitchEntity):
    """Switch entity wrapping a boolean V2C command."""

    _OPTIMISTIC_HOLD_SECONDS = 20.0

    def __init__(
        self,
        coordinator,
        client,
        runtime_data,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        setter: Callable[[bool], Awaitable[Any]],
        reported_keys: tuple[str, ...],
        local_keys: Sequence[str] | None = None,
        icon_on: str | None = None,
        icon_off: str | None = None,
        refresh_after_call: bool = True,
        trigger_local_refresh: bool = False,
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._setter = setter
        self._reported_keys = reported_keys
        self._runtime_data = runtime_data
        self._local_keys = tuple(local_keys) if local_keys else ()
        self._refresh_after_call = refresh_after_call
        self._trigger_local_refresh = trigger_local_refresh
        self._attr_translation_key = name_key
        self._attr_unique_id = f"v2c_{device_id}_{unique_suffix}"
        self._attr_icon = icon_on
        self._icon_on = icon_on
        self._icon_off = icon_off
        self._optimistic_state: bool | None = None
        self._last_command_ts: float | None = None
        self._local_coordinator = None

    @property
    def is_on(self) -> bool:
        """Return the current state of the switch."""
        now = time.monotonic()
        recent_command = (
            self._optimistic_state is not None
            and self._last_command_ts is not None
            and now - self._last_command_ts < self._OPTIMISTIC_HOLD_SECONDS
        )
        local_value = self._get_local_bool()
        if local_value is not None:
            if recent_command and local_value != self._optimistic_state:
                self._apply_icon(self._optimistic_state)
                return self._optimistic_state
            self._optimistic_state = local_value
            self._last_command_ts = None
            self._apply_icon(local_value)
            return local_value
        reported_value = self.get_reported_value(*self._reported_keys)
        bool_value = _to_bool(reported_value)
        if bool_value is not None:
            if (
                self._optimistic_state is not None
                and self._last_command_ts is not None
                and now - self._last_command_ts < self._OPTIMISTIC_HOLD_SECONDS
                and bool_value != self._optimistic_state
            ):
                self._apply_icon(self._optimistic_state)
                return self._optimistic_state

            self._optimistic_state = bool_value
            self._last_command_ts = None
            self._apply_icon(bool_value)
            return bool_value

        if self._optimistic_state is not None:
            if (
                self._last_command_ts is not None
                and now - self._last_command_ts >= self._OPTIMISTIC_HOLD_SECONDS
            ):
                self._last_command_ts = None
            self._apply_icon(self._optimistic_state)
            return self._optimistic_state

        self._apply_icon(False)

        return False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._local_keys:
            return
        coordinator = await async_get_or_create_local_coordinator(
            self.hass,
            self._runtime_data,
            self._device_id,
        )
        self._local_coordinator = coordinator
        remove_listener = coordinator.async_add_listener(self.async_write_ha_state)
        self.async_on_remove(remove_listener)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_call(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_call(False)

    async def _async_call(self, state: bool) -> None:
        self._optimistic_state = state
        self._last_command_ts = time.monotonic()
        self.async_write_ha_state()
        await self._async_call_and_refresh(
            self._setter(state),
            refresh=self._refresh_after_call,
        )
        if self._trigger_local_refresh:
            await async_request_local_refresh(self._runtime_data, self._device_id)

    def _apply_icon(self, state: bool | None) -> None:
        if self._icon_on and self._icon_off and state is not None:
            self._attr_icon = self._icon_on if state else self._icon_off

    def _get_local_data(self) -> dict[str, Any] | None:
        return get_local_data(self._runtime_data, self._device_id)

    def _get_local_bool(self) -> bool | None:
        if not self._local_keys:
            return None
        local_data = self._get_local_data()
        if not isinstance(local_data, dict):
            return None
        for key in self._local_keys:
            if key in local_data:
                return _to_bool(local_data.get(key))
        return None
