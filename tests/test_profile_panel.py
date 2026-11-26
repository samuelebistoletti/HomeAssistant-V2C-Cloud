"""Shared panel/entity snapshots, explicit targets, permissions and lifecycle."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.v2c_cloud import profile_panel
from custom_components.v2c_cloud.button import V2CRefreshProfilesButton
from custom_components.v2c_cloud.power_profiles import (
    PowerProfileCoordinator,
    PowerProfileSaveUnconfirmedError,
    profile_battery_slots,
    profile_revision,
    read_profile_list,
)
from custom_components.v2c_cloud.switch import (
    V2CProfileBatterySwitch,
    _async_setup_profile_switches,
)
from custom_components.v2c_cloud.v2c_cloud import V2CRequestError


@pytest.fixture
def panel():
    interval = {
        "hourStart": 0,
        "hourEnd": 24,
        "charge_fv_mode": 2,
        "bat_mode": 0,
        "power": 120,
        "intensity": {"L1": None},
        "future": [None, False],
    }
    profile = {
        "deviceId": "device",
        "name": "test",
        "active": False,
        "updateAt": "original",
        "powerweekday": json.dumps({"type": 0, "tram": [interval]}),
        "powerweekend": json.dumps({"type": 1, "tram": [interval]}),
    }
    state = [profile]
    client = MagicMock()
    client.async_list_personal_power_profiles = AsyncMock(
        side_effect=lambda _: deepcopy(state)
    )

    async def save(device, name, stamp, body):
        state[0]["powerweekday"] = json.dumps(body["powers"][0])
        state[0]["powerweekend"] = json.dumps(body["powers"][1])
        state[0]["updateAt"] = "saved"

    client.async_save_personal_power_profile = AsyncMock(side_effect=save)
    hass = MagicMock()
    hass.config.language = "en"
    hass.http.async_register_static_paths = AsyncMock()
    runtime = SimpleNamespace(
        client=client,
        cloud_commands_available=True,
        profile_lock=asyncio.Lock(),
        coordinator=MagicMock(
            data={"devices": {"device": {"pairing": {"tag": "Charger"}}}}
        ),
    )
    coordinator = PowerProfileCoordinator(hass, runtime, "device")
    coordinator.async_set_updated_data(deepcopy(state))
    runtime.profile_coordinators = {"device": coordinator}
    hass.data = {"v2c_cloud": {"entry": runtime}}
    connection = MagicMock()
    connection.user.is_admin = True
    message = {"id": 1, "entry_id": "entry", "device_id": "device"}
    return hass, runtime, coordinator, state, connection, message


async def test_panel_reads_current_cloud_profiles_without_a_write(panel):
    hass, runtime, coordinator, _state, connection, msg = panel
    await profile_panel.websocket_profiles(hass, connection, msg)
    result = connection.send_result.call_args.args[1]
    assert result[0]["revision"] == profile_revision(coordinator.data[0])
    assert result[0]["editable"] is True
    runtime.client.async_list_personal_power_profiles.assert_awaited_once_with("device")
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_panel_and_entity_share_confirmed_state(panel):
    hass, runtime, coordinator, _state, connection, msg = panel
    slot = next(iter(profile_battery_slots(coordinator.data[0])))
    entity = V2CProfileBatterySwitch(coordinator, slot, {}, "Weekdays")
    assert entity.is_on is True
    await profile_panel.websocket_save_battery(
        hass,
        connection,
        {
            **msg,
            "profile_name": "test",
            "revision": profile_revision(coordinator.data[0]),
            "group": 0,
            "index": 0,
            "allowed": False,
        },
    )
    connection.send_result.assert_called_once_with(1, {"saved": True})
    assert entity.is_on is False
    assert entity.available is True
    runtime.client.async_save_personal_power_profile.assert_awaited_once()
    runtime.client.async_update_personal_power_profile.assert_not_called()


@pytest.mark.parametrize(
    "handler",
    [
        profile_panel.websocket_devices,
        profile_panel.websocket_profiles,
        profile_panel.websocket_save_battery,
    ],
)
@pytest.mark.parametrize("user", [None, SimpleNamespace(is_admin=False)])
async def test_all_panel_commands_require_an_administrator(panel, handler, user):
    hass, runtime, _coord, _state, connection, msg = panel
    connection.user = user
    with pytest.raises(PermissionError):
        await handler(hass, connection, msg)
    runtime.client.async_list_personal_power_profiles.assert_not_called()
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_panel_rejects_unknown_charger_without_api_access(panel):
    hass, runtime, _coord, _state, connection, msg = panel
    await profile_panel.websocket_profiles(
        hass, connection, {**msg, "device_id": "unconfigured"}
    )
    assert connection.send_error.call_args.args[1] == "profiles_unavailable"
    runtime.client.async_list_personal_power_profiles.assert_not_called()


async def test_panel_refuses_a_stale_baseline_before_post(panel):
    hass, runtime, _coord, _state, connection, msg = panel
    await profile_panel.websocket_save_battery(
        hass,
        connection,
        {
            **msg,
            "profile_name": "test",
            "revision": "old",
            "group": 0,
            "index": 0,
            "allowed": False,
        },
    )
    assert connection.send_error.call_args.args[1] == "profile_conflict"
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_profile_read_failure_invalidates_controls_and_has_no_secret_error(panel):
    hass, runtime, coordinator, _state, connection, msg = panel
    entity = V2CProfileBatterySwitch(
        coordinator,
        next(iter(profile_battery_slots(coordinator.data[0]))),
        {},
        "Weekdays",
    )
    runtime.client.async_list_personal_power_profiles.side_effect = V2CRequestError(
        "secret API response"
    )
    await profile_panel.websocket_profiles(hass, connection, msg)
    assert entity.available is False
    assert entity.is_on is None
    assert "secret" not in str(connection.send_error.call_args)


async def test_failed_save_invalidates_every_consumer_without_retry(panel):
    _hass, runtime, coordinator, _state, _connection, _msg = panel
    entity = V2CProfileBatterySwitch(
        coordinator,
        next(iter(profile_battery_slots(coordinator.data[0]))),
        {},
        "Weekdays",
    )
    runtime.client.async_save_personal_power_profile.side_effect = None
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_off()
    assert not coordinator.last_update_success
    assert not entity.available
    runtime.client.async_save_personal_power_profile.assert_awaited_once()


async def test_entity_identity_survives_reordering_and_never_targets_new_index(panel):
    _hass, runtime, coordinator, state, _connection, _msg = panel
    schedule = json.loads(state[0]["powerweekday"])
    schedule["tram"][0]["hourStart"] = 1
    schedule["tram"].insert(0, {"hourStart": 0, "hourEnd": 1, "charge_fv_mode": 3})
    state[0]["powerweekday"] = json.dumps(schedule)
    await coordinator.async_refresh()
    slot = next(iter(profile_battery_slots(state[0])))
    entity = V2CProfileBatterySwitch(coordinator, slot, {}, "Weekdays")
    schedule["tram"].reverse()
    state[0]["powerweekday"] = json.dumps(schedule)
    await coordinator.async_refresh()
    assert (
        entity._attr_unique_id
        == V2CProfileBatterySwitch(coordinator, slot, {}, "Weekdays")._attr_unique_id
    )
    await entity.async_turn_off()
    written = runtime.client.async_save_personal_power_profile.call_args.args[3]
    assert written["powers"][0]["tram"][0]["bat_mode"] == 1
    assert written["powers"][0]["tram"][1]["charge_fv_mode"] == 3


@pytest.mark.parametrize("change", ["deleted", "duplicate", "mode", "metadata"])
async def test_unsupported_entity_target_cannot_be_written(panel, change):
    _hass, runtime, coordinator, state, _connection, _msg = panel
    entity = V2CProfileBatterySwitch(
        coordinator, next(iter(profile_battery_slots(state[0]))), {}, "Weekdays"
    )
    if change == "deleted":
        state.clear()
    elif change == "duplicate":
        state.append(deepcopy(state[0]))
    elif change == "metadata":
        state[0]["future_metadata"] = True
    else:
        schedule = json.loads(state[0]["powerweekday"])
        schedule["tram"][0]["charge_fv_mode"] = 3
        state[0]["powerweekday"] = json.dumps(schedule)
    await coordinator.async_refresh()
    assert not entity.available
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_off()
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_discovery_adds_new_slots_only_once_and_marks_old_ones_unavailable(panel):
    hass, runtime, coordinator, state, _connection, _msg = panel
    add = MagicMock()
    entry = MagicMock()
    await _async_setup_profile_switches(hass, entry, runtime, add)
    initial = add.call_args.args[0]
    assert len(initial) == 2
    await coordinator.async_refresh()
    assert add.call_count == 1
    group = json.loads(state[0]["powerweekday"])
    group["tram"][0]["hourEnd"] = 12
    state[0]["powerweekday"] = json.dumps(group)
    await coordinator.async_refresh()
    assert add.call_count == 2
    assert len(add.call_args.args[0]) == 1
    assert not initial[0].available
    assert initial[1].available


async def test_refresh_button_can_recover_a_failed_snapshot_without_post(panel):
    _hass, runtime, coordinator, _state, _connection, _msg = panel
    coordinator.async_set_update_error(UpdateFailed("stale"))
    button = V2CRefreshProfilesButton(coordinator, {})
    assert button.available
    await button.async_press()
    assert coordinator.last_update_success
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_panel_registration_is_single_and_reusable_after_unload(
    panel, monkeypatch
):
    hass, runtime, _coord, _state, _connection, _msg = panel
    register = AsyncMock()
    commands = MagicMock()
    remove = MagicMock()
    monkeypatch.setattr(profile_panel.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(profile_panel.websocket_api, "async_register_command", commands)
    monkeypatch.setattr(profile_panel.frontend, "async_remove_panel", remove)
    await asyncio.gather(
        profile_panel.async_setup_profile_panel(hass),
        profile_panel.async_setup_profile_panel(hass),
    )
    register.assert_awaited_once()
    assert register.call_args.kwargs["require_admin"] is True
    assert commands.call_count == 4
    hass.http.async_register_static_paths.assert_awaited_once()
    profile_panel.async_remove_profile_panel(hass)
    remove.assert_not_called()
    del hass.data["v2c_cloud"]["entry"]
    profile_panel.async_remove_profile_panel(hass)
    remove.assert_called_once()
    hass.data["v2c_cloud"]["entry"] = runtime
    await profile_panel.async_setup_profile_panel(hass)
    assert register.await_count == 2
    hass.http.async_register_static_paths.assert_awaited_once()
    assert commands.call_count == 4


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("en", "V2C Profiles"),
        ("fr", "Profils V2C"),
        ("it", "Profili V2C"),
        ("es", "Perfiles V2C"),
        ("en-GB", "V2C Profiles"),
        ("de", "V2C Profiles"),
    ],
)
async def test_sidebar_title_uses_installation_language(
    panel, monkeypatch, language, title
):
    hass = panel[0]
    hass.config.language = language
    register = AsyncMock()
    monkeypatch.setattr(profile_panel.panel_custom, "async_register_panel", register)
    await profile_panel.async_setup_profile_panel(hass)
    assert register.call_args.kwargs["sidebar_title"] == title


async def test_sidebar_title_updates_on_reload_after_language_change(
    panel, monkeypatch
):
    hass = panel[0]
    register = AsyncMock()
    remove = MagicMock()
    monkeypatch.setattr(profile_panel.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(profile_panel.frontend, "async_remove_panel", remove)
    hass.config.language = "fr"
    await profile_panel.async_setup_profile_panel(hass)
    assert register.call_args.kwargs["sidebar_title"] == "Profils V2C"
    hass.config.language = "en"
    await profile_panel.async_setup_profile_panel(hass)
    assert register.call_args.kwargs["sidebar_title"] == "V2C Profiles"
    remove.assert_called_once_with(hass, "v2c-profiles")
    assert register.await_count == 2
    hass.http.async_register_static_paths.assert_awaited_once()


def test_opaque_profiles_and_unknown_fields_survive_read_copy(panel):
    _hass, _runtime, _coordinator, state, _connection, _msg = panel
    state[0]["unknown_metadata"] = [None, False]
    original = deepcopy(state)
    result = read_profile_list(state, "device")
    result[0]["name"] = "copy"
    assert state == original
    assert result[0]["unknown_metadata"] == [None, False]


@pytest.mark.parametrize(
    "bounds", [(None, 24), (False, 24), (0, float("nan")), (12, 12), (0, 25)]
)
def test_invalid_interval_identity_does_not_create_an_entity(panel, bounds):
    profile = panel[3][0]
    group = json.loads(profile["powerweekday"])
    group["tram"][0].update(hourStart=bounds[0], hourEnd=bounds[1])
    profile["powerweekday"] = json.dumps(group)
    assert not any(json.loads(key)[1] == 0 for key in profile_battery_slots(profile))


@pytest.mark.parametrize("action", ["create", "edit", "activate", "delete"])
async def test_management_lifecycle_confirmed_by_readback(panel, action):
    from custom_components.v2c_cloud.power_profiles import async_manage_profile

    _hass, runtime, coordinator, state, _connection, _msg = panel
    baseline = deepcopy(state[0])

    async def save(device, name, stamp, body):
        target = next((p for p in state if p["name"] == name), None)
        if target is None:
            target = {**deepcopy(baseline), "name": name, "active": False}
            state.append(target)
        target["powerweekday"] = json.dumps(body["powers"][0])
        target["powerweekend"] = json.dumps(body["powers"][1])

    async def activate(device, name, stamp, body):
        for profile in state:
            profile["active"] = profile["name"] == name

    async def delete(device, name, stamp):
        assert stamp == baseline["updateAt"]
        state[:] = [p for p in state if p["name"] != name]

    runtime.client.async_save_personal_power_profile.side_effect = save
    runtime.client.async_activate_personal_power_profile = AsyncMock(
        side_effect=activate
    )
    runtime.client.async_delete_personal_power_profile = AsyncMock(side_effect=delete)
    entries = [
        {
            "group": group,
            "source": 0,
            "values": {"power_value": "11.9"} if group == 0 else {},
        }
        for group in (0, 1)
    ]
    await async_manage_profile(
        coordinator,
        action,
        "test",
        profile_revision(baseline),
        new_name="copy" if action == "create" else None,
        entries=entries if action in ("create", "edit") else None,
    )
    assert coordinator.data == state
    if action in ("create", "edit"):
        target = next(
            p for p in state if p["name"] == ("copy" if action == "create" else "test")
        )
        assert json.loads(target["powerweekday"])["tram"][0]["power"] == 119
        assert target["active"] is False
        assert json.loads(target["powerweekday"])["tram"][0]["future"] == [None, False]
        runtime.client.async_activate_personal_power_profile.assert_not_called()
    elif action == "activate":
        assert state[0]["active"] is True
        assert state[0]["powerweekday"] == baseline["powerweekday"]
        runtime.client.async_save_personal_power_profile.assert_not_called()
    else:
        assert not state


async def test_active_profile_edit_requires_explicit_confirmation(panel):
    from custom_components.v2c_cloud.power_profiles import (
        InvalidPowerProfilesError,
        async_manage_profile,
    )

    _hass, runtime, coordinator, state, _connection, _msg = panel
    state[0]["active"] = True
    coordinator.async_set_updated_data(deepcopy(state))
    with pytest.raises(InvalidPowerProfilesError, match="confirmation"):
        await async_manage_profile(
            coordinator,
            "edit",
            "test",
            profile_revision(state[0]),
            entries=[{"group": g, "source": 0, "values": {}} for g in (0, 1)],
        )
    runtime.client.async_save_personal_power_profile.assert_not_called()


def test_full_editor_preserves_phases_and_rejects_overlap(panel):
    from custom_components.v2c_cloud.power_profiles import (
        InvalidPowerProfilesError,
        profile_edit_body,
    )

    profile = panel[3][0]
    entries = [{"group": group, "source": 0, "values": {}} for group in (0, 1)]
    body = profile_edit_body(profile, entries)
    assert body["powers"][0]["tram"][0]["intensity"] == {"L1": None}
    assert body["powers"][0]["tram"][0]["future"] == [None, False]
    with pytest.raises(InvalidPowerProfilesError, match="overlapping"):
        profile_edit_body(profile, [*entries, entries[0]])


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
async def test_management_http_success_without_persistence_is_not_success(
    panel, action
):
    from custom_components.v2c_cloud.power_profiles import async_manage_profile

    _hass, runtime, coordinator, state, _connection, _msg = panel
    runtime.client.async_save_personal_power_profile.side_effect = None
    runtime.client.async_delete_personal_power_profile = AsyncMock(return_value="OK")
    entries = [
        {"group": g, "source": 0, "values": {"power_value": "11.9"}} for g in (0, 1)
    ]
    with pytest.raises(PowerProfileSaveUnconfirmedError):
        await async_manage_profile(
            coordinator,
            action,
            "test",
            profile_revision(state[0]),
            new_name="copy" if action == "create" else None,
            entries=entries if action != "delete" else None,
        )
    assert not coordinator.last_update_success


@pytest.mark.parametrize("mode", [0, 2])
async def test_active_profile_battery_autosave_preserves_schedule_and_activation(
    panel, mode
):
    hass, runtime, coordinator, state, connection, msg = panel
    state[0]["active"] = True
    schedule = json.loads(state[0]["powerweekday"])
    schedule["tram"][0]["charge_fv_mode"] = mode
    state[0]["powerweekday"] = json.dumps(schedule)
    await coordinator.async_refresh()
    before = deepcopy(state[0])
    entity = V2CProfileBatterySwitch(
        coordinator, next(iter(profile_battery_slots(state[0]))), {}, "Weekdays"
    )
    assert entity.available
    assert entity._attr_entity_registry_enabled_default is False
    await profile_panel.websocket_profiles(hass, connection, msg)
    assert connection.send_result.call_args.args[1][0]["editable"] is True
    await entity.async_turn_off()
    assert entity.is_on is False
    assert state[0]["active"] is True
    weekday = json.loads(before["powerweekday"])
    weekday["tram"][0]["bat_mode"] = 1
    assert json.loads(state[0]["powerweekday"]) == weekday
    assert state[0]["powerweekend"] == before["powerweekend"]
    runtime.client.async_activate_personal_power_profile.assert_not_called()


async def test_panel_option_hides_only_when_all_entries_opt_out(panel, monkeypatch):
    hass, runtime, _coordinator, _state, _connection, _msg = panel
    register, remove = AsyncMock(), MagicMock()
    monkeypatch.setattr(profile_panel.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(profile_panel.frontend, "async_remove_panel", remove)
    runtime.show_profile_panel = False
    await profile_panel.async_setup_profile_panel(hass)
    register.assert_not_called()
    runtime.show_profile_panel = True
    await profile_panel.async_setup_profile_panel(hass)
    register.assert_awaited_once()
    other = SimpleNamespace(
        profile_coordinators={"other": object()}, show_profile_panel=True
    )
    hass.data["v2c_cloud"]["other"] = other
    runtime.show_profile_panel = False
    profile_panel.async_remove_profile_panel(hass)
    remove.assert_not_called()
    other.show_profile_panel = False
    profile_panel.async_remove_profile_panel(hass)
    remove.assert_called_once()
    runtime.show_profile_panel = True
    await profile_panel.async_setup_profile_panel(hass)
    assert register.await_count == 2
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_active_profile_select_uses_activation_and_confirmed_readback(panel):
    from custom_components.v2c_cloud.select import V2CActiveProfileSelect

    _hass, runtime, coordinator, state, _connection, _msg = panel
    state[0]["active"] = True
    state.append({**deepcopy(state[0]), "name": "Other", "active": False})
    await coordinator.async_refresh()
    entity = V2CActiveProfileSelect(coordinator, {})
    assert entity.options == ["test", "Other"]
    assert entity.current_option == "test"

    async def activate(device, name, stamp, payload):
        for profile in state:
            profile["active"] = profile["name"] == name

    runtime.client.async_activate_personal_power_profile = AsyncMock(
        side_effect=activate
    )
    before = deepcopy(state)
    await entity.async_select_option("Other")
    assert entity.current_option == "Other"
    runtime.client.async_activate_personal_power_profile.assert_awaited_once()
    runtime.client.async_save_personal_power_profile.assert_not_called()
    assert [p["powerweekday"] for p in state] == [p["powerweekday"] for p in before]
    await entity.async_select_option("Other")
    runtime.client.async_activate_personal_power_profile.assert_awaited_once()


@pytest.mark.parametrize("failure", ["cloud", "ambiguous", "missing", "unconfirmed"])
async def test_active_profile_select_rejects_invalid_or_unconfirmed_target(
    panel, failure
):
    from custom_components.v2c_cloud.select import V2CActiveProfileSelect

    _hass, runtime, coordinator, state, _connection, _msg = panel
    state[0]["active"] = True
    state.append(
        {**deepcopy(state[0]), "name": "Other", "active": failure == "ambiguous"}
    )
    await coordinator.async_refresh()
    entity = V2CActiveProfileSelect(coordinator, {})
    if failure == "cloud":
        runtime.cloud_commands_available = False
    if failure == "unconfirmed":
        runtime.client.async_activate_personal_power_profile = AsyncMock(
            return_value={}
        )
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("absent" if failure == "missing" else "Other")
    assert entity.current_option == "test" or failure == "ambiguous"
    if failure != "unconfirmed":
        runtime.client.async_activate_personal_power_profile.assert_not_called()
    else:
        assert not entity.available


async def test_panel_visibility_updates_live_for_cloud_only_entry(panel, monkeypatch):
    from custom_components.v2c_cloud import V2CEntryRuntimeData, _async_options_updated

    hass, original, coordinator, _state, _connection, _msg = panel
    runtime = V2CEntryRuntimeData(
        client=original.client,
        coordinator=original.coordinator,
        cloud_only=True,
        profile_coordinators={"device": coordinator},
    )
    hass.data["v2c_cloud"]["entry"] = runtime
    register, remove = AsyncMock(), MagicMock()
    monkeypatch.setattr(profile_panel.panel_custom, "async_register_panel", register)
    monkeypatch.setattr(profile_panel.frontend, "async_remove_panel", remove)
    entry = SimpleNamespace(
        entry_id="entry",
        data={"cloud_only": True},
        options={"show_profile_panel": False},
    )
    await profile_panel.async_setup_profile_panel(hass)
    await _async_options_updated(hass, entry)
    assert runtime.show_profile_panel is False
    remove.assert_called_once()
    entry.options["show_profile_panel"] = True
    await _async_options_updated(hass, entry)
    assert runtime.show_profile_panel is True
    assert register.await_count == 2
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.parametrize("watts", ["0", "0.125", "1234.5", "10000"])
async def test_isolated_discharge_uses_distinct_watts_field_and_preserves_other_data(
    panel, watts
):
    from decimal import Decimal

    from custom_components.v2c_cloud.power_profiles import async_manage_profile

    _hass, runtime, coordinator, state, _connection, _msg = panel
    runtime.coordinator.data["devices"]["device"]["pairing"]["modelName"] = "Trydan Pro"
    before = deepcopy(state[0])
    entries = [
        {"group": 0, "source": 0, "values": {"mode": 4, "battery_discharge_w": watts}},
        {"group": 1, "source": 0, "values": {}},
    ]
    await async_manage_profile(
        coordinator, "edit", "test", profile_revision(before), entries=entries
    )
    expected = json.loads(before["powerweekday"])
    expected["tram"][0].update(charge_fv_mode=4, power=float(Decimal(watts) / 100))
    assert json.loads(state[0]["powerweekday"]) == expected
    assert state[0]["powerweekend"] == before["powerweekend"]
    assert state[0]["active"] is False
    runtime.client.async_activate_personal_power_profile.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"mode": 4},
        {"mode": 4, "power_value": "200"},
        {"mode": 4, "battery_discharge_w": "-1"},
        {"mode": 4, "battery_discharge_w": "10000.01"},
        {"mode": 4, "battery_discharge_w": "NaN"},
        {"mode": 4, "battery_discharge_w": True},
        {"mode": 4, "battery_discharge_w": "100", "power_value": "1"},
        {"battery_discharge_w": "100"},
        {"mode": 1, "power_value": "0", "battery_discharge_w": "100"},
    ],
)
async def test_invalid_or_confused_isolated_fields_are_rejected_before_write(
    panel, values
):
    from custom_components.v2c_cloud.power_profiles import (
        InvalidPowerProfilesError,
        async_manage_profile,
    )

    _hass, runtime, coordinator, state, _connection, _msg = panel
    runtime.coordinator.data["devices"]["device"]["pairing"]["modelName"] = "Trydan"
    entries = [
        {"group": group, "source": 0, "values": values if group == 0 else {}}
        for group in (0, 1)
    ]
    with pytest.raises(InvalidPowerProfilesError):
        await async_manage_profile(
            coordinator, "edit", "test", profile_revision(state[0]), entries=entries
        )
    runtime.client.async_save_personal_power_profile.assert_not_called()


@pytest.mark.parametrize("model", [None, "Trydan", "Trydan Pro", "Pole Pro"])
async def test_isolated_mode_hardware_availability_is_reported_and_enforced(
    panel, model
):
    from custom_components.v2c_cloud.power_profiles import (
        InvalidPowerProfilesError,
        async_manage_profile,
    )

    hass, runtime, coordinator, state, connection, msg = panel
    if model is not None:
        runtime.coordinator.data["devices"]["device"]["pairing"]["modelName"] = model
    await profile_panel.websocket_profiles(hass, connection, msg)
    assert connection.send_result.call_args.args[1][0]["supports_isolated"] is (
        model in ("Trydan", "Trydan Pro")
    )
    if model in (None, "Pole Pro"):
        entries = [
            {
                "group": group,
                "source": 0,
                "values": {"mode": 4, "battery_discharge_w": "200"}
                if group == 0
                else {},
            }
            for group in (0, 1)
        ]
        with pytest.raises(InvalidPowerProfilesError, match="Trydan"):
            await async_manage_profile(
                coordinator, "edit", "test", profile_revision(state[0]), entries=entries
            )
        runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_existing_isolated_schedule_can_be_edited_when_model_unknown(panel):
    from custom_components.v2c_cloud.power_profiles import async_manage_profile

    _hass, _runtime, coordinator, state, _connection, _msg = panel
    weekday = json.loads(state[0]["powerweekday"])
    weekday["tram"][0].update(charge_fv_mode=4, power=2)
    state[0]["powerweekday"] = json.dumps(weekday)
    await coordinator.async_refresh()
    entries = [
        {
            "group": group,
            "source": 0,
            "values": {"battery_discharge_w": "300"} if group == 0 else {},
        }
        for group in (0, 1)
    ]
    await async_manage_profile(
        coordinator, "edit", "test", profile_revision(state[0]), entries=entries
    )
    assert json.loads(state[0]["powerweekday"])["tram"][0]["power"] == 3


@pytest.mark.parametrize(
    ("ha_name", "cloud_name", "registered_name", "expected"),
    [
        ("Borne maison", "Cloud charger", "Device name", "Borne maison"),
        (None, "Cloud charger", "Device name", "Cloud charger"),
        ("   ", " Cloud charger ", "Device name", "Cloud charger"),
        (None, None, "Device name", "Device name"),
        (None, None, None, "device"),
        (None, {"unexpected": "value"}, False, "device"),
    ],
)
async def test_panel_charger_name_prefers_user_name_then_cloud_and_registry(
    panel, monkeypatch, *, ha_name, cloud_name, registered_name, expected
):
    hass, runtime, _coordinator, _state, connection, msg = panel
    runtime.coordinator.data["devices"]["device"]["pairing"]["tag"] = cloud_name
    device = SimpleNamespace(name_by_user=ha_name, name=registered_name)
    registry = SimpleNamespace(async_get_device=MagicMock(return_value=device))
    monkeypatch.setattr(
        profile_panel.dr, "async_get", lambda _: registry, raising=False
    )
    await profile_panel.websocket_devices(hass, connection, msg)
    assert connection.send_result.call_args.args[1] == [
        {"entry_id": "entry", "device_id": "device", "name": expected}
    ]
    registry.async_get_device.assert_called_once_with(
        identifiers={("v2c_cloud", "device")}
    )
    runtime.client.async_list_personal_power_profiles.assert_not_called()
    runtime.client.async_save_personal_power_profile.assert_not_called()


async def test_panel_charger_name_reads_account_pairing_and_handles_absent_registry_device(
    panel, monkeypatch
):
    hass, runtime, _coordinator, _state, connection, msg = panel
    runtime.coordinator.data["devices"]["device"]["pairing"] = {}
    runtime.coordinator.data["pairings"] = [
        {"deviceId": "other", "tag": "Other charger"},
        {"deviceId": "device", "tag": "Garage"},
    ]
    registry = SimpleNamespace(async_get_device=MagicMock(return_value=None))
    monkeypatch.setattr(
        profile_panel.dr, "async_get", lambda _: registry, raising=False
    )
    await profile_panel.websocket_devices(hass, connection, msg)
    assert connection.send_result.call_args.args[1][0]["name"] == "Garage"
    assert connection.send_result.call_args.args[1][0]["device_id"] == "device"
