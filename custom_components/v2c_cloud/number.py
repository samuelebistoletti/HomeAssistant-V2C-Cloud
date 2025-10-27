"""Number entities for configurable numeric values on the V2C charger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import V2CEntity

CURRENT_MIN = 6.0
CURRENT_MAX = 80.0
CURRENT_STEP = 1.0
POWER_MIN = 1.0
POWER_MAX = 50.0
POWER_STEP = 0.1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C number entities."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}
    entities: list[NumberEntity] = []

    for device_id in devices:
        entities.extend(
            (
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="current_intensity",
                    unique_suffix="intensity",
                    reported_keys=("intensity", "currentintensity", "current_intensity"),
                    setter=lambda value, _device_id=device_id: client.async_set_intensity(
                        _device_id, int(value)
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="min_intensity",
                    unique_suffix="min_intensity",
                    reported_keys=("mincarint", "min_intensity", "mincarintensity"),
                    setter=lambda value, _device_id=device_id: client.async_set_min_car_intensity(
                        _device_id, int(value)
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="max_intensity",
                    unique_suffix="max_intensity",
                    reported_keys=("maxcarint", "max_intensity", "maxcarintensity"),
                    setter=lambda value, _device_id=device_id: client.async_set_max_car_intensity(
                        _device_id, int(value)
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="max_power",
                    unique_suffix="max_power",
                    reported_keys=("maxpower", "max_power"),
                    setter=lambda value, _device_id=device_id: client.async_set_max_power(
                        _device_id, float(value)
                    ),
                    native_unit=UnitOfPower.KILO_WATT,
                    minimum=POWER_MIN,
                    maximum=POWER_MAX,
                    step=POWER_STEP,
                ),
            )
        )

    async_add_entities(entities)


class V2CNumberEntity(V2CEntity, NumberEntity):
    """Generic number entity for V2C Chargers."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator,
        client,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        reported_keys: tuple[str, ...],
        setter: Callable[[float], Awaitable[Any]],
        native_unit: str,
        minimum: float,
        maximum: float,
        step: float,
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._reported_keys = reported_keys
        self._setter = setter
        self._attr_translation_key = name_key
        self._attr_unique_id = f"{device_id}_{unique_suffix}_number"
        self._attr_native_unit_of_measurement = native_unit
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._optimistic_value: float | None = None

    @property
    def native_value(self) -> float | None:
        value = self.get_reported_value(*self._reported_keys)
        if value is None:
            value = self.device_state.get(self._reported_keys[0])

        if value is None:
            return self._optimistic_value

        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return self._optimistic_value

        self._optimistic_value = numeric
        return numeric

    async def async_set_native_value(self, value: float) -> None:
        self._optimistic_value = value
        await self._async_call_and_refresh(self._setter(value))
