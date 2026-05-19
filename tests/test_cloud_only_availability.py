"""Tests for the LAN-only availability gating (B2, 2026-05-19).

When a config entry is configured as cloud-only (4G), entities backed by
LAN-only `/RealTimeData` keys cannot produce a useful value because the
V2C cloud `/reported` and `/currentstatecharge` payloads do not contain
the data. The `available` property must return False for these entities
so the Home Assistant UI shows "Unavailable" rather than the misleading
"Unknown" state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.v2c_cloud.local_api import LAN_ONLY_KEYS


def test_lan_only_keys_set() -> None:
    """Lock down which keys are considered LAN-only.

    Updating this set has UX implications (entities flip to Unavailable),
    so any addition or removal should be intentional and reflected here.
    """
    assert (
        frozenset(
            {
                "ReadyState",
                "SignalStatus",
                "Timer",
                "ChargeMode",
                "DynamicPowerMode",
                "PauseDynamic",
            }
        )
        == LAN_ONLY_KEYS
    )


class TestSensorAvailabilityGating:
    """V2CLocalRealtimeSensor.available — cloud_only + LAN-only key → False."""

    def _sensor(self, *, key: str, cloud_only: bool) -> object:
        from custom_components.v2c_cloud.sensor import V2CLocalRealtimeSensor

        sensor = V2CLocalRealtimeSensor.__new__(V2CLocalRealtimeSensor)
        sensor._runtime_data = MagicMock()
        sensor._runtime_data.cloud_only = cloud_only
        sensor.entity_description = MagicMock()
        sensor.entity_description.key = key
        # Bypass the super().available chain — assume the coordinator path
        # is happy so we isolate the LAN-only gate.
        sensor.coordinator = MagicMock()
        sensor.coordinator.last_update_success = True
        return sensor

    def test_cloud_only_lan_key_is_unavailable(self) -> None:
        sensor = self._sensor(key="SignalStatus", cloud_only=True)
        assert sensor.available is False

    def test_cloud_only_non_lan_key_falls_through(self) -> None:
        sensor = self._sensor(key="ChargeState", cloud_only=True)
        # ChargeState is mapped from cloud → available should defer to base
        assert sensor.available is True

    def test_local_mode_lan_key_is_available(self) -> None:
        sensor = self._sensor(key="SignalStatus", cloud_only=False)
        assert sensor.available is True

    def test_every_lan_only_sensor_key_gated(self) -> None:
        """All sensor-side LAN-only keys are blocked in cloud-only mode."""
        for key in ("ReadyState", "SignalStatus", "Timer"):
            sensor = self._sensor(key=key, cloud_only=True)
            assert sensor.available is False, f"{key} should be unavailable"


class TestSwitchAvailabilityGating:
    """V2CBooleanSwitch.available — cloud_only + LAN-only local_keys → False."""

    def _switch(self, *, local_keys: tuple[str, ...], cloud_only: bool) -> object:
        from custom_components.v2c_cloud.switch import V2CBooleanSwitch

        sw = V2CBooleanSwitch.__new__(V2CBooleanSwitch)
        sw._runtime_data = MagicMock()
        sw._runtime_data.cloud_only = cloud_only
        sw._local_keys = local_keys
        sw._local_coordinator = None
        sw.coordinator = MagicMock()
        sw.coordinator.last_update_success = True
        return sw

    def test_cloud_only_timer_switch_unavailable(self) -> None:
        sw = self._switch(local_keys=("Timer",), cloud_only=True)
        assert sw.available is False

    def test_cloud_only_pause_dynamic_unavailable(self) -> None:
        sw = self._switch(local_keys=("PauseDynamic",), cloud_only=True)
        assert sw.available is False

    def test_cloud_only_non_lan_switch_still_available(self) -> None:
        # Dynamic IS in the cloud → switch stays available
        sw = self._switch(local_keys=("Dynamic",), cloud_only=True)
        assert sw.available is True

    def test_local_mode_lan_switch_available(self) -> None:
        sw = self._switch(local_keys=("Timer",), cloud_only=False)
        assert sw.available is True

    def test_no_local_keys_does_not_block(self) -> None:
        """Cloud-only entities that don't track a local_key shouldn't be gated."""
        sw = self._switch(local_keys=(), cloud_only=True)
        assert sw.available is True


class TestSelectAvailabilityGating:
    """V2CEnumSelect.available — cloud_only + LAN-only local_key → False."""

    def _select(self, *, local_key: str | None, cloud_only: bool) -> object:
        from custom_components.v2c_cloud.select import V2CEnumSelect

        sel = V2CEnumSelect.__new__(V2CEnumSelect)
        sel._runtime_data = MagicMock()
        sel._runtime_data.cloud_only = cloud_only
        sel._local_key = local_key
        sel._local_coordinator = None
        sel.coordinator = MagicMock()
        sel.coordinator.last_update_success = True
        return sel

    def test_cloud_only_charge_mode_unavailable(self) -> None:
        sel = self._select(local_key="ChargeMode", cloud_only=True)
        assert sel.available is False

    def test_cloud_only_dynamic_power_mode_unavailable(self) -> None:
        sel = self._select(local_key="DynamicPowerMode", cloud_only=True)
        assert sel.available is False

    def test_cloud_only_no_local_key_available(self) -> None:
        # installation_type / language have no local_key → read directly from
        # /reported, so they MUST stay available in cloud-only mode.
        sel = self._select(local_key=None, cloud_only=True)
        assert sel.available is True

    def test_local_mode_lan_select_available(self) -> None:
        sel = self._select(local_key="ChargeMode", cloud_only=False)
        assert sel.available is True
