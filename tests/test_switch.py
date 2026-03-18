"""Tests for V2CBooleanSwitch entity logic."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_switch(
    *,
    local_keys=("Dynamic",),
    local_value=None,
    reported_value=None,
    icon_on="mdi:flash",
    icon_off="mdi:flash-off",
):
    from custom_components.v2c_cloud.switch import V2CBooleanSwitch

    # Build fake local data
    local_data = {}
    if local_value is not None:
        local_data = {"Dynamic": local_value}

    # Build coordinator data
    reported = {}
    reported_lower = {}
    if reported_value is not None:
        reported = {"dynamic": reported_value}
        reported_lower = {"dynamic": reported_value}

    coord = MagicMock()
    coord.data = {
        "devices": {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": reported,
                "additional": {"reported_lower": reported_lower, "static_ip": "192.168.1.1"},
            }
        },
        "pairings": [{"deviceId": "dev-1"}],
    }
    coord.last_update_success = True

    runtime_data = MagicMock()
    runtime_data.coordinator = coord
    if local_data:
        local_coord = MagicMock()
        local_coord.data = {"Dynamic": local_value, "_lower_index": {"dynamic": "Dynamic"}}
        local_coord.last_update_success = True
        runtime_data.local_coordinators = {"dev-1": local_coord}
    else:
        runtime_data.local_coordinators = {}

    client = MagicMock()
    setter = AsyncMock()

    switch = V2CBooleanSwitch(
        coord,
        client,
        runtime_data,
        "dev-1",
        name_key="dynamic_mode",
        unique_suffix="dynamic",
        setter=setter,
        reported_keys=("dynamic",),
        local_keys=local_keys,
        icon_on=icon_on,
        icon_off=icon_off,
        refresh_after_call=False,
        trigger_local_refresh=False,
    )
    return switch, setter


class TestV2CBooleanSwitchIsOn:
    """Tests for V2CBooleanSwitch.is_on state resolution."""

    def test_returns_true_from_local_data(self):
        switch, _ = _make_switch(local_value=1)
        assert switch.is_on is True

    def test_returns_false_from_local_data(self):
        switch, _ = _make_switch(local_value=0)
        assert switch.is_on is False

    def test_falls_back_to_reported_when_no_local_keys(self):
        switch, _ = _make_switch(local_keys=(), reported_value=True)
        assert switch.is_on is True

    def test_falls_back_to_reported_false(self):
        switch, _ = _make_switch(local_keys=(), reported_value=False)
        assert switch.is_on is False

    def test_returns_false_when_no_data_at_all(self):
        switch, _ = _make_switch(local_keys=(), reported_value=None)
        assert switch.is_on is False

    def test_optimistic_state_held_during_window(self):
        switch, _ = _make_switch(local_keys=())
        switch._optimistic_state = True
        switch._record_command()  # start hold window
        # No real reported data, so optimistic state is returned
        assert switch.is_on is True

    def test_icon_set_on_for_true(self):
        switch, _ = _make_switch(local_value=1, icon_on="mdi:flash", icon_off="mdi:flash-off")
        _ = switch.is_on
        assert switch._attr_icon == "mdi:flash"

    def test_icon_set_off_for_false(self):
        switch, _ = _make_switch(local_value=0, icon_on="mdi:flash", icon_off="mdi:flash-off")
        _ = switch.is_on
        assert switch._attr_icon == "mdi:flash-off"


class TestV2CBooleanSwitchOptimisticHold:
    """Tests for optimistic state hold during cloud-lag window."""

    def test_local_value_clears_hold_when_matches_optimistic(self):
        switch, _ = _make_switch(local_value=1)
        switch._optimistic_state = True
        switch._record_command()
        # Local and optimistic agree → hold cleared, real value returned
        result = switch.is_on
        assert result is True
        assert switch._is_within_hold() is False

    def test_local_value_maintains_hold_when_differs(self):
        switch, _ = _make_switch(local_value=0)
        switch._optimistic_state = True
        switch._record_command()
        # Local says 0 but optimistic says True → hold maintained
        result = switch.is_on
        assert result is True

    def test_unique_id(self):
        switch, _ = _make_switch()
        assert switch._attr_unique_id == "v2c_dev-1_dynamic"


class TestV2CBooleanSwitchAvailability:
    """Tests for availability property."""

    def test_available_from_local_coordinator(self):
        switch, _ = _make_switch(local_value=1)
        # local_coordinator is set when local_keys is non-empty
        # The switch creates _local_coordinator=None initially,
        # it's set in async_added_to_hass — test without it:
        switch._local_coordinator = MagicMock()
        switch._local_coordinator.last_update_success = True
        assert switch.available is True

    def test_unavailable_when_local_coord_fails(self):
        switch, _ = _make_switch(local_value=1)
        switch._local_coordinator = MagicMock()
        switch._local_coordinator.last_update_success = False
        assert switch.available is False

    def test_available_from_cloud_coordinator(self):
        switch, _ = _make_switch()
        switch._local_coordinator = None
        switch.coordinator.last_update_success = True
        assert switch.available is True
