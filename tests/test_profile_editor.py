"""Battery edits must preserve complete profiles and confirm actual Cloud state."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.v2c_cloud.power_profiles import (
    InvalidPowerProfilesError,
    PowerProfileConflictError,
    PowerProfileCoordinator,
    PowerProfileSaveUnconfirmedError,
    battery_permission_intervals,
    profile_edit_body,
    profile_revision,
)
from custom_components.v2c_cloud.v2c_cloud import V2CRequestError


@pytest.fixture
def cloud():
    def schedule(group):
        return json.dumps(
            {
                "type": group,
                "extension": {"opaque": [None, False, 0.5]},
                "tram": [
                    {
                        "hourStart": 0,
                        "hourEnd": 9,
                        "charge_fv_mode": 2,
                        "bat_mode": 0,
                        "power": 120.0,
                        "intensity": {"L1": None, "L2": 16, "L3": None, "extra": 0.25},
                        "future": {"preserve": True},
                    },
                    {
                        "hourStart": 9,
                        "hourEnd": 19,
                        "charge_fv_mode": 1,
                        "bat_prio": 0,
                        "power": -2.005,
                    },
                    {
                        "hourStart": 19,
                        "hourEnd": 24,
                        "charge_fv_mode": 2,
                        "bat_mode": 1,
                        "power": 120.0,
                    },
                ],
            }
        )

    profile = {
        "deviceId": "dev-1",
        "name": "draft",
        "active": False,
        "updateAt": "2026-11-09T12:00:00.000+00:00",
        "powerweekday": schedule(0),
        "powerweekend": schedule(1),
    }
    active = deepcopy(profile)
    active.update(name="normal", active=True)
    state = [active, profile]
    client = MagicMock()
    client.async_list_personal_power_profiles = AsyncMock(
        side_effect=lambda _: deepcopy(state)
    )

    async def save(device, name, updated, body):
        assert device == "dev-1"
        assert name == "draft"
        assert updated.isdecimal()
        assert len(updated) == 13
        await asyncio.sleep(0)
        target = next(p for p in state if p["name"] == name)
        target["powerweekday"] = json.dumps(body["powers"][0])
        target["powerweekend"] = json.dumps(body["powers"][1])
        for item in state:
            item["updateAt"] = "2026-11-09T13:00:00.000+00:00"
        return ""

    client.async_save_personal_power_profile = AsyncMock(side_effect=save)
    runtime = SimpleNamespace(
        client=client,
        profile_lock=asyncio.Lock(),
        cloud_commands_available=True,
        coordinator=MagicMock(data={"devices": {}}),
    )
    coordinator = PowerProfileCoordinator(MagicMock(), runtime, "dev-1")
    coordinator.async_set_updated_data(deepcopy(state))
    return client, state, deepcopy(profile), coordinator


async def _save(coordinator, baseline, interval, *, allowed):
    await coordinator.async_save(
        baseline["name"], profile_revision(baseline), interval, allowed=allowed
    )
    return coordinator.data


def _entries(baseline, interval, *, allowed):
    return [
        {
            "group": group,
            "source": source,
            "values": {"allow_battery": allowed} if (group, source) == interval else {},
        }
        for group, field in enumerate(("powerweekday", "powerweekend"))
        for source, _item in enumerate(json.loads(baseline[field])["tram"])
    ]


def test_draft_changes_only_the_selected_battery_field(cloud):
    _client, _state, baseline, _coordinator = cloud
    original = deepcopy(baseline)
    body = profile_edit_body(baseline, _entries(baseline, (1, 0), allowed=False))
    expected = [json.loads(baseline[k]) for k in ("powerweekday", "powerweekend")]
    expected[1]["tram"][0]["bat_mode"] = 1
    assert body == {"powers": expected}
    assert baseline == original
    assert battery_permission_intervals(baseline) == [(0, 0), (0, 2), (1, 0), (1, 2)]


@pytest.mark.parametrize("active", [None, 0, "false"])
def test_invalid_activation_metadata_disables_edits(cloud, active):
    baseline = cloud[2]
    baseline["active"] = active
    assert battery_permission_intervals(baseline) == []
    with pytest.raises(InvalidPowerProfilesError):
        profile_edit_body(baseline, _entries(baseline, (0, 0), allowed=False))


@pytest.mark.parametrize("value", [None, True, "0", 2])
def test_unrecognised_battery_values_are_not_replaced(cloud, value):
    baseline = cloud[2]
    group = json.loads(baseline["powerweekday"])
    group["tram"][0]["bat_mode"] = value
    baseline["powerweekday"] = json.dumps(group)
    assert (0, 0) not in battery_permission_intervals(baseline)


@pytest.mark.parametrize("mode", [1, 3, 4, "2", True])
def test_non_permission_modes_have_no_battery_switch(cloud, mode):
    baseline = cloud[2]
    group = json.loads(baseline["powerweekday"])
    group["tram"][0]["charge_fv_mode"] = mode
    baseline["powerweekday"] = json.dumps(group)
    assert (0, 0) not in battery_permission_intervals(baseline)


@pytest.mark.parametrize(
    "schedule",
    [
        "broken",
        "[]",
        '{"type":true,"tram":[]}',
        '{"type":0,"tram":[null]}',
        '{"type":0,"tram":[],"extra":NaN}',
        {"type": 0, "tram": []},
    ],
)
def test_malformed_schedules_disable_all_writes(cloud, schedule):
    baseline = cloud[2]
    baseline["powerweekend"] = schedule
    assert battery_permission_intervals(baseline) == []


def test_unknown_record_metadata_is_kept_read_only(cloud):
    baseline = cloud[2]
    baseline["future_metadata"] = {"keep": True}
    assert battery_permission_intervals(baseline) == []
    assert baseline["future_metadata"] == {"keep": True}


async def test_save_readback_preserves_all_fields_and_activation(cloud):
    client, state, baseline, coordinator = cloud
    original = deepcopy(state)
    result = await _save(coordinator, baseline, (1, 0), allowed=False)
    assert result == state
    expected = deepcopy(original)
    schedule = json.loads(expected[1]["powerweekend"])
    schedule["tram"][0]["bat_mode"] = 1
    expected[1]["powerweekend"] = json.dumps(schedule)
    for profile in expected:
        profile["updateAt"] = state[0]["updateAt"]
    assert state == expected
    assert baseline == original[1]
    client.async_save_personal_power_profile.assert_awaited_once()
    assert client.async_list_personal_power_profiles.await_count == 2
    client.async_update_personal_power_profile.assert_not_called()
    client.async_cloud_start_charge.assert_not_called()


@pytest.mark.parametrize(
    "change", ["content", "active", "timestamp", "duplicate", "deleted"]
)
async def test_stale_or_ambiguous_target_aborts_before_post(cloud, change):
    client, state, baseline, coordinator = cloud
    if change == "content":
        state[1]["powerweekday"] = state[1]["powerweekday"].replace("120.0", "121.0")
    elif change == "active":
        state[1]["active"] = True
    elif change == "timestamp":
        state[1]["updateAt"] = "different"
    elif change == "duplicate":
        state.append(deepcopy(state[1]))
    else:
        state.pop()
    with pytest.raises(PowerProfileConflictError):
        await _save(coordinator, baseline, (0, 0), allowed=False)
    client.async_save_personal_power_profile.assert_not_called()


async def test_unchanged_setting_does_not_send_a_post(cloud):
    client, _state, baseline, coordinator = cloud
    await _save(coordinator, baseline, (0, 0), allowed=True)
    client.async_save_personal_power_profile.assert_not_called()
    client.async_list_personal_power_profiles.assert_awaited_once()


async def test_http_success_is_insufficient_without_persistence(cloud):
    client, _state, baseline, coordinator = cloud
    client.async_save_personal_power_profile.side_effect = None
    client.async_save_personal_power_profile.return_value = (
        "Command executed successfully"
    )
    with pytest.raises(PowerProfileSaveUnconfirmedError):
        await _save(coordinator, baseline, (0, 0), allowed=False)
    client.async_save_personal_power_profile.assert_awaited_once()


@pytest.mark.parametrize("persisted", [False, True])
async def test_lost_write_response_is_read_back_without_retry(cloud, persisted):
    client, state, baseline, coordinator = cloud
    save = client.async_save_personal_power_profile.side_effect

    async def timeout(*args):
        if persisted:
            await save(*args)
        raise V2CRequestError("Timeout")

    client.async_save_personal_power_profile.side_effect = timeout
    if persisted:
        assert await _save(coordinator, baseline, (0, 0), allowed=False) == state
    else:
        with pytest.raises(PowerProfileSaveUnconfirmedError):
            await _save(coordinator, baseline, (0, 0), allowed=False)
    client.async_save_personal_power_profile.assert_awaited_once()
    assert client.async_list_personal_power_profiles.await_count == 2


@pytest.mark.parametrize("change", ["activation", "power", "unknown", "new_profile"])
async def test_unexpected_server_changes_are_never_reported_as_success(cloud, change):
    client, state, baseline, coordinator = cloud
    save = client.async_save_personal_power_profile.side_effect

    async def save_unexpected(*args):
        await save(*args)
        if change == "activation":
            state[0]["active"] = False
            state[1]["active"] = True
        elif change == "power":
            state[0]["powerweekday"] = state[0]["powerweekday"].replace(
                "120.0", "999.0"
            )
        elif change == "unknown":
            state[0]["powers"] = "new record-level field"
        else:
            state.append({**state[0], "name": "unexpected"})

    client.async_save_personal_power_profile.side_effect = save_unexpected
    with pytest.raises(PowerProfileSaveUnconfirmedError):
        await _save(coordinator, baseline, (0, 0), allowed=False)
    # No guessed rollback and no second POST after an unexpected change.
    client.async_save_personal_power_profile.assert_awaited_once()


async def test_failed_readback_is_an_uncertain_write(cloud):
    client, state, baseline, coordinator = cloud
    client.async_list_personal_power_profiles.side_effect = [
        deepcopy(state),
        V2CRequestError("offline"),
    ]
    with pytest.raises(PowerProfileSaveUnconfirmedError):
        await _save(coordinator, baseline, (0, 0), allowed=False)
    client.async_save_personal_power_profile.assert_awaited_once()


async def test_simultaneous_editor_saves_are_serialised(cloud):
    client, _state, baseline, coordinator = cloud
    results = await asyncio.gather(
        _save(coordinator, baseline, (0, 0), allowed=False),
        _save(coordinator, baseline, (1, 0), allowed=False),
        return_exceptions=True,
    )
    assert isinstance(results[0], list)
    assert isinstance(results[1], PowerProfileConflictError)
    client.async_save_personal_power_profile.assert_awaited_once()


def _native_payload(baseline):
    return {
        "powers": [
            json.loads(baseline[field]) for field in ("powerweekday", "powerweekend")
        ]
    }


@pytest.mark.parametrize("active", [False, True])
async def test_existing_update_service_keeps_fields_and_saves_without_activation(
    cloud, active
):
    from custom_components.v2c_cloud import (
        V2CEntryRuntimeData,
        _async_register_services,
    )

    client, state, baseline, coordinator = cloud
    state[0]["active"] = not active
    state[1]["active"] = active
    telemetry = MagicMock(data={"devices": {"dev-1": {}}})
    telemetry.async_request_refresh = AsyncMock()
    runtime = V2CEntryRuntimeData(client=client, coordinator=telemetry)
    runtime.profile_coordinators["dev-1"] = coordinator
    coordinator.runtime = runtime
    hass = MagicMock()
    hass.data = {"v2c_cloud": {"entry": runtime}}
    hass.services.has_service.return_value = False
    _async_register_services(hass)
    registration = next(
        call
        for call in hass.services.async_register.call_args_list
        if call.args[1] == "update_power_profile"
    )
    payload = _native_payload(baseline)
    payload["powers"][0]["tram"][0]["power"] = 119
    original = deepcopy(payload)
    data = {
        "device_id": "dev-1",
        "name": "draft",
        "updated_at": baseline["updateAt"],
        "profile": payload,
    }
    validated = registration.kwargs["schema"](data)
    assert validated == data
    await registration.args[2](SimpleNamespace(data=validated))
    call = client.async_save_personal_power_profile.await_args
    assert call.args[:2] == ("dev-1", "draft")
    assert call.args[2].isdecimal()
    assert len(call.args[2]) == 13
    assert call.args[3] == original
    assert payload == original
    assert json.loads(state[1]["powerweekday"])["tram"][0]["power"] == 119
    assert state[0]["active"] is not active
    assert state[1]["active"] is active
    assert coordinator.data == state
    client.async_activate_personal_power_profile.assert_not_called()
    telemetry.async_request_refresh.assert_awaited_once()


async def test_service_update_preserves_omitted_extension_fields_and_raw_units(cloud):
    client, state, baseline, coordinator = cloud
    payload = _native_payload(baseline)
    weekday = payload["powers"][0]
    weekday.pop("extension")
    first = weekday["tram"][0]
    first.pop("future")
    first["intensity"] = {"L1": 12}
    first["bat_mode"] = 1
    original = deepcopy(payload)
    await coordinator.async_update_payload("draft", payload)
    actual = json.loads(state[1]["powerweekday"])
    expected = json.loads(baseline["powerweekday"])
    expected["tram"][0]["intensity"]["L1"] = 12
    expected["tram"][0]["bat_mode"] = 1
    assert actual == expected
    assert state[1]["powerweekend"] == baseline["powerweekend"]
    assert payload == original
    client.async_save_personal_power_profile.assert_awaited_once()


@pytest.mark.parametrize(
    "invalid", ["missing", "one_day", "wrong_type", "empty_day", "overlap", "nan"]
)
async def test_invalid_service_payload_never_sends_a_write(cloud, invalid):
    client, _state, baseline, coordinator = cloud
    payload = _native_payload(baseline)
    if invalid == "missing":
        payload = {"mode": 2, "value": 120}
    elif invalid == "one_day":
        payload["powers"].pop()
    elif invalid == "wrong_type":
        payload["powers"][1]["type"] = 0
    elif invalid == "empty_day":
        payload["powers"][0]["tram"] = []
    elif invalid == "overlap":
        payload["powers"][0]["tram"][1]["hourStart"] = 8
    else:
        payload["powers"][0]["tram"][0]["power"] = float("nan")
    with pytest.raises(InvalidPowerProfilesError):
        await coordinator.async_update_payload("draft", payload)
    client.async_save_personal_power_profile.assert_not_called()
    client.async_activate_personal_power_profile.assert_not_called()


async def test_service_update_detects_concurrent_change_before_writing(cloud):
    client, state, baseline, coordinator = cloud
    payload = _native_payload(baseline)
    payload["powers"][0]["tram"][0]["power"] = 119
    changed = deepcopy(state)
    changed[1]["updateAt"] = "concurrent change"
    client.async_list_personal_power_profiles.side_effect = [deepcopy(state), changed]
    with pytest.raises(PowerProfileConflictError):
        await coordinator.async_update_payload("draft", payload)
    client.async_save_personal_power_profile.assert_not_called()


async def test_service_update_requires_confirmed_persistence(cloud):
    client, _state, baseline, coordinator = cloud
    payload = _native_payload(baseline)
    payload["powers"][0]["tram"][0]["power"] = 119
    client.async_save_personal_power_profile.side_effect = None
    with pytest.raises(PowerProfileSaveUnconfirmedError):
        await coordinator.async_update_payload("draft", payload)
    client.async_save_personal_power_profile.assert_awaited_once()
    assert not coordinator.last_update_success
