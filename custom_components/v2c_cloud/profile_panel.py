"""Admin-only profile panel backed by the same validated saves as entities."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN
from .entity import get_pairing_from_coordinator
from .power_profiles import (
    InvalidPowerProfilesError,
    PowerProfileConflictError,
    PowerProfileCoordinator,
    PowerProfileSaveUnconfirmedError,
    async_manage_profile,
    editable_profile,
    profile_revision,
    supports_isolated_profiles,
)
from .v2c_cloud import V2CError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_PANEL_PATH = "v2c-profiles"
_PANEL_STATE = "_profile_panel"
_PANEL_TITLES = {
    "en": "V2C Profiles",
    "fr": "Profils V2C",
    "it": "Profili V2C",
    "es": "Perfiles V2C",
}


def _coordinator(hass: HomeAssistant, msg: dict[str, Any]) -> PowerProfileCoordinator:
    """Allow only configured Cloud chargers, never arbitrary client identifiers."""
    runtime = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    coordinators = getattr(runtime, "profile_coordinators", {})
    if not isinstance(coordinators, dict) or msg["device_id"] not in coordinators:
        raise InvalidPowerProfilesError("Unknown Cloud charger")
    return coordinators[msg["device_id"]]


def _error(
    connection: Any, message_id: int, error: Exception, *, invalid_draft: bool = False
) -> None:
    """Return stable errors without forwarding credentials or Cloud bodies."""
    if isinstance(error, PowerProfileSaveUnconfirmedError):
        code = "save_unconfirmed"
    elif isinstance(error, PowerProfileConflictError):
        code = "profile_conflict"
    elif invalid_draft and isinstance(error, InvalidPowerProfilesError):
        code = "invalid_profile"
    else:
        code = "profiles_unavailable"
    connection.send_error(
        message_id,
        code,
        "Refresh profiles and check their Cloud state before editing again.",
    )


@websocket_api.websocket_command({vol.Required("type"): "v2c_cloud/profiles/devices"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_devices(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """List local integration identities without requesting any Cloud writes."""
    devices = []
    registry = dr.async_get(hass)
    for entry_id, runtime in hass.data.get(DOMAIN, {}).items():
        coordinators = getattr(runtime, "profile_coordinators", {})
        if not isinstance(coordinators, dict):
            continue
        for device_id in coordinators:
            device = registry.async_get_device(identifiers={(DOMAIN, device_id)})
            pairing_name = get_pairing_from_coordinator(
                runtime.coordinator, device_id
            ).get("tag")
            # Some coordinator snapshots keep the pairing only in the account list.
            if not isinstance(pairing_name, str) or not pairing_name.strip():
                pairings = (runtime.coordinator.data or {}).get("pairings", [])
                if isinstance(pairings, list):
                    pairing_name = next(
                        (
                            item.get("tag")
                            for item in pairings
                            if isinstance(item, dict)
                            and item.get("deviceId") == device_id
                        ),
                        None,
                    )
            candidates = (
                device.name_by_user if device else None,
                pairing_name,
                device.name if device else None,
            )
            name = next(
                (
                    value.strip()
                    for value in candidates
                    if isinstance(value, str) and value.strip()
                ),
                device_id,
            )
            devices.append({"entry_id": entry_id, "device_id": device_id, "name": name})
    connection.send_result(msg["id"], devices)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "v2c_cloud/profiles/list",
        vol.Required("entry_id"): str,
        vol.Required("device_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_profiles(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Refresh the actual profiles and return server-side baseline fingerprints."""
    try:
        coordinator = _coordinator(hass, msg)
        await coordinator.async_refresh()
        if not coordinator.last_update_success or not isinstance(
            coordinator.data, list
        ):
            _error(
                connection,
                msg["id"],
                InvalidPowerProfilesError("No current profile list"),
            )
            return
        profiles = [
            {
                "profile": profile,
                "revision": profile_revision(profile),
                "editable": editable_profile(profile),
                "supports_isolated": supports_isolated_profiles(coordinator),
            }
            for profile in coordinator.data
        ]
    except (
        InvalidPowerProfilesError,
        UpdateFailed,
        V2CError,
        ClientError,
        TimeoutError,
    ) as error:
        _error(connection, msg["id"], error)
        return
    connection.send_result(msg["id"], profiles)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "v2c_cloud/profiles/save_battery",
        vol.Required("entry_id"): str,
        vol.Required("device_id"): str,
        vol.Required("profile_name"): str,
        vol.Required("revision"): str,
        vol.Required("group"): vol.In([0, 1]),
        vol.Required("index"): vol.All(int, vol.Range(min=0)),
        vol.Required("allowed"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_save_battery(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Save exactly one supported field without accepting a raw profile payload."""
    try:
        if type(msg["group"]) is not int or type(msg["index"]) is not int:
            _error(connection, msg["id"], InvalidPowerProfilesError("Invalid interval"))
            return
        coordinator = _coordinator(hass, msg)
        await coordinator.async_save(
            msg["profile_name"],
            msg["revision"],
            (msg["group"], msg["index"]),
            allowed=msg["allowed"],
        )
    except (
        InvalidPowerProfilesError,
        UpdateFailed,
        V2CError,
        ClientError,
        TimeoutError,
    ) as error:
        _error(connection, msg["id"], error)
        return
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "v2c_cloud/profiles/manage",
        vol.Required("entry_id"): str,
        vol.Required("device_id"): str,
        vol.Required("action"): vol.In(["create", "edit", "activate", "delete"]),
        vol.Required("profile_name"): str,
        vol.Required("revision"): str,
        vol.Optional("new_name"): str,
        vol.Optional("entries"): list,
        vol.Optional("confirm_active", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manage_profile(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    """Keep profile lifecycle actions separate and validate all editor input."""
    try:
        coordinator = _coordinator(hass, msg)
        await async_manage_profile(
            coordinator,
            msg["action"],
            msg["profile_name"],
            msg["revision"],
            new_name=msg.get("new_name"),
            entries=msg.get("entries"),
            confirm_active=msg.get("confirm_active", False),
        )
    except (
        InvalidPowerProfilesError,
        UpdateFailed,
        V2CError,
        ClientError,
        TimeoutError,
    ) as error:
        _error(connection, msg["id"], error, invalid_draft=True)
        return
    connection.send_result(msg["id"], {"confirmed": True})


async def async_setup_profile_panel(hass: HomeAssistant) -> None:
    """Bundle and register one panel, with no manual frontend installation."""
    state = hass.data[DOMAIN].setdefault(_PANEL_STATE, {})
    async with state.setdefault("lock", asyncio.Lock()):
        if not state.get("registered"):
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/v2c_cloud/profiles.js",
                        str(Path(__file__).with_name("profiles.js")),
                        cache_headers=False,
                    )
                ]
            )
            for command in (
                websocket_devices,
                websocket_profiles,
                websocket_save_battery,
                websocket_manage_profile,
            ):
                websocket_api.async_register_command(hass, command)
            state["registered"] = True
        # Custom sidebar titles are shared across users, like native entity names.
        language = hass.config.language.replace("_", "-").split("-")[0].lower()
        title = _PANEL_TITLES.get(language, _PANEL_TITLES["en"])
        if state.get("visible") and state.get("title") != title:
            frontend.async_remove_panel(hass, _PANEL_PATH)
            state["visible"] = False
        if not state.get("visible") and _panel_wanted(hass):
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=_PANEL_PATH,
                webcomponent_name="v2c-profiles-panel",
                sidebar_title=title,
                sidebar_icon="mdi:ev-station",
                module_url="/v2c_cloud/profiles.js",
                require_admin=True,
            )
            state["visible"] = True
            state["title"] = title


def _panel_wanted(hass: HomeAssistant) -> bool:
    """Keep a shared panel visible while any Cloud entry opts in."""
    return any(
        getattr(runtime, "profile_coordinators", None)
        and getattr(runtime, "show_profile_panel", True) is True
        for runtime in hass.data.get(DOMAIN, {}).values()
    )


def async_remove_profile_panel(hass: HomeAssistant) -> None:
    """Hide the panel when the last Cloud entry unloads; keep routes reusable."""
    if _panel_wanted(hass):
        return
    state = hass.data.get(DOMAIN, {}).get(_PANEL_STATE, {})
    if state.get("visible"):
        frontend.async_remove_panel(hass, _PANEL_PATH)
        state["visible"] = False
