"""Number entities for configurable numeric values on the V2C charger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_POWER_MAX_KW,
    MAX_POWER_MIN_KW,
)
from .entity import V2CEntity
from .v2c_cloud import V2CError

CURRENT_MIN = 6.0
CURRENT_MAX = 80.0
CURRENT_STEP = 1.0
POWER_MIN = MAX_POWER_MIN_KW
POWER_MAX = MAX_POWER_MAX_KW
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
                    reported_keys=("intensity", "currentintensity", "current_int", "current_intensity", "car_intensity"),
                    setter=lambda api_value, _device_id=device_id: client.async_set_intensity(
                        _device_id, api_value
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="min_intensity",
                    unique_suffix="min_intensity",
                    reported_keys=("mincarint", "min_intensity", "mincarintensity", "min_car_int", "mincar_int"),
                    setter=lambda api_value, _device_id=device_id: client.async_set_min_car_intensity(
                        _device_id, api_value
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="max_intensity",
                    unique_suffix="max_intensity",
                    reported_keys=("maxcarint", "max_intensity", "maxcarintensity", "max_car_int", "maxcar_int"),
                    setter=lambda api_value, _device_id=device_id: client.async_set_max_car_intensity(
                        _device_id, api_value
                    ),
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    device_id,
                    name_key="max_power",
                    unique_suffix="max_power",
                    reported_keys=("maxpower", "max_power"),
                    setter=lambda api_value, _device_id=device_id: client.async_set_max_power(
                        _device_id, api_value
                    ),
                    native_unit=UnitOfPower.KILO_WATT,
                    minimum=POWER_MIN,
                    maximum=POWER_MAX,
                    step=POWER_STEP,
                    value_to_api=lambda value: int(round(value * 1000)),
                    source_to_native=lambda raw: (raw / 1000)
                    if raw and raw > MAX_POWER_MAX_KW + 1
                    else raw,
                    dynamic_max_keys=("maxpowerinstallation", "max_power_installation"),
                    dynamic_max_transform=lambda raw: (raw / 1000)
                    if raw and raw > MAX_POWER_MAX_KW + 1
                    else raw,
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
        value_to_api: Callable[[float], float] | None = None,
        source_to_native: Callable[[float], float] | None = None,
        dynamic_max_keys: tuple[str, ...] | None = None,
        dynamic_max_transform: Callable[[float], float] | None = None,
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
        self._value_to_api = value_to_api or (lambda value: value)
        self._source_to_native = source_to_native or (lambda value: value)
        self._dynamic_max_keys = dynamic_max_keys
        self._dynamic_max_transform = dynamic_max_transform
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

        native_numeric = self._source_to_native(float(numeric))
        self._optimistic_value = native_numeric
        return native_numeric

    @property
    def native_max_value(self) -> float | None:
        if self._dynamic_max_keys:
            dynamic = self.get_reported_value(*self._dynamic_max_keys)
            if dynamic is None:
                dynamic = self.device_state.get(self._dynamic_max_keys[0])
            if dynamic is not None:
                try:
                    numeric = float(dynamic)
                except (TypeError, ValueError):
                    pass
                else:
                    if self._dynamic_max_transform:
                        numeric = self._dynamic_max_transform(numeric)
                    return numeric
        return super().native_max_value

    async def async_set_native_value(self, value: float) -> None:
        previous_value = self._optimistic_value
        self._optimistic_value = value
        self.async_write_ha_state()
        api_value = self._value_to_api(value)
        try:
            await self._async_call_and_refresh(self._setter(api_value))
        except V2CError as err:
            self._optimistic_value = previous_value
            self.async_write_ha_state()
            raise HomeAssistantError(str(err)) from err
