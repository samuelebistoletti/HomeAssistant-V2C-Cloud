"""Button entities for invoking momentary V2C Cloud actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import V2CEntity
from .local_api import V2CLocalApiError


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
                    device_id,
                    name_key="trigger_update",
                    unique_suffix="trigger_update",
                    coroutine_factory=lambda _device_id=device_id: client.async_trigger_update(
                        _device_id
                    ),
                    icon="mdi:update",
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
            )
        )

    async_add_entities(entities)


class V2CButton(V2CEntity, ButtonEntity):
    """Generic button for invoking an API command."""

    def __init__(
        self,
        coordinator,
        client,
        device_id: str,
        *,
        name_key: str,
        unique_suffix: str,
        coroutine_factory,
        icon: str,
        entity_category: EntityCategory | None = None,
        refresh_after_call: bool = True,
    ) -> None:
        super().__init__(coordinator, client, device_id)
        self._coroutine_factory = coroutine_factory
        self._refresh_after_call = refresh_after_call
        self._attr_translation_key = name_key
        self._attr_unique_id = f"v2c_{device_id}_{unique_suffix}"
        self._attr_icon = icon
        if entity_category:
            self._attr_entity_category = entity_category

    async def async_press(self) -> None:
        try:
            await self._async_call_and_refresh(
                self._coroutine_factory(),
                refresh=self._refresh_after_call,
            )
        except V2CLocalApiError as err:
            raise HomeAssistantError(str(err)) from err
