"""Tests for entity.py helpers and _OptimisticHoldMixin."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from custom_components.v2c_cloud.entity import (
    _OptimisticHoldMixin,
    build_device_info,
    coerce_bool,
    get_device_state_from_coordinator,
    get_pairing_from_coordinator,
)


# ---------------------------------------------------------------------------
# coerce_bool
# ---------------------------------------------------------------------------


class TestCoerceBool:
    """Tests for entity-layer boolean coercion."""

    @pytest.mark.parametrize("value", [True, 1, 1.0, 2, "1", "true", "True", "TRUE", "on", "yes", "enabled"])
    def test_truthy(self, value):
        assert coerce_bool(value) is True

    @pytest.mark.parametrize("value", [False, 0, 0.0, "0", "false", "False", "FALSE", "off", "no", "disabled"])
    def test_falsy(self, value):
        assert coerce_bool(value) is False

    @pytest.mark.parametrize("value", [None, "maybe", "2", "yes please", [], {}])
    def test_unknown_returns_none(self, value):
        assert coerce_bool(value) is None

    def test_none_returns_none(self):
        assert coerce_bool(None) is None

    def test_strips_whitespace(self):
        assert coerce_bool("  true  ") is True
        assert coerce_bool("  off  ") is False

    def test_bool_true_is_bool(self):
        result = coerce_bool(True)
        assert result is True
        assert isinstance(result, bool)

    def test_bool_false_is_bool(self):
        result = coerce_bool(False)
        assert result is False
        assert isinstance(result, bool)

    def test_int_nonzero_is_true(self):
        assert coerce_bool(42) is True

    def test_float_nonzero_is_true(self):
        assert coerce_bool(0.1) is True

    def test_float_zero_is_false(self):
        assert coerce_bool(0.0) is False


# ---------------------------------------------------------------------------
# get_device_state_from_coordinator
# ---------------------------------------------------------------------------


class TestGetDeviceStateFromCoordinator:
    """Tests for coordinator device-state lookup."""

    def _coordinator(self, data):
        coord = MagicMock()
        coord.data = data
        return coord

    def test_returns_device_state(self):
        coord = self._coordinator({"devices": {"dev-1": {"connected": True}}})
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {"connected": True}

    def test_returns_empty_when_device_missing(self):
        coord = self._coordinator({"devices": {}})
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}

    def test_returns_empty_when_no_devices_key(self):
        coord = self._coordinator({"pairings": []})
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}

    def test_returns_empty_when_coordinator_data_none(self):
        coord = self._coordinator(None)
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}

    def test_returns_empty_when_data_not_dict(self):
        coord = self._coordinator([1, 2, 3])
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}

    def test_returns_empty_when_devices_is_not_dict(self):
        coord = self._coordinator({"devices": "not-a-dict"})
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}

    def test_handles_none_device_entry(self):
        coord = self._coordinator({"devices": {"dev-1": None}})
        state = get_device_state_from_coordinator(coord, "dev-1")
        assert state == {}


# ---------------------------------------------------------------------------
# get_pairing_from_coordinator
# ---------------------------------------------------------------------------


class TestGetPairingFromCoordinator:
    """Tests for pairing lookup from coordinator storage."""

    def _coordinator(self, data):
        coord = MagicMock()
        coord.data = data
        return coord

    def test_returns_pairing_from_device_state(self):
        pairing = {"deviceId": "dev-1", "name": "Charger"}
        coord = self._coordinator({
            "devices": {"dev-1": {"pairing": pairing}},
            "pairings": [],
        })
        result = get_pairing_from_coordinator(coord, "dev-1")
        assert result == pairing

    def test_falls_back_to_pairings_list(self):
        pairing = {"deviceId": "dev-1", "name": "Charger"}
        coord = self._coordinator({
            "devices": {"dev-1": {}},
            "pairings": [pairing],
        })
        result = get_pairing_from_coordinator(coord, "dev-1")
        assert result == pairing

    def test_returns_empty_when_not_found(self):
        coord = self._coordinator({"devices": {}, "pairings": []})
        result = get_pairing_from_coordinator(coord, "dev-1")
        assert result == {}

    def test_accepts_precomputed_device_state(self):
        pairing = {"deviceId": "dev-1"}
        device_state = {"pairing": pairing}
        coord = self._coordinator({"devices": {}, "pairings": []})
        result = get_pairing_from_coordinator(coord, "dev-1", device_state=device_state)
        assert result == pairing

    def test_skips_non_matching_pairings(self):
        pairing_a = {"deviceId": "dev-A"}
        pairing_b = {"deviceId": "dev-B"}
        coord = self._coordinator({
            "devices": {"dev-B": {}},
            "pairings": [pairing_a, pairing_b],
        })
        result = get_pairing_from_coordinator(coord, "dev-B")
        assert result == pairing_b


# ---------------------------------------------------------------------------
# build_device_info
# ---------------------------------------------------------------------------


class TestBuildDeviceInfo:
    """Tests for DeviceInfo construction."""

    def _coordinator(self, data):
        coord = MagicMock()
        coord.data = data
        return coord

    def test_basic_device_info(self):
        pairing = {"deviceId": "dev-1", "tag": "My Charger"}
        coord = self._coordinator({
            "devices": {"dev-1": {"pairing": pairing, "version": "1.0", "additional": {}}},
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info["name"] == "My Charger"
        assert info["manufacturer"] == "V2C"
        assert info["sw_version"] == "1.0"

    def test_name_falls_back_to_device_id(self):
        pairing = {"deviceId": "dev-1"}
        coord = self._coordinator({
            "devices": {"dev-1": {"pairing": pairing, "version": None, "additional": {}}},
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info["name"] == "dev-1"

    def test_model_from_version_info(self):
        pairing = {"deviceId": "dev-1"}
        coord = self._coordinator({
            "devices": {
                "dev-1": {
                    "pairing": pairing,
                    "version": "2.0",
                    "additional": {
                        "version_info": {"modelName": "trydan_v2"}
                    },
                }
            },
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info["model"] == "Trydan V2"

    def test_model_init_is_suppressed(self):
        pairing = {"deviceId": "dev-1"}
        coord = self._coordinator({
            "devices": {
                "dev-1": {
                    "pairing": pairing,
                    "version": None,
                    "additional": {
                        "version_info": {"modelName": "INIT"}
                    },
                }
            },
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info.get("model") is None

    def test_model_from_pairing_model_name(self):
        pairing = {"deviceId": "dev-1", "modelName": "trydan_pro"}
        coord = self._coordinator({
            "devices": {"dev-1": {"pairing": pairing, "version": None, "additional": {}}},
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info["model"] == "Trydan Pro"

    def test_sw_version_none_when_no_version(self):
        pairing = {"deviceId": "dev-1"}
        coord = self._coordinator({
            "devices": {"dev-1": {"pairing": pairing, "version": None, "additional": {}}},
            "pairings": [pairing],
        })
        info = build_device_info(coord, "dev-1")
        assert info.get("sw_version") is None


# ---------------------------------------------------------------------------
# _OptimisticHoldMixin
# ---------------------------------------------------------------------------


class _ConcreteHoldMixin(_OptimisticHoldMixin):
    """Minimal concrete subclass for testing the mixin."""

    def __init__(self, hold_seconds: float = 20.0) -> None:
        self._OPTIMISTIC_HOLD_SECONDS = hold_seconds
        self._last_command_ts: float | None = None


class TestOptimisticHoldMixin:
    """Tests for _OptimisticHoldMixin bookkeeping."""

    def test_initially_not_within_hold(self):
        mixin = _ConcreteHoldMixin()
        assert mixin._is_within_hold() is False

    def test_record_command_starts_hold(self):
        mixin = _ConcreteHoldMixin()
        mixin._record_command()
        assert mixin._is_within_hold() is True

    def test_clear_command_ends_hold(self):
        mixin = _ConcreteHoldMixin()
        mixin._record_command()
        mixin._clear_command()
        assert mixin._is_within_hold() is False

    def test_hold_expires_after_window(self):
        mixin = _ConcreteHoldMixin(hold_seconds=0.01)
        mixin._record_command()
        time.sleep(0.02)
        assert mixin._is_within_hold() is False

    def test_expire_hold_clears_timestamp_after_expiry(self):
        mixin = _ConcreteHoldMixin(hold_seconds=0.01)
        mixin._record_command()
        time.sleep(0.02)
        mixin._expire_hold_if_needed()
        assert mixin._last_command_ts is None

    def test_expire_hold_keeps_timestamp_if_not_expired(self):
        mixin = _ConcreteHoldMixin(hold_seconds=60.0)
        mixin._record_command()
        mixin._expire_hold_if_needed()
        assert mixin._last_command_ts is not None

    def test_is_within_hold_when_no_ts_attribute(self):
        """_is_within_hold uses getattr to safely access _last_command_ts."""
        mixin = _OptimisticHoldMixin()
        # _last_command_ts declared as ClassVar annotation but not set in __init__
        # getattr with default None should make this return False
        assert mixin._is_within_hold() is False
