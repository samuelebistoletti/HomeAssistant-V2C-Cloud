"""Tests for V2CNumberEntity logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_number(
    *,
    local_key="Intensity",
    reported_keys=("intensity",),
    local_value=None,
    reported_value=None,
    source_to_native=None,
    value_to_api=None,
):
    from custom_components.v2c_cloud.number import V2CNumberEntity

    reported_lower = {}
    reported = {}
    if reported_value is not None:
        reported = {"intensity": reported_value}
        reported_lower = {"intensity": reported_value}

    coord = MagicMock()
    coord.data = {
        "devices": {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": reported,
                "additional": {
                    "reported_lower": reported_lower,
                    "static_ip": "192.168.1.1",
                },
            }
        },
        "pairings": [{"deviceId": "dev-1"}],
    }
    coord.last_update_success = True

    runtime_data = MagicMock()
    runtime_data.coordinator = coord

    if local_value is not None:
        local_coord = MagicMock()
        local_coord.data = {
            local_key: local_value,
            "_lower_index": {local_key.lower(): local_key},
        }
        local_coord.last_update_success = True
        runtime_data.local_coordinators = {"dev-1": local_coord}
    else:
        runtime_data.local_coordinators = {}

    client = MagicMock()
    setter = AsyncMock()

    kwargs = dict(
        name_key="current_intensity",
        unique_suffix="intensity",
        reported_keys=reported_keys,
        setter=setter,
        native_unit="A",
        minimum=6.0,
        maximum=32.0,
        step=1.0,
        local_key=local_key,
        refresh_after_call=False,
    )
    if source_to_native is not None:
        kwargs["source_to_native"] = source_to_native
    if value_to_api is not None:
        kwargs["value_to_api"] = value_to_api

    number = V2CNumberEntity(coord, client, runtime_data, "dev-1", **kwargs)
    return number, setter


class TestV2CNumberEntityNativeValue:
    """Tests for V2CNumberEntity.native_value."""

    def test_returns_local_value(self):
        number, _ = _make_number(local_value=16)
        assert number.native_value == pytest.approx(16.0)

    def test_returns_none_when_no_data(self):
        number, _ = _make_number(local_value=None)
        assert number.native_value is None

    def test_applies_source_to_native(self):
        number, _ = _make_number(local_value=3000, source_to_native=lambda v: v / 1000)
        assert number.native_value == pytest.approx(3.0)

    def test_optimistic_value_returned_when_hold_active(self):
        number, _ = _make_number(local_value=16)
        number._optimistic_value = 20.0
        number._record_command()
        # Local is 16, optimistic is 20 — should hold optimistic
        result = number.native_value
        assert result == pytest.approx(20.0)

    def test_real_value_clears_hold_when_matches(self):
        number, _ = _make_number(local_value=16)
        number._optimistic_value = 16.0
        number._record_command()
        result = number.native_value
        assert result == pytest.approx(16.0)
        # Hold cleared because values match
        assert number._last_command_ts is None

    def test_returns_reported_value_when_no_local_key(self):
        number, _ = _make_number(local_key=None, reported_value=8)
        number._local_key = None
        result = number.native_value
        assert result == pytest.approx(8.0)


class TestShouldHoldValue:
    """Tests for _should_hold_value logic."""

    def test_holds_when_updated_differs_from_optimistic(self):
        number, _ = _make_number()
        number._optimistic_value = 20.0
        number._record_command()
        assert number._should_hold_value(10.0) is True

    def test_does_not_hold_when_no_optimistic(self):
        number, _ = _make_number()
        number._optimistic_value = None
        assert number._should_hold_value(10.0) is False

    def test_does_not_hold_after_expiry(self):
        number, _ = _make_number()
        number._optimistic_value = 20.0
        number._OPTIMISTIC_HOLD_SECONDS = 0.01
        number._record_command()
        import time
        time.sleep(0.02)
        assert number._should_hold_value(10.0) is False


class TestValuesMatch:
    """Tests for _values_match tolerance."""

    def test_exact_match(self):
        number, _ = _make_number()
        assert number._values_match(16.0, 16.0) is True

    def test_within_half_step(self):
        number, _ = _make_number()
        # step=1.0 → tolerance=0.5
        assert number._values_match(16.4, 16.0) is True

    def test_outside_half_step(self):
        number, _ = _make_number()
        assert number._values_match(16.6, 16.0) is False

    def test_zero_step_uses_half_tolerance(self):
        number, _ = _make_number()
        number._attr_native_step = 0
        assert number._values_match(0.4, 0.0) is True
        assert number._values_match(0.6, 0.0) is False


class TestV2CNumberEntityAvailability:
    """Tests for availability property."""

    def test_available_from_local(self):
        number, _ = _make_number()
        number._local_coordinator = MagicMock()
        number._local_coordinator.last_update_success = True
        assert number.available is True

    def test_unavailable_from_local(self):
        number, _ = _make_number()
        number._local_coordinator = MagicMock()
        number._local_coordinator.last_update_success = False
        assert number.available is False

    def test_available_from_cloud(self):
        number, _ = _make_number()
        number._local_coordinator = None
        number.coordinator.last_update_success = True
        assert number.available is True
