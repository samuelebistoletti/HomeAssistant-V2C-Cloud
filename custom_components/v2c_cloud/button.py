"""Button entities for invoking momentary V2C Cloud actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN
from .entity import V2CEntity, build_device_info
from .local_api import V2CLocalApiError
from .v2c_cloud import V2CError

if TYPE_CHECKING:
    from . import V2CEntryRuntimeData
    from .power_profiles import PowerProfileCoordinator
    from .v2c_cloud import V2CClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up V2C button entities."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    client = runtime_data.client

    devices = coordinator.data.get("devices", {}) if coordinator.data else {}
    entities: list[ButtonEntity] = []

    for device_id in devices:
        entities.extend(
            (
                V2CButton(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="reboot",
                    unique_suffix="reboot",
                    coroutine_factory=lambda _device_id=device_id: client.async_reboot(
                        _device_id
                    ),
                    icon="mdi:restart",
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                V2CButton(
                    coordinator,
                    client,
                    runtime_data,
                    device_id,
                    name_key="trigger_update",
                    unique_suffix="trigger_update",
                    coroutine_factory=lambda _device_id=device_id: (
                        client.async_trigger_update(_device_id)
                    ),
                    icon="mdi:update",
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
            )
        )

    coordinators = getattr(runtime_data, "profile_coordinators", {})
    if isinstance(coordinators, dict):
        entities.extend(
            V2CRefreshProfilesButton(coord, build_device_info(coordinator, device_id))
            for device_id, coord in coordinators.items()
        )
    async_add_entities(entities)


class V2CButton(V2CEntity, ButtonEntity):
    """Generic button for invoking an API command."""

    def __init__(  # noqa: PLR0913
        self,
        coordinator: DataUpdateCoordinator,
        client: V2CClient,
        runtime_data: V2CEntryRuntimeData,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        coroutine_factory: Callable[[], Any],
        icon: str,
        entity_category: EntityCategory | None = None,
        refresh_after_call: bool = True,
    ) -> None:
        """Initialise the button with coordinator, client and action factory."""
        super().__init__(coordinator, client, device_id)
        self._coroutine_factory = coroutine_factory
        self._refresh_after_call = refresh_after_call
        self._runtime_data = runtime_data
        self._attr_translation_key = name_key
        self._attr_unique_id = f"v2c_{device_id}_{unique_suffix}"
        self._attr_icon = icon
        if entity_category:
            self._attr_entity_category = entity_category

    @property
    def available(self) -> bool:
        """Return True only while the action behind the button can be issued."""
        # Reboot and firmware update are cloud commands with no LAN equivalent.
        # A button that can be pressed but does nothing is a worse answer than
        # one that is visibly out of service.
        if not self._runtime_data.cloud_commands_available:
            return False
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        """Execute the button action."""
        try:
            await self._async_call_and_refresh(
                self._coroutine_factory(),
                refresh=self._refresh_after_call,
            )
        except (V2CError, V2CLocalApiError) as err:
            raise HomeAssistantError(str(err)) from err


class V2CRefreshProfilesButton(CoordinatorEntity, ButtonEntity):
    """Refresh profile entities without invoking any mutating Cloud operation."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_profiles"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: PowerProfileCoordinator, device_info: Any) -> None:
        """Attach a refresh action to the existing charger device."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"v2c_{coordinator.device_id}_refresh_profiles"

    @property
    def available(self) -> bool:
        """Permit recovery from a failed profile read when Cloud auth is usable."""
        return self.coordinator.runtime.cloud_commands_available

    async def async_press(self) -> None:
        """Read the actual Cloud profile list, keeping failed snapshots unavailable."""
        try:
            await self.coordinator.async_refresh()
        except UpdateFailed as error:
            raise HomeAssistantError("Could not refresh Cloud profiles") from error
        if not self.coordinator.last_update_success:
            raise HomeAssistantError("Could not refresh Cloud profiles")
