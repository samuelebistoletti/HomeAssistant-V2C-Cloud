"""Switch platform for controlling V2C Cloud charger toggles."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import V2CEntity


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
                    device_id,
                    name_key="dynamic_mode",
                    unique_suffix="dynamic",
                    setter=lambda state, _device_id=device_id: client.async_set_dynamic(
                        _device_id, state
                    ),
                    reported_keys=("dynamic",),
                    icon_on="mdi:flash-auto",
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
                    device_id,
                    name_key="locked",
                    unique_suffix="locked",
                    setter=lambda state, _device_id=device_id: client.async_lock(
                        _device_id, state
                    ),
                    reported_keys=("locked",),
                    icon_on="mdi:lock",
                    icon_off="mdi:lock-open",
                ),
                V2CBooleanSwitch(
                    coordinator,
                    client,
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

    def __init__(
        self,
        coordinator,
        client,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        setter: Callable[[bool], Awaitable[Any]],
        reported_keys: tuple[str, ...],
        icon_on: str | None = None,
        icon_off: str | None = None,
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._setter = setter
        self._reported_keys = reported_keys
        self._attr_translation_key = name_key
        self._attr_unique_id = f"{device_id}_{unique_suffix}"
        self._attr_icon = icon_on
        self._icon_on = icon_on
        self._icon_off = icon_off
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool:
        """Return the current state of the switch."""
        reported_value = self.get_reported_value(*self._reported_keys)
        bool_value = _to_bool(reported_value)
        if bool_value is not None:
            self._optimistic_state = bool_value
            if self._icon_on and self._icon_off:
                self._attr_icon = self._icon_on if bool_value else self._icon_off
            return bool_value

        if self._optimistic_state is not None:
            if self._icon_on and self._icon_off:
                self._attr_icon = (
                    self._icon_on if self._optimistic_state else self._icon_off
                )
            return self._optimistic_state

        return False

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_call(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_call(False)

    async def _async_call(self, state: bool) -> None:
        self._optimistic_state = state
        self.async_write_ha_state()
        await self._async_call_and_refresh(self._setter(state))
