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
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime

try:  # Home Assistant >= 2023.8
    from homeassistant.const import UnitOfVoltage
except ImportError:  # pragma: no cover - older releases
    UnitOfVoltage = None
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

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


def _as_flag(value: Any) -> int | None:
    """Return 1/0 integers for boolean-like payloads."""
    bool_value = _as_bool(value)
    if bool_value is not None:
        return 1 if bool_value else 0
    int_value = _as_int(value)
    if int_value is None:
        return None
    return 1 if int_value != 0 else 0


STATE_VALUE_LABELS: dict[str, dict[Any, dict[str, str]]] = {
    "ChargeState": {
        0: {"en": CHARGE_STATE_LABELS[0], "it": "Disconnesso"},
        1: {"en": CHARGE_STATE_LABELS[1], "it": "Veicolo collegato"},
        2: {"en": CHARGE_STATE_LABELS[2], "it": "In carica"},
        3: {"en": CHARGE_STATE_LABELS[3], "it": "Ventilazione richiesta"},
        4: {"en": CHARGE_STATE_LABELS[4], "it": "Corto del pilot"},
        5: {"en": CHARGE_STATE_LABELS[5], "it": "Guasto generale"},
    },
    "SlaveError": {
        0: {"en": "No error", "it": "Nessun errore"},
        1: {"en": "Communication", "it": "Comunicazione"},
        2: {"en": "Reading", "it": "Lettura"},
        3: {"en": "Slave", "it": "Slave"},
        4: {"en": "Waiting Wi-Fi", "it": "In attesa Wi-Fi"},
        5: {"en": "Waiting communication", "it": "In attesa comunicazione"},
        6: {"en": "Wrong IP", "it": "IP errato"},
        7: {"en": "Slave not found", "it": "Slave non trovato"},
        8: {"en": "Wrong slave", "it": "Slave errato"},
        9: {"en": "No response", "it": "Nessuna risposta"},
        10: {"en": "Clamp not connected", "it": "Pinza non collegata"},
    },
    "Paused": {
        0: {"en": "No", "it": "No"},
        1: {"en": "Yes", "it": "Si"},
    },
    "ReadyState": {
        0: {"en": "Not ready", "it": "Non pronto"},
        1: {"en": "Ready", "it": "Pronto"},
    },
    "Locked": {
        0: {"en": "Unlocked", "it": "Sbloccato"},
        1: {"en": "Locked", "it": "Bloccato"},
    },
    "Timer": {
        0: {"en": "Timer off", "it": "Timer disattivo"},
        1: {"en": "Timer on", "it": "Timer attivo"},
    },
    "Dynamic": {
        0: {"en": "Disabled", "it": "Disattivato"},
        1: {"en": "Enabled", "it": "Attivato"},
    },
    "PauseDynamic": {
        0: {"en": "Modulating", "it": "In modulazione"},
        1: {"en": "Not modulating", "it": "Non modula"},
    },
    "DynamicPowerMode": {
        0: {"en": "Timed power enabled", "it": "Potenza programmata attiva"},
        1: {"en": "Timed power disabled", "it": "Potenza programmata disattiva"},
        2: {"en": "Exclusive PV mode", "it": "Solo PV"},
        3: {"en": "Minimum power mode", "it": "Modalità potenza minima"},
        4: {"en": "Grid + PV mode", "it": "Modalità rete + PV"},
        5: {"en": "Stop mode", "it": "Modalità stop"},
    },
    "SignalStatus": {
        0: {"en": "Unknown", "it": "Sconosciuto"},
        1: {"en": "Poor", "it": "Scarso"},
        2: {"en": "Fair", "it": "Discreto"},
        3: {"en": "Good", "it": "Buono"},
    },
}


def _localize_state(key: str, value: Any, hass: HomeAssistant) -> str | None:
    """Return a localized label for a mapped state value."""
    if value is None:
        return None
    mapping = STATE_VALUE_LABELS.get(key)
    if not mapping:
        return None
    normalized: Any = value
    if isinstance(normalized, bool):
        normalized = 1 if normalized else 0
    elif isinstance(normalized, str):
        candidate = normalized.strip()
        if candidate.isdigit():
            normalized = int(candidate)
        else:
            candidate_lower = candidate.lower()
            if candidate_lower in mapping:
                normalized = candidate_lower
    label_entry = mapping.get(normalized)
    if label_entry is None:
        return None
    language = (hass.config.language or "en").split("-")[0]
    return label_entry.get(language, label_entry.get("en"))


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
        unique_id_suffix="device_identifier",
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
        unique_id_suffix="charge_state",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ReadyState",
        translation_key="ready_state",
        icon="mdi:check-circle-outline",
        unique_id_suffix="ready_state",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargePower",
        translation_key="charge_power",
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="charge_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargeEnergy",
        translation_key="charge_energy",
        icon="mdi:lightning-bolt-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unique_id_suffix="charge_energy",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SlaveError",
        translation_key="slave_error",
        icon="mdi:alert-circle-outline",
        unique_id_suffix="slave_error",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="ChargeTime",
        translation_key="charge_time",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="charge_time",
        value_fn=_as_int,
    ),
    V2CLocalRealtimeSensorDescription(
        key="HousePower",
        translation_key="house_power",
        icon="mdi:home-lightning-bolt-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="house_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="FVPower",
        translation_key="fv_power",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="fv_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="BatteryPower",
        translation_key="battery_power",
        icon="mdi:battery",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="battery_power",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="Timer",
        translation_key="timer_state",
        icon="mdi:calendar-clock",
        unique_id_suffix="timer_state",
        value_fn=_as_flag,
    ),
    V2CLocalRealtimeSensorDescription(
        key="VoltageInstallation",
        translation_key="grid_voltage",
        icon="mdi:flash",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfVoltage.VOLT if UnitOfVoltage else "V",
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_suffix="grid_voltage",
        value_fn=_as_float,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SSID",
        translation_key="wifi_ssid",
        icon="mdi:wifi",
        unique_id_suffix="wifi_ssid",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="IP",
        translation_key="wifi_ip",
        icon="mdi:ip-network",
        unique_id_suffix="wifi_ip",
        value_fn=_as_str,
    ),
    V2CLocalRealtimeSensorDescription(
        key="SignalStatus",
        translation_key="signal_status",
        icon="mdi:wifi-strength-2",
        unique_id_suffix="signal_status",
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
    devices = (
        cloud_coordinator.data.get("devices", {}) if cloud_coordinator.data else {}
    )

    entities: list[SensorEntity] = []

    for device_id in devices:
        coordinator = await async_get_or_create_local_coordinator(
            hass, runtime_data, device_id
        )
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
        self._attr_unique_id = f"v2c_{device_id}_{description.unique_id_suffix}"
        if description.icon:
            self._attr_icon = description.icon
        if description.device_class:
            self._attr_device_class = description.device_class
        if description.native_unit_of_measurement:
            self._attr_native_unit_of_measurement = (
                description.native_unit_of_measurement
            )
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
        value = raw_value
        if self.entity_description.value_fn is not None:
            value = self.entity_description.value_fn(raw_value)
        localized = _localize_state(self.entity_description.key, value, self.hass)
        if localized is not None:
            return localized
        return value
