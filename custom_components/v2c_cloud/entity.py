"""Base entity classes and helpers for V2C Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN


@dataclass(slots=True)
class DeviceMetadata:
    """Container for device metadata extracted from pairing data."""

    device_id: str
    name: str
    model: str | None = None
    manufacturer: str = "V2C"


class V2CEntity(CoordinatorEntity[DataUpdateCoordinator]):
    """Common base entity for V2C devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id

    @property
    def client(self):
        """Return the API client."""
        return self._client

    @property
    def device_id(self) -> str:
        """Return the associated V2C device id."""
        return self._device_id

    @property
    def device_state(self) -> dict[str, Any]:
        """Shortcut to the coordinator state for this device."""
        data = self.coordinator.data or {}
        devices = data.get("devices") if isinstance(data, dict) else None
        if isinstance(devices, dict):
            return devices.get(self._device_id, {}) or {}
        return {}

    @property
    def pairing(self) -> dict[str, Any]:
        """Return pairing information for this device."""
        if pairing := self.device_state.get("pairing"):
            return pairing

        pairings = self.coordinator.data.get("pairings") if self.coordinator.data else []
        if isinstance(pairings, list):
            for pairing in pairings:
                if pairing.get("deviceId") == self._device_id:
                    return pairing
        return {}

    @property
    def reported(self) -> dict[str, Any]:
        """Return reported state dictionary if available."""
        reported = self.device_state.get("reported")
        if isinstance(reported, dict):
            return reported
        return {}

    @property
    def reported_lower(self) -> dict[str, Any]:
        """Return a lowercase-key mapping of reported values."""
        lowered = self.device_state.get("additional", {}).get("reported_lower")
        if isinstance(lowered, dict):
            return lowered
        # Fallback to build from reported on the fly
        return {str(k).lower(): v for k, v in self.reported.items()}

    def get_reported_value(self, *keys: str) -> Any:
        """Return a reported value, trying multiple possible keys."""
        lowered = self.reported_lower
        for key in keys:
            lookup = key.lower()
            if lookup in lowered:
                return lowered[lookup]
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        pairing = self.pairing
        name = pairing.get("tag") or pairing.get("deviceId") or self._device_id
        model = str(pairing.get("model")) if pairing.get("model") is not None else None
        version = self.device_state.get("version")

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=name,
            manufacturer="V2C",
            model=model,
            sw_version=str(version) if version is not None else None,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def _async_call_and_refresh(self, coro):
        """Helper to perform an API call and refresh coordinator."""
        await coro
        await self.coordinator.async_request_refresh()
