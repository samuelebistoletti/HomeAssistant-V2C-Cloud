"""Switch platform for controlling V2C Cloud charger toggles."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .entity import V2CEntity, _OptimisticHoldMixin, coerce_bool
from .local_api import (
    async_get_or_create_local_coordinator,
    async_request_local_refresh,
    async_write_keyword,
    get_local_data,
    get_local_value,
)

if TYPE_CHECKING:
    from . import V2CEntryRuntimeData
    from .v2c_cloud import V2CClient

_LOGGER = logging.getLogger(__name__)


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
                    name_key="timer",
                    unique_suffix="timer",
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "Timer",
                        1 if state else 0,
                    ),
                    reported_keys=("timer",),
                    local_keys=("Timer",),
                    icon_on="mdi:timer",
                    icon_off="mdi:timer-off",
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
                    setter=lambda state, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "LogoLED",
                        1 if state else 0,
                    ),
                    reported_keys=("logo_led", "logoled"),
                    local_keys=("LogoLED",),
                    icon_on="mdi:led-on",
                    icon_off="mdi:led-off",
                    refresh_after_call=False,
                    trigger_local_refresh=True,
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
                    refresh_after_call=False,
                    # Cloud takes ~90 s to reflect the change; hold optimistic state
                    # for that duration so the UI doesn't flicker back to the old value.
                    optimistic_hold_seconds=90.0,
                    delayed_refresh_seconds=90.0,
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
                    refresh_after_call=False,
                    optimistic_hold_seconds=90.0,
                    delayed_refresh_seconds=90.0,
                ),
            )
        )

    async_add_entities(entities)


class V2CBooleanSwitch(_OptimisticHoldMixin, V2CEntity, SwitchEntity):
    """Switch entity wrapping a boolean V2C command."""

    def __init__(  # noqa: PLR0913
        self,
        coordinator: DataUpdateCoordinator,
        client: V2CClient,
        runtime_data: V2CEntryRuntimeData,
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
        optimistic_hold_seconds: float = 20.0,
        delayed_refresh_seconds: float | None = None,
    ) -> None:
        """Initialise a boolean switch entity."""
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
        self._local_coordinator: DataUpdateCoordinator | None = None
        # Override the mixin class constant with the per-instance value.
        self._OPTIMISTIC_HOLD_SECONDS = optimistic_hold_seconds
        self._delayed_refresh_seconds = delayed_refresh_seconds
        self._cancel_delayed_refresh: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        """Return True if the entity can be controlled."""
        if self._local_coordinator is not None:
            return self._local_coordinator.last_update_success
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        """Return the current state of the switch."""
        local_value = self._get_local_bool()
        if local_value is not None:
            if self._is_within_hold() and local_value != self._optimistic_state:
                self._apply_icon(self._optimistic_state)
                return self._optimistic_state
            self._optimistic_state = local_value
            self._clear_command()
            self._apply_icon(local_value)
            return local_value

        if not self._local_keys:
            # Cloud-only entities fall back to reported payload.
            reported_value = self.get_reported_value(*self._reported_keys)
            bool_value = coerce_bool(reported_value)
            if bool_value is not None:
                if (
                    self._optimistic_state is not None
                    and self._is_within_hold()
                    and bool_value != self._optimistic_state
                ):
                    self._apply_icon(self._optimistic_state)
                    return self._optimistic_state
                self._optimistic_state = bool_value
                self._clear_command()
                self._apply_icon(bool_value)
                return bool_value

        if self._optimistic_state is not None:
            self._expire_hold_if_needed()
            self._apply_icon(self._optimistic_state)
            return self._optimistic_state

        self._apply_icon(state=False)
        return False

    async def async_added_to_hass(self) -> None:
        """Subscribe to the local coordinator once the entity is registered."""
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

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_call(state=True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_call(state=False)

    async def _async_call(self, state: bool) -> None:
        self._optimistic_state = state
        self._record_command()
        self.async_write_ha_state()
        await self._async_call_and_refresh(
            self._setter(state),
            refresh=self._refresh_after_call,
        )
        if self._trigger_local_refresh:
            await async_request_local_refresh(self._runtime_data, self._device_id)
        self._schedule_delayed_refresh()

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
            found, value = get_local_value(local_data, key)
            if found:
                return coerce_bool(value)
        return None

    def _schedule_delayed_refresh(self) -> None:
        """Schedule a delayed coordinator refresh for slow cloud updates."""
        if (
            self._delayed_refresh_seconds is None
            or self.hass is None
            or self._delayed_refresh_seconds <= 0
        ):
            return
        if self._cancel_delayed_refresh:
            self._cancel_delayed_refresh()
            self._cancel_delayed_refresh = None

        async def _refresh(_now: Any) -> None:
            self._cancel_delayed_refresh = None
            try:
                await self.coordinator.async_request_refresh()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Delayed coordinator refresh failed for %s", self._device_id)

        self._cancel_delayed_refresh = async_call_later(
            self.hass,
            self._delayed_refresh_seconds,
            _refresh,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending delayed refresh before removal."""
        if self._cancel_delayed_refresh:
            self._cancel_delayed_refresh()
            self._cancel_delayed_refresh = None
        await super().async_will_remove_from_hass()
