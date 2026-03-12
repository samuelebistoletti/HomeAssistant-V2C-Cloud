"""Tests for local_api helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.v2c_cloud.local_api import get_local_data, get_local_value


# ---------------------------------------------------------------------------
# get_local_value — case-insensitive key lookup
# ---------------------------------------------------------------------------

class TestGetLocalValue:
    """Tests for get_local_value key lookup in RealTimeData payloads."""

    def test_exact_match(self):
        data = {"ChargeState": 2, "ChargeEnergy": 12.5}
        found, value = get_local_value(data, "ChargeState")
        assert found is True
        assert value == 2

    def test_case_insensitive_match_lowercase_query(self):
        data = {"ChargeState": 2}
        found, value = get_local_value(data, "chargestate")
        assert found is True
        assert value == 2

    def test_case_insensitive_match_uppercase_query(self):
        data = {"chargestate": 5}
        found, value = get_local_value(data, "ChargeState")
        assert found is True
        assert value == 5

    def test_logoled_case_insensitive(self):
        """LogoLED is a known read-only keyword that may appear in different cases."""
        data = {"LogoLED": 1.0}
        found, value = get_local_value(data, "logoled")
        assert found is True
        assert value == 1.0

    def test_key_not_found_returns_false_and_none(self):
        data = {"ChargeState": 2}
        found, value = get_local_value(data, "NonExistent")
        assert found is False
        assert value is None

    def test_exact_match_preferred_over_case_insensitive(self):
        """Exact key takes priority when both forms exist."""
        data = {"ChargeState": 10, "chargestate": 20}
        found, value = get_local_value(data, "ChargeState")
        assert found is True
        assert value == 10

    def test_empty_dict_returns_not_found(self):
        found, value = get_local_value({}, "AnyKey")
        assert found is False
        assert value is None

    def test_value_zero_is_found(self):
        """A value of 0 is falsy but must be detected as found."""
        data = {"Paused": 0}
        found, value = get_local_value(data, "Paused")
        assert found is True
        assert value == 0

    def test_none_value_is_found(self):
        """A None value stored under a key must be found."""
        data = {"SomeKey": None}
        found, value = get_local_value(data, "SomeKey")
        assert found is True
        assert value is None

    def test_float_value(self):
        data = {"SlaveVoltage": 230.5}
        found, value = get_local_value(data, "slavevoltage")
        assert found is True
        assert value == pytest.approx(230.5)

    def test_bool_value_true(self):
        data = {"Locked": True}
        found, value = get_local_value(data, "Locked")
        assert found is True
        assert value is True

    def test_bool_value_false(self):
        data = {"Locked": False}
        found, value = get_local_value(data, "locked")
        assert found is True
        assert value is False

    def test_string_value(self):
        data = {"FirmwareVersion": "1.2.3"}
        found, value = get_local_value(data, "firmwareversion")
        assert found is True
        assert value == "1.2.3"


# ---------------------------------------------------------------------------
# get_local_data — read latest cached local payload
# ---------------------------------------------------------------------------

class TestGetLocalData:
    """Tests for get_local_data returning coordinator payload."""

    def test_returns_data_when_coordinator_exists(self):
        payload = {"ChargeState": 1, "_static_ip": "192.168.1.50"}
        local_coordinator = MagicMock()
        local_coordinator.data = payload

        runtime_data = MagicMock()
        runtime_data.local_coordinators = {"dev-1": local_coordinator}

        result = get_local_data(runtime_data, "dev-1")
        assert result == payload

    def test_returns_none_when_coordinator_missing(self):
        runtime_data = MagicMock()
        runtime_data.local_coordinators = {}

        result = get_local_data(runtime_data, "dev-1")
        assert result is None

    def test_returns_none_when_coordinator_data_is_not_dict(self):
        local_coordinator = MagicMock()
        local_coordinator.data = None

        runtime_data = MagicMock()
        runtime_data.local_coordinators = {"dev-1": local_coordinator}

        result = get_local_data(runtime_data, "dev-1")
        assert result is None

    def test_returns_none_for_different_device_id(self):
        local_coordinator = MagicMock()
        local_coordinator.data = {"ChargeState": 1}

        runtime_data = MagicMock()
        runtime_data.local_coordinators = {"dev-1": local_coordinator}

        result = get_local_data(runtime_data, "dev-2")
        assert result is None
