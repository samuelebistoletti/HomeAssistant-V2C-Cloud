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
                "IntensityMeasure_L1",
                "IntensityMeasure_L2",
                "IntensityMeasure_L3",
                "VoltageMeasure_L1",
                "VoltageMeasure_L2",
                "VoltageMeasure_L3",
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

    def _switch(
        self,
        *,
        local_keys: tuple[str, ...],
        cloud_only: bool,
        cloud_ok: bool = True,
    ) -> object:
        from custom_components.v2c_cloud.switch import V2CBooleanSwitch

        sw = V2CBooleanSwitch.__new__(V2CBooleanSwitch)
        sw._runtime_data = MagicMock()
        sw._runtime_data.cloud_only = cloud_only
        # Stated outright: a bare MagicMock is truthy, so leaving this to the
        # mock would make the cloud-health gate untestable by accident.
        sw._runtime_data.cloud_commands_available = cloud_ok
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

    def _select(
        self,
        *,
        local_key: str | None,
        cloud_only: bool,
        cloud_ok: bool = True,
    ) -> object:
        from custom_components.v2c_cloud.select import V2CEnumSelect

        sel = V2CEnumSelect.__new__(V2CEnumSelect)
        sel._runtime_data = MagicMock()
        sel._runtime_data.cloud_only = cloud_only
        sel._runtime_data.cloud_commands_available = cloud_ok
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
        # /reported, so they MUST stay available in cloud-only mode — as long
        # as the cloud itself is answering.
        sel = self._select(local_key=None, cloud_only=True)
        assert sel.available is True

    def test_local_mode_lan_select_available(self) -> None:
        sel = self._select(local_key="ChargeMode", cloud_only=False)
        assert sel.available is True


# ---------------------------------------------------------------------------
# The mirror case: the cloud is what is missing, not the LAN
# ---------------------------------------------------------------------------


