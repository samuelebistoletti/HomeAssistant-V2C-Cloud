"""Tests for V2CConnectedBinarySensor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_coordinator(connected_value, reported_value=None):
    """Build a minimal coordinator with one device."""
    additional: dict = {}
    reported: dict = {}
    if reported_value is not None:
        reported = {"connected": reported_value}
        additional["reported_lower"] = {"connected": reported_value}

    coord = MagicMock()
    coord.data = {
        "devices": {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "connected": connected_value,
                "reported": reported,
                "additional": additional,
            }
        },
        "pairings": [{"deviceId": "dev-1"}],
    }
    coord.last_update_success = True
    return coord


def _make_sensor(connected_value=None, reported_value=None):
    from custom_components.v2c_cloud.binary_sensor import V2CConnectedBinarySensor

    coord = _make_coordinator(connected_value, reported_value)
    client = MagicMock()
    return V2CConnectedBinarySensor(coord, client, "dev-1")


class TestV2CConnectedBinarySensor:
    """Tests for V2CConnectedBinarySensor.is_on."""

    def _sensor(self, connected_value=None, reported_value=None):
        return _make_sensor(connected_value, reported_value)

    def test_bool_true(self):
        sensor = self._sensor(connected_value=True)
        assert sensor.is_on is True

    def test_bool_false(self):
        sensor = self._sensor(connected_value=False)
        assert sensor.is_on is False

    def test_int_one_is_on(self):
        sensor = self._sensor(connected_value=1)
        assert sensor.is_on is True

    def test_int_zero_is_off(self):
        sensor = self._sensor(connected_value=0)
        assert sensor.is_on is False

    def test_float_nonzero_is_on(self):
        sensor = self._sensor(connected_value=1.0)
        assert sensor.is_on is True

    def test_string_online(self):
        sensor = self._sensor(connected_value="online")
        assert sensor.is_on is True

    def test_string_true(self):
        sensor = self._sensor(connected_value="true")
        assert sensor.is_on is True

    def test_string_1(self):
        sensor = self._sensor(connected_value="1")
        assert sensor.is_on is True

    def test_string_offline_is_false(self):
        # "offline" is not in the recognised truthy set → False (not None)
        sensor = self._sensor(connected_value="offline")
        assert sensor.is_on is False

    def test_none_falls_back_to_reported(self):
        sensor = self._sensor(connected_value=None, reported_value=True)
        assert sensor.is_on is True

    def test_none_with_no_reported_is_none(self):
        sensor = self._sensor(connected_value=None)
        assert sensor.is_on is None

    def test_unique_id_format(self):
        sensor = self._sensor()
        assert sensor._attr_unique_id == "v2c_dev-1_connected_status"

    def test_translation_key(self):
        sensor = self._sensor()
        assert sensor._attr_translation_key == "connected"
