"""Select platform for configuration options exposed by the V2C charger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FV_MODES,
    INSTALLATION_TYPES,
    LANGUAGES,
    SLAVE_TYPES,
)
from .entity import V2CEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C select entities."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}
    entities: list[SelectEntity] = []

    for device_id in devices:
        entities.extend(
            (
                V2CEnumSelect(
                    coordinator,
                    client,
                    device_id,
                    name_key="installation_type",
                    unique_suffix="installation_type",
                    options_map=INSTALLATION_TYPES,
                    setter=lambda value, _device_id=device_id: client.async_set_installation_type(
                        _device_id, value
                    ),
                    reported_keys=("inst_type", "installation_type"),
                ),
                V2CEnumSelect(
                    coordinator,
                    client,
                    device_id,
                    name_key="slave_type",
                    unique_suffix="slave_type",
                    options_map=SLAVE_TYPES,
                    setter=lambda value, _device_id=device_id: client.async_set_slave_type(
                        _device_id, value
                    ),
                    reported_keys=("slave_type",),
                ),
                V2CEnumSelect(
                    coordinator,
                    client,
                    device_id,
                    name_key="language",
                    unique_suffix="language",
                    options_map=LANGUAGES,
                    setter=lambda value, _device_id=device_id: client.async_set_language(
                        _device_id, value
                    ),
                    reported_keys=("language",),
                ),
                V2CEnumSelect(
                    coordinator,
                    client,
                    device_id,
                    name_key="fv_mode",
                    unique_suffix="fv_mode",
                    options_map=FV_MODES,
                    setter=lambda value, _device_id=device_id: client.async_set_fv_mode(
                        _device_id, value
                    ),
                    reported_keys=("chargefvmode", "fv_mode"),
                ),
            )
        )

    async_add_entities(entities)


class V2CEnumSelect(V2CEntity, SelectEntity):
    """Generic select entity backed by an integer option map."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator,
        client,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        options_map: dict[int, str],
        setter: Callable[[int], Awaitable[Any]],
        reported_keys: tuple[str, ...],
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._options_map = options_map
        self._options = list(options_map.values())
        self._reverse_map = {
            label.lower(): key for key, label in options_map.items()
        }
        self._setter = setter
        self._reported_keys = reported_keys

        self._attr_translation_key = name_key
        self._attr_unique_id = f"{device_id}_{unique_suffix}"
        self._attr_options = self._options

        self._optimistic_value: int | None = None

    @property
    def current_option(self) -> str | None:
        value = self.get_reported_value(*self._reported_keys)
        resolved = self._resolve_value(value)
        if resolved is not None:
            self._optimistic_value = resolved
            return self._options_map.get(resolved)

        if self._optimistic_value is not None:
            return self._options_map.get(self._optimistic_value)

        return None

    def _resolve_value(self, value: Any) -> int | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            candidate = int(value)
            if candidate in self._options_map:
                return candidate
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered.isdigit():
                candidate = int(lowered)
                if candidate in self._options_map:
                    return candidate
            if lowered in self._reverse_map:
                return self._reverse_map[lowered]
        return None

    async def async_select_option(self, option: str) -> None:
        for key, label in self._options_map.items():
            if label == option:
                self._optimistic_value = key
                self.async_write_ha_state()
                await self._async_call_and_refresh(self._setter(key))
                return
        raise ValueError(f"Unsupported option {option}")