class TestUnauthenticatedCloudGating:
    """
    A control with no LAN route must go Unavailable when the cloud is out.

    During the V2C auth outage (issue #54) the integration kept running over
    the LAN, which is the point — but OCPP and the RFID reader, which exist
    only in the cloud API, stayed available and toggleable. Pressing one
    raised deep inside the client and changed nothing on the charger, while
    the switch went on displaying a state it had never received. The
    integration's own log said "cloud-only controls are unavailable until it
    recovers"; nothing in the code made that true.
    """

    def _switch(self, *, local_keys: tuple[str, ...], cloud_ok: bool) -> object:
        from custom_components.v2c_cloud.switch import V2CBooleanSwitch

        sw = V2CBooleanSwitch.__new__(V2CBooleanSwitch)
        sw._runtime_data = MagicMock()
        sw._runtime_data.cloud_only = False
        sw._runtime_data.cloud_commands_available = cloud_ok
        sw._local_keys = local_keys
        sw._local_coordinator = None
        sw.coordinator = MagicMock()
        sw.coordinator.last_update_success = True
        return sw

    def _select(self, *, local_key: str | None, cloud_ok: bool) -> object:
        from custom_components.v2c_cloud.select import V2CEnumSelect

        sel = V2CEnumSelect.__new__(V2CEnumSelect)
        sel._runtime_data = MagicMock()
        sel._runtime_data.cloud_only = False
        sel._runtime_data.cloud_commands_available = cloud_ok
        sel._local_key = local_key
        sel._local_coordinator = None
        sel.coordinator = MagicMock()
        sel.coordinator.last_update_success = True
        return sel

    def _number(self, *, local_key: str | None, cloud_ok: bool) -> object:
        from custom_components.v2c_cloud.number import V2CNumberEntity

        num = V2CNumberEntity.__new__(V2CNumberEntity)
        num._runtime_data = MagicMock()
        num._runtime_data.cloud_commands_available = cloud_ok
        num._local_key = local_key
        num._local_coordinator = None
        num.coordinator = MagicMock()
        num.coordinator.last_update_success = True
        return num

    def _button(self, *, cloud_ok: bool) -> object:
        from custom_components.v2c_cloud.button import V2CButton

        btn = V2CButton.__new__(V2CButton)
        btn._runtime_data = MagicMock()
        btn._runtime_data.cloud_commands_available = cloud_ok
        btn.coordinator = MagicMock()
        btn.coordinator.last_update_success = True
        return btn

    def _binary_sensor(self, *, cloud_ok: bool) -> object:
        from custom_components.v2c_cloud.binary_sensor import V2CConnectedBinarySensor

        sensor = V2CConnectedBinarySensor.__new__(V2CConnectedBinarySensor)
        sensor._runtime_data = MagicMock()
        sensor._runtime_data.cloud_commands_available = cloud_ok
        sensor.coordinator = MagicMock()
        sensor.coordinator.last_update_success = True
        return sensor

    # -- switches ----------------------------------------------------------

    def test_ocpp_switch_unavailable_without_cloud(self) -> None:
        """OCPP has no LAN keyword at all."""
        assert self._switch(local_keys=(), cloud_ok=False).available is False

    def test_ocpp_switch_available_with_cloud(self) -> None:
        assert self._switch(local_keys=(), cloud_ok=True).available is True

    def test_lan_backed_switch_survives_the_outage(self) -> None:
        """The whole point of degrading instead of unloading."""
        assert self._switch(local_keys=("Dynamic",), cloud_ok=False).available is True

    # -- selects -----------------------------------------------------------

    def test_cloud_only_select_unavailable_without_cloud(self) -> None:
        """Installation type, slave device and language are cloud-only."""
        assert self._select(local_key=None, cloud_ok=False).available is False

    def test_lan_backed_select_survives_the_outage(self) -> None:
        assert self._select(local_key="ChargeMode", cloud_ok=False).available is True

    # -- numbers -----------------------------------------------------------

    def test_cloud_only_number_unavailable_without_cloud(self) -> None:
        assert self._number(local_key=None, cloud_ok=False).available is False

    def test_lan_backed_number_survives_the_outage(self) -> None:
        assert self._number(local_key="Intensity", cloud_ok=False).available is True

    # -- buttons and the cloud connectivity sensor -------------------------

    def test_buttons_unavailable_without_cloud(self) -> None:
        """Reboot and firmware update are cloud commands with no LAN twin."""
        assert self._button(cloud_ok=False).available is False

    def test_buttons_available_with_cloud(self) -> None:
        assert self._button(cloud_ok=True).available is True

    def test_cloud_connectivity_sensor_unavailable_without_cloud(self) -> None:
        """
        It reports what the cloud thinks, so a dead cloud leaves it nothing.

        Crucially it must not read as "the charger is offline": the LAN may be
        working, and `Trasporto attivo` is the sensor that says so.
        """
        assert self._binary_sensor(cloud_ok=False).available is False

    def test_cloud_connectivity_sensor_available_with_cloud(self) -> None:
        assert self._binary_sensor(cloud_ok=True).available is True


class TestCloudAuthState:
    """`cloud_commands_available` is the single source of truth."""

    def test_healthy_by_default(self) -> None:
        from custom_components.v2c_cloud import _CloudAuthState

        assert _CloudAuthState().usable is True

    def test_degraded_blocks_cloud_commands(self) -> None:
        from custom_components.v2c_cloud import _CloudAuthState

        assert _CloudAuthState(degraded=True).usable is False

    def test_lan_only_entry_has_no_cloud_at_all(self) -> None:
        """No account was ever supplied, so cloud controls can never work."""
        from custom_components.v2c_cloud import _CloudAuthState

        assert _CloudAuthState(absent=True).usable is False

    def test_runtime_data_exposes_the_state(self) -> None:
        from custom_components.v2c_cloud import V2CEntryRuntimeData, _CloudAuthState

        runtime = V2CEntryRuntimeData(
            client=MagicMock(),
            coordinator=MagicMock(),
            cloud_auth=_CloudAuthState(degraded=True),
        )
        assert runtime.cloud_commands_available is False

    def test_runtime_data_defaults_to_healthy(self) -> None:
        from custom_components.v2c_cloud import V2CEntryRuntimeData

        runtime = V2CEntryRuntimeData(client=MagicMock(), coordinator=MagicMock())
        assert runtime.cloud_commands_available is True
