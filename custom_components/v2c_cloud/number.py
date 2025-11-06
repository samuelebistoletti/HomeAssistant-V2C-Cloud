"""Number entities for configurable numeric values on the V2C charger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import time
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower

try:  # Home Assistant >= 2024.3
    from homeassistant.const import UnitOfVoltage
except ImportError:  # pragma: no cover - fallback for older cores
    UnitOfVoltage = None
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
from .local_api import (
    async_get_or_create_local_coordinator,
    async_write_keyword,
    get_local_data,
    V2CLocalApiError,
)
from .v2c_cloud import V2CError

CURRENT_MIN = 6.0
CURRENT_MAX = 32.0
CURRENT_STEP = 1.0
POWER_MIN = MAX_POWER_MIN_KW
POWER_MAX = MAX_POWER_MAX_KW
POWER_STEP = 0.1
VOLTAGE_MIN = 100.0
VOLTAGE_MAX = 300.0
VOLTAGE_STEP = 1.0


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
                    runtime_data,
                    device_id,
                    name_key="current_intensity",
                    unique_suffix="intensity",
                    reported_keys=("intensity", "currentintensity", "current_int", "current_intensity", "car_intensity"),
                    setter=lambda api_value, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "Intensity",
                        api_value,
                    ),
                    local_key="Intensity",
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                    refresh_after_call=False,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="voltage_installation",
                    unique_suffix="voltage_installation",
                    reported_keys=("voltageinstallation", "voltage_installation"),
                    setter=lambda api_value, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "VoltageInstallation",
                        api_value,
                    ),
                    local_key="VoltageInstallation",
                    native_unit=UnitOfVoltage.VOLT if UnitOfVoltage else "V",
                    minimum=VOLTAGE_MIN,
                    maximum=VOLTAGE_MAX,
                    step=VOLTAGE_STEP,
                    value_to_api=lambda value: int(round(value)),
                    refresh_after_call=False,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="min_intensity",
                    unique_suffix="min_intensity",
                    reported_keys=("mincarint", "min_intensity", "mincarintensity", "min_car_int", "mincar_int"),
                    setter=lambda api_value, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "MinIntensity",
                        api_value,
                    ),
                    local_key="MinIntensity",
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                    refresh_after_call=False,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="contracted_power",
                    unique_suffix="contracted_power",
                    reported_keys=("contractedpower", "contracted_power"),
                    setter=lambda api_value, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "ContractedPower",
                        api_value,
                    ),
                    local_key="ContractedPower",
                    native_unit=UnitOfPower.KILO_WATT,
                    minimum=POWER_MIN,
                    maximum=POWER_MAX,
                    step=POWER_STEP,
                    value_to_api=lambda value: int(round(value * 1000)),
                    source_to_native=lambda raw: raw / 1000 if raw else raw,
                    refresh_after_call=False,
                ),
                V2CNumberEntity(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="max_intensity",
                    unique_suffix="max_intensity",
                    reported_keys=("maxcarint", "max_intensity", "maxcarintensity", "max_car_int", "maxcar_int"),
                    setter=lambda api_value, _device_id=device_id: async_write_keyword(
                        hass,
                        runtime_data,
                        _device_id,
                        "MaxIntensity",
                        api_value,
                    ),
                    local_key="MaxIntensity",
                    native_unit=UnitOfElectricCurrent.AMPERE,
                    minimum=CURRENT_MIN,
                    maximum=CURRENT_MAX,
                    step=CURRENT_STEP,
                    value_to_api=lambda value: int(round(value)),
                    refresh_after_call=False,
                ),
            )
        )

    async_add_entities(entities)


class V2CNumberEntity(V2CEntity, NumberEntity):
    """Generic number entity for V2C Chargers."""

    _attr_entity_category = EntityCategory.CONFIG
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
        local_key: str | None = None,
        refresh_after_call: bool = True,
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._reported_keys = reported_keys
        self._setter = setter
        self._runtime_data = runtime_data
        self._local_key = local_key
        self._refresh_after_call = refresh_after_call
        self._attr_translation_key = name_key
        self._attr_unique_id = f"v2c_{device_id}_{unique_suffix}_number"
        self._attr_native_unit_of_measurement = native_unit
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._value_to_api = value_to_api or (lambda value: value)
        self._source_to_native = source_to_native or (lambda value: value)
        self._dynamic_max_keys = dynamic_max_keys
        self._dynamic_max_transform = dynamic_max_transform
        self._optimistic_value: float | None = None
        self._last_command_ts: float | None = None
        self._local_coordinator = None

    @property
    def native_value(self) -> float | None:
        value = None
        if self._local_key:
            local_data = get_local_data(self._runtime_data, self._device_id)
            if isinstance(local_data, dict) and self._local_key in local_data:
                value = local_data.get(self._local_key)
        if value is None:
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
        now = time.monotonic()
        if self._should_hold_value(native_numeric, now):
            return self._optimistic_value

        self._optimistic_value = native_numeric
        self._last_command_ts = None
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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._local_key:
            return
        coordinator = await async_get_or_create_local_coordinator(
            self.hass,
            self._runtime_data,
            self._device_id,
        )
        self._local_coordinator = coordinator
        remove_listener = coordinator.async_add_listener(self.async_write_ha_state)
        self.async_on_remove(remove_listener)

    async def async_set_native_value(self, value: float) -> None:
        previous_value = self._optimistic_value
        self._optimistic_value = value
        self._last_command_ts = time.monotonic()
        self.async_write_ha_state()
        api_value = self._value_to_api(value)
        try:
            await self._async_call_and_refresh(
                self._setter(api_value),
                refresh=self._refresh_after_call,
            )
        except (V2CError, V2CLocalApiError) as err:
            self._optimistic_value = previous_value
            self._last_command_ts = None
            self.async_write_ha_state()
            raise HomeAssistantError(str(err)) from err

    def _should_hold_value(self, updated_value: float, now: float) -> bool:
        if (
            self._optimistic_value is None
            or self._last_command_ts is None
            or now - self._last_command_ts >= self._OPTIMISTIC_HOLD_SECONDS
        ):
            if (
                self._last_command_ts is not None
                and now - self._last_command_ts >= self._OPTIMISTIC_HOLD_SECONDS
            ):
                self._last_command_ts = None
            return False
        return not self._values_match(updated_value, self._optimistic_value)

    def _values_match(self, first: float, second: float) -> bool:
        step = self._attr_native_step
        tolerance = step / 2 if isinstance(step, (int, float)) and step else 0.5
        return abs(first - second) <= tolerance
