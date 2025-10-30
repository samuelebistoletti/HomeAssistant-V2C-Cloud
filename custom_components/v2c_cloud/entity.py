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
        model: str | None = None

        version_info = self.device_state.get("additional", {}).get("version_info")
        if isinstance(version_info, dict):
            preferred_order = (
                version_info.get("modelName"),
                version_info.get("modelId"),
                version_info.get("commercialName"),
            )
            for candidate in preferred_order:
                if isinstance(candidate, str) and candidate.strip():
                    model = candidate
                    break
            if isinstance(model, str):
                normalized = model.strip()
                if normalized.upper() == "INIT":
                    normalized = ""
                else:
                    normalized = normalized.replace("_", " ").title()
                model = normalized or None

        if model is None:
            pairing_model = pairing.get("modelName") or pairing.get("model_name")
            if pairing_model:
                model = str(pairing_model).strip()
                model = model.replace("_", " ").title()
            else:
                pairing_model_code = pairing.get("model")
                if isinstance(pairing_model_code, str) and pairing_model_code.strip():
                    model = pairing_model_code.replace("_", " ").title()
                elif isinstance(pairing_model_code, (int, float)) and pairing_model_code not in (0, 0.0):
                    model = f"Model {pairing_model_code}"

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
