"""Binary sensors for the V2C Cloud integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import V2CEntity

if TYPE_CHECKING:
    from . import V2CEntryRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C binary sensors based on coordinator data."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}

    entities: list[BinarySensorEntity] = [
        V2CConnectedBinarySensor(coordinator, client, runtime_data, device_id)
        for device_id in devices
    ]

    async_add_entities(entities)


class V2CConnectedBinarySensor(V2CEntity, BinarySensorEntity):
    """Binary sensor indicating if the charger is online."""

    def __init__(
        self,
        coordinator: Any,
        client: Any,
        runtime_data: V2CEntryRuntimeData,
        device_id: str,
    ) -> None:
        """Initialise the binary sensor for the given device."""
        super().__init__(coordinator, client, device_id)
        self._runtime_data = runtime_data
        self._attr_translation_key = "connected"
        self._attr_unique_id = f"v2c_{device_id}_connected_status"
        self._attr_icon = "mdi:cloud"

    @property
    def available(self) -> bool:
        """Return True only while the cloud can answer the question."""
        # This sensor reports what the CLOUD thinks of the charger, so a dead
        # cloud leaves it with nothing to report. It must not be read as "the
        # charger is offline" — the LAN transport may well be working, and the
        # `Trasporto attivo` sensor is the one that says so.
        if not self._runtime_data.cloud_commands_available:
            return False
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        """Return True when the charger is online."""
        connected = self.device_state.get("connected")
        if connected is None:
            connected = self.get_reported_value("connected")
        if connected is None:
            return None
        if isinstance(connected, bool):
            return connected
        if isinstance(connected, (int, float)):
            return bool(connected)
        if isinstance(connected, str):
            return connected.lower() in {"1", "true", "yes", "online"}
        return None
