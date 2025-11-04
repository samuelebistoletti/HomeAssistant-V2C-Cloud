"""Sensor platform for the V2C Cloud integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)

try:  # Home Assistant >= 2023.8
    from homeassistant.const import UnitOfVoltage
except ImportError:  # pragma: no cover - older releases
    UnitOfVoltage = None
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import CHARGE_STATE_LABELS, DOMAIN
from .entity import build_device_info
from .local_api import async_get_or_create_local_coordinator, resolve_static_ip

_LOGGER = logging.getLogger(__name__)


def _as_float(value: Any) -> float | None:
    """Convert arbitrary value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Convert arbitrary value to int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        if "." in text:
            return int(float(text))
        return int(text)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    """Convert arbitrary payload to boolean."""
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


def _as_str(value: Any) -> str | None:
    """Return a trimmed string or None."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _charge_state_label(value: Any) -> str | None:
    """Return the human-friendly charge state label."""
    index = _as_int(value)
    if index is None:
        return None
    return CHARGE_STATE_LABELS.get(index, str(index))


@dataclass(frozen=True, kw_only=True)
class V2CLocalRealtimeSensorDescription(SensorEntityDescription):
    """Description for V2C local realtime sensors."""

    unique_id_suffix: str
    value_fn: Callable[[Any], Any] | None = None


REALTIME_SENSOR_DESCRIPTIONS: tuple[V2CLocalRealtimeSensorDescription, ...] = (
    V2CLocalRealtimeSensorDescription(
        key="ID",
        translation_key="device_identifier",
        icon="mdi:identifier",
        unique_id_suffix="local_id",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="FirmwareVersion",
        translation_key="firmware_version",
        icon="mdi:fuse",
        unique_id_suffix="firmware_version",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargeState",
        translation_key="charge_state",
        icon="mdi:ev-station",
        unique_id_suffix="charging_state",
        value_fn=_charge_state_label,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ReadyState",
        translation_key="ready_state",
        icon="mdi:check-circle-outline",
        unique_id_suffix="local_ready_state",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargePower",
        translation_key="charge_power",
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_charge_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="VoltageInstallation",
        translation_key="voltage_installation",
        icon="mdi:flash",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfVoltage.VOLT if UnitOfVoltage else "V",
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_voltage_installation",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargeEnergy",
        translation_key="charge_energy",
        icon="mdi:lightning-bolt-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_charge_energy",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SlaveError",
        translation_key="slave_error",
        icon="mdi:alert-circle-outline",
        unique_id_suffix="local_slave_error",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargeTime",
        translation_key="charge_time",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_charge_time",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="HousePower",
        translation_key="house_power",
        icon="mdi:home-lightning-bolt-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_house_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="FVPower",
        translation_key="fv_power",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_fv_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="BatteryPower",
        translation_key="battery_power",
        icon="mdi:battery",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_battery_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Paused",
        translation_key="paused",
        icon="mdi:pause-circle-outline",
        unique_id_suffix="local_paused",
        value_fn=_as_bool,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Locked",
        translation_key="locked_state",
        icon="mdi:lock",
        unique_id_suffix="local_locked",
        value_fn=_as_bool,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Timer",
        translation_key="timer_state",
        icon="mdi:calendar-clock",
        unique_id_suffix="local_timer",
        value_fn=_as_bool,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Intensity",
        translation_key="current_intensity",
        icon="mdi:current-ac",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="intensity",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Dynamic",
        translation_key="dynamic_state",
        icon="mdi:flash-auto",
        unique_id_suffix="local_dynamic",
        value_fn=_as_bool,
    ),
    V2CLocalRealtimeSensorDescription(
        key="MinIntensity",
        translation_key="min_intensity",
        icon="mdi:current-ac",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="min_intensity",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="MaxIntensity",
        translation_key="max_intensity",
        icon="mdi:current-ac",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="max_intensity",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="PauseDynamic",
        translation_key="pause_dynamic",
        icon="mdi:pause-octagon-outline",
        unique_id_suffix="local_pause_dynamic",
        value_fn=_as_bool,
    ),
    V2CLocalRealtimeSensorDescription(
        key="DynamicPowerMode",
        translation_key="dynamic_power_mode",
        icon="mdi:lightning-bolt-circle",
        unique_id_suffix="local_dynamic_power_mode",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ContractedPower",
        translation_key="contracted_power",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="local_contracted_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SSID",
        translation_key="wifi_ssid",
        icon="mdi:wifi",
        unique_id_suffix="local_wifi_ssid",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="IP",
        translation_key="wifi_ip",
        icon="mdi:ip-network",
        unique_id_suffix="local_wifi_ip",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SignalStatus",
        translation_key="signal_status",
        icon="mdi:wifi-strength-2",
        unique_id_suffix="local_signal_status",
        value_fn=_as_int,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up local realtime sensors for each configured charger."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    cloud_coordinator = runtime_data.coordinator
    devices = cloud_coordinator.data.get("devices", {}) if cloud_coordinator.data else {}

    entities: list[SensorEntity] = []

    for device_id in devices:
        coordinator = await async_get_or_create_local_coordinator(hass, runtime_data, device_id)
        for description in REALTIME_SENSOR_DESCRIPTIONS:
            entities.append(
                V2CLocalRealtimeSensor(
                    runtime_data,
                    coordinator,
                    device_id,
                    description,
                )
            )

    async_add_entities(entities)


class V2CLocalRealtimeSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """Sensor backed by the charger local RealTimeData endpoint."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime_data,
        coordinator: DataUpdateCoordinator,
        device_id: str,
        description: V2CLocalRealtimeSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._runtime_data = runtime_data
        self._device_id = device_id
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_unique_id = f"{device_id}_{description.unique_id_suffix}"
        if description.icon:
            self._attr_icon = description.icon
        if description.device_class:
            self._attr_device_class = description.device_class
        if description.native_unit_of_measurement:
            self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        if description.state_class:
            self._attr_state_class = description.state_class

    @property
    def device_info(self):
        """Return registry information for the underlying charger."""
        return build_device_info(self._runtime_data.coordinator, self._device_id)

    @property
    def native_value(self) -> Any:
        """Return the processed value for this sensor."""
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        raw_value = data.get(self.entity_description.key)
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(raw_value)
        return raw_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw value alongside processed values for troubleshooting."""
        data = self.coordinator.data
        if not isinstance(data, dict):
            return {}
        attributes: dict[str, Any] = {"raw_value": data.get(self.entity_description.key)}
        static_ip = data.get("_static_ip") or resolve_static_ip(self._runtime_data, self._device_id)
        if isinstance(static_ip, str):
            attributes["static_ip"] = static_ip
        return attributes
