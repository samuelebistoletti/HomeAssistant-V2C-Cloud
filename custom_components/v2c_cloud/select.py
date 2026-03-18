"""Select platform for configuration options exposed by the V2C charger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    DYNAMIC_POWER_MODES,
    INSTALLATION_TYPES,
    LANGUAGES,
    SLAVE_TYPES,
)
from .entity import V2CEntity, _OptimisticHoldMixin
from .local_api import (
    V2CLocalApiError,
    async_get_or_create_local_coordinator,
    async_write_keyword,
    get_local_data,
    get_local_value,
)
from .v2c_cloud import V2CError

if TYPE_CHECKING:
    from . import V2CEntryRuntimeData
    from .v2c_cloud import V2CClient


def _localized_options(
    options_map: dict[int, dict[str, str] | str], hass: HomeAssistant
) -> dict[int, str]:
    """Return options localized to the configured Home Assistant language."""
    language = (hass.config.language or "en").split("-")[0]
    localized: dict[int, str] = {}
    for key, label in options_map.items():
        if isinstance(label, dict):
            localized[key] = label.get(language, label.get("en") or next(iter(label.values())))
        else:
            localized[key] = str(label)
    return localized


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
        device_selects = [
            V2CEnumSelect(
                hass,
                coordinator,
                client,
                runtime_data,
                device_id,
                name_key="installation_type",
                unique_suffix="installation_type",
                options_map=INSTALLATION_TYPES,
                setter=lambda value, _device_id=device_id: client.async_set_installation_type(
                    _device_id, value
                ),
                reported_keys=("inst_type", "installation_type"),
                icon="mdi:home-lightning-bolt",
            ),
            V2CEnumSelect(
                hass,
                coordinator,
                client,
                runtime_data,
                device_id,
                name_key="slave_type",
                unique_suffix="slave_type",
                options_map=SLAVE_TYPES,
                setter=lambda value, _device_id=device_id: client.async_set_slave_type(
                    _device_id, value
                ),
                reported_keys=("slave_type",),
                icon="mdi:robot-industrial",
            ),
            V2CEnumSelect(
                hass,
                coordinator,
                client,
                runtime_data,
                device_id,
                name_key="language",
                unique_suffix="language",
                options_map=LANGUAGES,
                setter=lambda value, _device_id=device_id: client.async_set_language(
                    _device_id, value
                ),
                reported_keys=("language",),
                icon="mdi:translate",
            ),
        ]
        device_selects.append(
            V2CEnumSelect(
                hass,
                coordinator,
                client,
                runtime_data,
                device_id,
                name_key="dynamic_power_mode",
                unique_suffix="dynamic_power_mode",
                options_map=DYNAMIC_POWER_MODES,
                setter=lambda value, _device_id=device_id: async_write_keyword(
                    hass,
                    runtime_data,
                    _device_id,
                    "DynamicPowerMode",
                    value,
                ),
                reported_keys=("dynamicpowermode", "dynamic_power_mode"),
                local_key="DynamicPowerMode",
                refresh_after_call=False,
                icon="mdi:lightning-bolt-circle",
            )
        )
        entities.extend(device_selects)

    async_add_entities(entities)


class V2CEnumSelect(_OptimisticHoldMixin, V2CEntity, SelectEntity):
    """Generic select entity backed by an integer option map."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        client: V2CClient,
        runtime_data: V2CEntryRuntimeData,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        options_map: dict[int, str],
        setter: Callable[[int], Awaitable[Any]],
        reported_keys: tuple[str, ...],
        local_key: str | None = None,
        refresh_after_call: bool = True,
        icon: str | None = None,
    ) -> None:
        """Initialise the select entity with coordinator, client and option map."""
        super().__init__(coordinator, client, device_id)
        self._runtime_data = runtime_data
        localized_map = _localized_options(options_map, hass)
        self._options_map = localized_map
        self._options = list(localized_map.values())
        self._reverse_map = {label.lower(): key for key, label in localized_map.items()}
        self._setter = setter
        self._reported_keys = reported_keys
        self._local_key = local_key
        self._refresh_after_call = refresh_after_call
        self._local_coordinator = None

        self._attr_translation_key = name_key
        self._attr_unique_id = f"v2c_{device_id}_{unique_suffix}"
        self._attr_options = self._options
        if icon:
            self._attr_icon = icon

        self._optimistic_value: int | None = None
        self._last_command_ts: float | None = None
        initial_value = self._get_state_value()
        resolved = self._resolve_value(initial_value)
        if resolved is not None:
            self._optimistic_value = resolved

    @property
    def available(self) -> bool:
        """Return True if the entity can be controlled."""
        if self._local_coordinator is not None:
            return self._local_coordinator.last_update_success
        return self.coordinator.last_update_success

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option label."""
        value = self._get_state_value()
        resolved = self._resolve_value(value)
        if resolved is not None:
            if self._should_hold_value(resolved):
                return self._options_map.get(self._optimistic_value)
            self._optimistic_value = resolved
            self._clear_command()
            return self._options_map.get(resolved)

        if self._optimistic_value is not None:
            self._expire_hold_if_needed()
            return self._options_map.get(self._optimistic_value)

        return None

    async def async_added_to_hass(self) -> None:
        """Subscribe to local coordinator updates when a local key is configured."""
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
        """Select the given option and push the change to the device."""
        for key, label in self._options_map.items():
            if label == option:
                previous = self._optimistic_value
                self._optimistic_value = key
                self._record_command()
                self.async_write_ha_state()
                try:
                    await self._async_call_and_refresh(
                        self._setter(key), refresh=self._refresh_after_call
                    )
                except (V2CError, V2CLocalApiError) as err:
                    self._optimistic_value = previous
                    self._clear_command()
                    self.async_write_ha_state()
                    raise HomeAssistantError(str(err)) from err
                return
        raise ValueError(f"Unsupported option {option}")

    def _get_state_value(self) -> Any:
        """Retrieve the latest value from local data or reported payload."""
        if self._local_key:
            local_data = get_local_data(self._runtime_data, self._device_id)
            if isinstance(local_data, dict):
                found, value = get_local_value(local_data, self._local_key)
                if found:
                    return value
            # Local entities do not fall back to cloud reported data
            return None
        value = self.get_reported_value(*self._reported_keys)
        if value is None and self._reported_keys:
            value = self.device_state.get(self._reported_keys[0])
        return value

    def _should_hold_value(self, resolved: int) -> bool:
        return (
            self._optimistic_value is not None
            and self._is_within_hold()
            and resolved != self._optimistic_value
        )
