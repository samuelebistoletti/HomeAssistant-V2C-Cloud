"""Sensor platform for the V2C Cloud integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CHARGE_STATE_LABELS, DOMAIN
from .entity import V2CEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C Cloud sensors."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}

    entities: list[SensorEntity] = []
    for device_id in devices:
        entities.extend(
            (
                V2CChargingStateSensor(coordinator, client, device_id),
                V2CIntensitySensor(coordinator, client, device_id),
                V2CMinIntensitySensor(coordinator, client, device_id),
                V2CMaxIntensitySensor(coordinator, client, device_id),
                V2CMaxPowerSensor(coordinator, client, device_id),
                V2CVersionSensor(coordinator, client, device_id),
                V2CMacAddressSensor(coordinator, client, device_id),
                V2CRfidCardsSensor(coordinator, client, device_id),
            )
        )

    async_add_entities(entities)


class V2CChargingStateSensor(V2CEntity, SensorEntity):
    """Representation of the charging state reported by the charger."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id)
        self._attr_translation_key = "charging_state"
        self._attr_unique_id = f"{device_id}_charging_state"

    @property
    def native_value(self) -> str | int | None:
        """Return the current charging state."""
        value = self.device_state.get("current_state")
        if value is None:
            return None
        try:
            index = int(value)
            return CHARGE_STATE_LABELS.get(index, index)
        except (TypeError, ValueError):
            return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw state information."""
        attrs: dict[str, Any] = {}
        if "current_state" in self.device_state:
            attrs["state_code"] = self.device_state["current_state"]
        reported_value = self.get_reported_value("status", "chargingstate")
        if reported_value is not None:
            attrs["reported_status"] = reported_value
        return attrs


class _IntensityBaseSensor(V2CEntity, SensorEntity):
    """Base class for sensors exposing intensity values."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT

    reported_keys: tuple[str, ...] = ()

    def __init__(self, coordinator, client, device_id, key: str) -> None:
        super().__init__(coordinator, client, device_id)
        self._key = key

    @property
    def native_value(self) -> float | None:
        """Return the intensity value."""
        reported_value = self.get_reported_value(*self.reported_keys)
        if reported_value is None:
            reported_value = self.device_state.get(self._key)

        if reported_value is None:
            return None

        try:
            return float(reported_value)
        except (TypeError, ValueError):
            return None


class V2CIntensitySensor(_IntensityBaseSensor):
    """Sensor for the currently configured charging intensity."""

    reported_keys = ("intensity", "currentintensity", "current_intensity")

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id, "intensity")
        self._attr_translation_key = "current_intensity"
        self._attr_unique_id = f"{device_id}_intensity"


class V2CMinIntensitySensor(_IntensityBaseSensor):
    """Sensor for the minimum allowed car intensity."""

    reported_keys = ("mincarint", "min_intensity", "mincarintensity")

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id, "min_intensity")
        self._attr_translation_key = "min_intensity"
        self._attr_unique_id = f"{device_id}_min_intensity"


class V2CMaxIntensitySensor(_IntensityBaseSensor):
    """Sensor for the maximum allowed car intensity."""

    reported_keys = ("maxcarint", "max_intensity", "maxcarintensity")

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id, "max_intensity")
        self._attr_translation_key = "max_intensity"
        self._attr_unique_id = f"{device_id}_max_intensity"


class V2CMaxPowerSensor(V2CEntity, SensorEntity):
    """Sensor exposing the configured maximum power."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id)
        self._attr_translation_key = "max_power"
        self._attr_unique_id = f"{device_id}_max_power"

    @property
    def native_value(self) -> float | None:
        """Return the maximum power in kW."""
        reported_value = self.get_reported_value("maxpower", "max_power")
        if reported_value is None:
            reported_value = self.device_state.get("max_power")

        if reported_value is None:
            return None
        try:
            return float(reported_value)
        except (TypeError, ValueError):
            return None


class V2CVersionSensor(V2CEntity, SensorEntity):
    """Sensor exposing the firmware version."""

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id)
        self._attr_translation_key = "firmware_version"
        self._attr_unique_id = f"{device_id}_firmware_version"
        self._attr_icon = "mdi:chip"

    @property
    def native_value(self) -> str | None:
        """Return the firmware version."""
        version = self.device_state.get("version")
        if version is None:
            version = self.get_reported_value("version")
        if version is None:
            return None
        return str(version)


class V2CMacAddressSensor(V2CEntity, SensorEntity):
    """Sensor exposing the MAC address reported by the charger."""

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id)
        self._attr_translation_key = "mac_address"
        self._attr_unique_id = f"{device_id}_mac"
        self._attr_icon = "mdi:chip"

    @property
    def native_value(self) -> str | None:
        mac = self.device_state.get("mac_address")
        if mac is None:
            mac = self.get_reported_value("mac")
        return str(mac) if mac else None


class V2CRfidCardsSensor(V2CEntity, SensorEntity):
    """Sensor indicating the number of configured RFID cards."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, client, device_id) -> None:
        super().__init__(coordinator, client, device_id)
        self._attr_translation_key = "rfid_cards"
        self._attr_unique_id = f"{device_id}_rfid_cards"
        self._attr_icon = "mdi:card-account-details"

    @property
    def native_value(self) -> int | None:
        rfid_cards = self.device_state.get("rfid_cards")
        if isinstance(rfid_cards, list):
            return len(rfid_cards)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        rfid_cards = self.device_state.get("rfid_cards")
        if isinstance(rfid_cards, list):
            return {"rfid_cards": rfid_cards}
        raw = self.device_state.get("additional", {}).get("rfid_cards_raw")
        if raw is not None:
            return {"rfid_cards_raw": raw}
        return None
