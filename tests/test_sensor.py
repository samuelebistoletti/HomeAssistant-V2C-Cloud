"""Tests for sensor.py helper functions and V2CLocalRealtimeSensor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.v2c_cloud.sensor import (
    _as_flag,
    _as_float,
    _as_int,
    _as_str,
    _localize_state,
)


# ---------------------------------------------------------------------------
# _as_float
# ---------------------------------------------------------------------------


class TestAsFloat:
    """Tests for _as_float conversion."""

    def test_none_returns_none(self):
        assert _as_float(None) is None

    def test_int(self):
        assert _as_float(5) == pytest.approx(5.0)

    def test_float(self):
        assert _as_float(3.14) == pytest.approx(3.14)

    def test_numeric_string(self):
        assert _as_float("7.5") == pytest.approx(7.5)

    def test_integer_string(self):
        assert _as_float("10") == pytest.approx(10.0)

    def test_invalid_string_returns_none(self):
        assert _as_float("abc") is None

    def test_empty_string_returns_none(self):
        assert _as_float("") is None

    def test_zero(self):
        assert _as_float(0) == pytest.approx(0.0)

    def test_negative(self):
        assert _as_float(-3.5) == pytest.approx(-3.5)


# ---------------------------------------------------------------------------
# _as_int
# ---------------------------------------------------------------------------


class TestAsInt:
    """Tests for _as_int conversion."""

    def test_none_returns_none(self):
        assert _as_int(None) is None

    def test_int_value(self):
        assert _as_int(7) == 7

    def test_float_truncates(self):
        assert _as_int(4.9) == 4

    def test_float_string_with_dot(self):
        assert _as_int("3.0") == 3

    def test_integer_string(self):
        assert _as_int("42") == 42

    def test_invalid_returns_none(self):
        assert _as_int("abc") is None

    def test_empty_string_returns_none(self):
        assert _as_int("") is None

    def test_whitespace_only_returns_none(self):
        assert _as_int("   ") is None

    def test_negative_int(self):
        assert _as_int(-2) == -2

    def test_zero(self):
        assert _as_int(0) == 0


# ---------------------------------------------------------------------------
# _as_str
# ---------------------------------------------------------------------------


class TestAsStr:
    """Tests for _as_str conversion."""

    def test_none_returns_none(self):
        assert _as_str(None) is None

    def test_string_trimmed(self):
        assert _as_str("  hello  ") == "hello"

    def test_empty_string_returns_none(self):
        assert _as_str("") is None

    def test_whitespace_only_returns_none(self):
        assert _as_str("   ") is None

    def test_int_converted_to_str(self):
        assert _as_str(42) == "42"

    def test_float_converted_to_str(self):
        result = _as_str(3.14)
        assert isinstance(result, str)
        assert "3.14" in result

    def test_non_empty_string(self):
        assert _as_str("v1.2.3") == "v1.2.3"


# ---------------------------------------------------------------------------
# _as_flag
# ---------------------------------------------------------------------------


class TestAsFlag:
    """Tests for _as_flag — boolean-like values mapped to 1/0."""

    @pytest.mark.parametrize("value", [True, 1, "true", "on", "yes", "1"])
    def test_truthy_returns_1(self, value):
        assert _as_flag(value) == 1

    @pytest.mark.parametrize("value", [False, 0, "false", "off", "no", "0"])
    def test_falsy_returns_0(self, value):
        assert _as_flag(value) == 0

    def test_none_returns_none(self):
        assert _as_flag(None) is None

    def test_unknown_string_returns_none(self):
        assert _as_flag("maybe") is None


# ---------------------------------------------------------------------------
# _localize_state
# ---------------------------------------------------------------------------


class TestLocalizeState:
    """Tests for _localize_state — maps integer codes to human labels."""

    def _hass(self, language: str = "en") -> MagicMock:
        hass = MagicMock()
        hass.config.language = language
        return hass

    def test_charge_state_english(self):
        result = _localize_state("ChargeState", 2, self._hass("en"))
        assert result == "Charging"

    def test_charge_state_italian(self):
        result = _localize_state("ChargeState", 2, self._hass("it"))
        assert result == "In carica"

    def test_charge_state_unknown_language_falls_back_to_en(self):
        result = _localize_state("ChargeState", 2, self._hass("fr"))
        assert result == "Charging"

    def test_unknown_key_returns_none(self):
        result = _localize_state("NonExistentKey", 0, self._hass())
        assert result is None

    def test_none_value_returns_none(self):
        result = _localize_state("ChargeState", None, self._hass())
        assert result is None

    def test_out_of_range_value_returns_none(self):
        result = _localize_state("ChargeState", 99, self._hass())
        assert result is None

    def test_bool_true_mapped_as_1(self):
        result = _localize_state("Paused", True, self._hass())
        assert result == "Yes"

    def test_bool_false_mapped_as_0(self):
        result = _localize_state("Paused", False, self._hass())
        assert result == "No"

    def test_string_digit_is_normalised(self):
        result = _localize_state("ChargeState", "0", self._hass())
        assert result == "Disconnected"

    def test_locked_state(self):
        assert _localize_state("Locked", 1, self._hass()) == "Locked"
        assert _localize_state("Locked", 0, self._hass()) == "Unlocked"

    def test_dynamic_power_mode(self):
        assert _localize_state("DynamicPowerMode", 2, self._hass()) == "Exclusive PV mode"

    def test_language_with_region_code(self):
        """hass.config.language may include region like 'en-US'."""
        result = _localize_state("ChargeState", 0, self._hass("en-US"))
        assert result == "Disconnected"


# ---------------------------------------------------------------------------
# V2CLocalRealtimeSensor.native_value
# ---------------------------------------------------------------------------


def _make_local_sensor(key: str, raw_value, value_fn=None):
    """Instantiate V2CLocalRealtimeSensor with a simple coordinator payload."""
    from custom_components.v2c_cloud.sensor import V2CLocalRealtimeSensor, V2CLocalRealtimeSensorDescription

    description = V2CLocalRealtimeSensorDescription(
        key=key,
        translation_key=key.lower(),
        unique_id_suffix=key.lower(),
        value_fn=value_fn,
    )

    coord = MagicMock()
    coord.data = {key: raw_value}

    runtime_data = MagicMock()
    runtime_data.coordinator = coord

    sensor = V2CLocalRealtimeSensor(runtime_data, coord, "dev-1", description)
    sensor.hass = MagicMock()
    sensor.hass.config.language = "en"
    return sensor


class TestV2CLocalRealtimeSensorNativeValue:
    """Tests for V2CLocalRealtimeSensor.native_value."""

    def test_returns_raw_value_when_no_value_fn(self):
        sensor = _make_local_sensor("ChargeEnergy", 12.5, value_fn=None)
        assert sensor.native_value == pytest.approx(12.5)

    def test_applies_value_fn(self):
        from custom_components.v2c_cloud.sensor import _as_float

        # Use a non-localized key so _localize_state does not transform the value
        sensor = _make_local_sensor("ChargeEnergy", "3.5", value_fn=_as_float)
        assert sensor.native_value == pytest.approx(3.5)

    def test_returns_none_when_data_is_not_dict(self):
        sensor = _make_local_sensor("ChargeState", 1)
        sensor.coordinator.data = "invalid"
        assert sensor.native_value is None

    def test_returns_localized_label_for_charge_state(self):
        from custom_components.v2c_cloud.sensor import _as_int

        sensor = _make_local_sensor("ChargeState", 2, value_fn=_as_int)
        # _localize_state maps 2 → "Charging"
        assert sensor.native_value == "Charging"

    def test_missing_key_returns_none_through_fn(self):
        from custom_components.v2c_cloud.sensor import _as_float

        sensor = _make_local_sensor("HousePower", None, value_fn=_as_float)
        assert sensor.native_value is None

    def test_unique_id_format(self):
        sensor = _make_local_sensor("ChargeState", 1)
        assert sensor._attr_unique_id == "v2c_dev-1_chargestate"
