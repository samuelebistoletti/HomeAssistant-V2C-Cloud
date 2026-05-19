"""Tests for `_build_realtime_from_reported` — the cloud-only synthesis path.

Verifies that every mapping in `_REPORTED_TO_REALTIME` plus the new string-field
passthrough (added 2026-05-19) populates the synthetic /RealTimeData dict that
all entity platforms read.

The reference payload shape mirrors a real `/device/reported` capture from a
Trydan running firmware 2.4.6 — fields irrelevant to entity reads have been
stripped, but all the keys that drive entity values are present.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock

from custom_components.v2c_cloud.local_api import _build_realtime_from_reported


def _runtime_with_reported(reported: dict[str, Any]) -> Any:
    """Build a minimal V2CEntryRuntimeData mock that exposes reported data."""
    runtime = MagicMock()
    runtime.coordinator.data = {
        "devices": {
            "dev1": {
                "reported": reported,
                "additional": {},
            }
        }
    }
    return runtime


def _runtime_with_reported_and_csc(
    reported: dict[str, Any], csc: dict[str, Any]
) -> Any:
    runtime = MagicMock()
    runtime.coordinator.data = {
        "devices": {
            "dev1": {
                "reported": reported,
                "additional": {"currentstatecharge": csc},
            }
        }
    }
    return runtime


# ---------------------------------------------------------------------------
# New mappings added 2026-05-19 — verified against real /reported payload
# ---------------------------------------------------------------------------


class TestNumberEntityCloudFallback:
    """Number entities (LightLED, MinIntensity, MaxIntensity, ContractedPower)
    were Unknown in cloud-only mode because the cloud key wasn't in the synthesis
    map. Confirm each one now resolves."""

    def test_light_led_from_cloud_full_brightness(self) -> None:
        # Cloud serialises LightLED as a 0.0-1.0 fraction; "1.000000" = 100 %.
        # The Number entity is defined on 0-100 %, so synthesis must scale
        # by 100 to align with the LAN /RealTimeData convention.
        runtime = _runtime_with_reported({"light_led": "1.000000"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["LightLED"] == 100

    def test_light_led_from_cloud_mid_brightness(self) -> None:
        runtime = _runtime_with_reported({"light_led": "0.500000"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["LightLED"] == 50

    def test_light_led_from_cloud_off(self) -> None:
        runtime = _runtime_with_reported({"light_led": "0.000000"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["LightLED"] == 0

    def test_min_intensity_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"min_car_int": "6"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MinIntensity"] == 6

    def test_min_intensity_fallback_alias(self) -> None:
        # If only the *_fb fallback is present, still map it
        runtime = _runtime_with_reported({"min_car_int_fb": "6"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MinIntensity"] == 6

    def test_max_intensity_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"max_car_int": "32"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MaxIntensity"] == 32

    def test_max_intensity_fallback_alias(self) -> None:
        runtime = _runtime_with_reported({"max_car_int_fb": "32"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MaxIntensity"] == 32

    def test_contracted_power_from_cloud(self) -> None:
        # Cloud encodes contract_power as W/100, so "7" -> 700 W (= 0.7 kW).
        # The Number entity uses W and divides by 1000 in source_to_native
        # to render kW; without the x100 override the UI would show 0.007 kW.
        # Verified against a live install where the V2C app displayed 0.7 kW
        # for cloud value "7".
        runtime = _runtime_with_reported({"contract_power": "7"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ContractedPower"] == 700

    def test_contracted_power_higher_value(self) -> None:
        # 5 kW contract -> cloud encoded as "50" -> 5000 W -> entity shows 5.0 kW.
        runtime = _runtime_with_reported({"contract_power": "50"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ContractedPower"] == 5000

    def test_contracted_power_decimal_input(self) -> None:
        # Edge case: cloud may report fractional values (e.g. "3.45" -> 345 W).
        runtime = _runtime_with_reported({"contract_power": "3.45"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ContractedPower"] == 345


class TestVoltageInstallationMapping:
    """The mains/installation voltage comes from `cp_level` in cloud payloads
    (e.g. 248 V on a 230 V EU install). The cloud's `voltage` field carries
    a small internal signal (e.g. 0.077350) that does NOT correspond to the
    mains voltage, so it is intentionally NOT mapped — but it is still used
    by `_detect_cloud_scale` as a magnitude heuristic for power fields."""

    # A minimal /reported is required because _build_realtime_from_reported
    # short-circuits on an empty reported dict (the synthesis pipeline is
    # gated on /reported existing).
    _PROBE_REPORTED: ClassVar[dict[str, Any]] = {"device_id": "dev1"}

    def test_voltage_installation_from_cp_level(self) -> None:
        runtime = _runtime_with_reported_and_csc(
            self._PROBE_REPORTED, {"cp_level": "248.000000"}
        )
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["VoltageInstallation"] == 248.0

    def test_cloud_voltage_field_not_mapped(self) -> None:
        # Regression: pre-fix the cloud `voltage` field (= 0.077350) was
        # scaled by 1000 in _detect_cloud_scale and surfaced as 77.35 V, a
        # spurious mains-voltage reading. After the fix this field MUST be
        # ignored as a voltage source.
        runtime = _runtime_with_reported_and_csc(
            self._PROBE_REPORTED,
            {"voltage": "0.077350"},
        )
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "VoltageInstallation" not in result

    def test_cp_level_no_longer_emits_cplevel_key(self) -> None:
        # Regression: cp_level used to map to a (unused) `CpLevel` key.
        # After remapping to VoltageInstallation, the CpLevel key must
        # not appear in the synthesised RealTimeData.
        runtime = _runtime_with_reported_and_csc(
            self._PROBE_REPORTED, {"cp_level": "248.0"}
        )
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "CpLevel" not in result

    def test_logo_led_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"logo_led": "1"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["LogoLED"] == 1

    def test_primary_key_wins_over_fallback(self) -> None:
        # min_car_int = primary, min_car_int_fb = fallback. When both
        # are present, the primary value must win.
        runtime = _runtime_with_reported({"min_car_int": "6", "min_car_int_fb": "8"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MinIntensity"] == 6


class TestStringFieldPassthrough:
    """ID, FirmwareVersion, MAC — string-only fields needed for the
    device_identifier / firmware_version / wifi sensors in cloud-only."""

    def test_device_id_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"device_id": "XQUXDU"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ID"] == "XQUXDU"

    def test_device_id_alias_camelcase(self) -> None:
        runtime = _runtime_with_reported({"deviceId": "XQUXDU"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ID"] == "XQUXDU"

    def test_firmware_version_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"version": "2.4.6"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["FirmwareVersion"] == "2.4.6"

    def test_mac_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"mac": "28:56:2F:56:12:EC"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["MAC"] == "28:56:2F:56:12:EC"

    def test_empty_string_is_skipped(self) -> None:
        # A blank version field shouldn't write FirmwareVersion="" — better
        # to leave the key absent so the entity stays Unavailable.
        runtime = _runtime_with_reported({"version": ""})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "FirmwareVersion" not in result

    def test_numeric_path_does_not_clobber_string_path(self) -> None:
        # Both paths run; the string mapping must NOT trigger float coercion.
        runtime = _runtime_with_reported(
            {"version": "2.4.6", "intensity": "6", "device_id": "XQUXDU"}
        )
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["FirmwareVersion"] == "2.4.6"
        assert result["ID"] == "XQUXDU"
        assert result["Intensity"] == 6


class TestWifiInfoJsonExtraction:
    """The cloud nests SSID/IP inside a JSON-encoded `wifi_info` string."""

    def test_ssid_and_ip_extracted_from_wifi_info(self) -> None:
        wifi_info = json.dumps(
            {
                "ssid": "Home",
                "ip": "10.35.0.50",
                "static_mode": "1",
                "status": "0",
            }
        )
        runtime = _runtime_with_reported({"wifi_info": wifi_info})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["SSID"] == "Home"
        assert result["IP"] == "10.35.0.50"

    def test_wifi_info_missing_is_safe(self) -> None:
        runtime = _runtime_with_reported({})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "SSID" not in result
        assert "IP" not in result

    def test_wifi_info_malformed_json_is_safe(self) -> None:
        runtime = _runtime_with_reported({"wifi_info": "{not-json"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "SSID" not in result
        assert "IP" not in result

    def test_wifi_info_missing_keys_is_safe(self) -> None:
        runtime = _runtime_with_reported({"wifi_info": json.dumps({"status": "0"})})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "SSID" not in result
        assert "IP" not in result

    def test_wifi_info_empty_ssid_is_skipped(self) -> None:
        runtime = _runtime_with_reported(
            {"wifi_info": json.dumps({"ssid": "", "ip": "10.0.0.1"})}
        )
        result = _build_realtime_from_reported(runtime, "dev1")
        assert "SSID" not in result
        assert result["IP"] == "10.0.0.1"


class TestFullPayloadFromRealDevice:
    """End-to-end smoke test using a minimal slice of the real device's
    /reported + /currentstatecharge payloads (Trydan XQUXDU firmware 2.4.6)."""

    REPORTED: ClassVar[dict[str, Any]] = {
        # config / metadata
        "device_id": "XQUXDU",
        "deviceId": "XQUXDU",
        "version": "2.4.6",
        "mac": "28:56:2F:56:12:EC",
        "wifi_info": json.dumps({"ssid": "Home", "ip": "10.35.0.50"}),
        # number setpoints
        "intensity": "6",
        "min_car_int": "6",
        "max_car_int": "32",
        "light_led": "1.000000",
        "logo_led": "1",
        "contract_power": "7",
        # switches
        "dynamic": "1",
        "locked": "0",
        "pause": "0",
    }
    CSC: ClassVar[dict[str, Any]] = {
        # real-time telemetry
        "seconds": "26711",
        "error": "0",
        "voltage": "0.072800",  # cloud reports kV → scale 1000
        "phases": "0",
        "battery": "0.000000",
        "intensity": "0",  # csc has *live* intensity, /reported has setpoint
        "energy": "4.179506",
        "power": "0.000000",
        "house_power": "0.212000",
        "sun_power": "0.000000",
        "grid_power": "0.212000",
        "photovoltaic_on": "1",
        "cp_level": "248.000000",
        "charge_state": "2",
    }

    def test_real_device_payload_recovers_all_entities(self) -> None:
        runtime = _runtime_with_reported_and_csc(self.REPORTED, self.CSC)
        result = _build_realtime_from_reported(runtime, "dev1")

        # Number entities (previously broken in cloud-only)
        assert result["Intensity"] == 6  # from /reported (setpoint)
        assert result["MinIntensity"] == 6
        assert result["MaxIntensity"] == 32
        # LightLED: cloud "1.000000" (= 100 % fraction) -> 100 in LAN format.
        assert result["LightLED"] == 100
        assert result["LogoLED"] == 1
        # ContractedPower: cloud encodes as W/100, so "7" -> 700 W (= 0.7 kW).
        assert result["ContractedPower"] == 700

        # Sensors needing string passthrough (previously broken in cloud-only)
        assert result["ID"] == "XQUXDU"
        assert result["FirmwareVersion"] == "2.4.6"
        assert result["MAC"] == "28:56:2F:56:12:EC"
        assert result["SSID"] == "Home"
        assert result["IP"] == "10.35.0.50"

        # Already-working entities (regression check)
        assert result["Dynamic"] == 1
        assert result["Locked"] == 0
        assert result["ChargeState"] == 2  # from /csc
        assert result["ChargeTime"] == 26711  # seconds
        assert result["ChargeEnergy"] == 4.18
        # Power values scaled from kW → W (heuristic triggers because the
        # cloud `voltage` field — not real voltage — has magnitude < 10).
        assert result["HousePower"] == 212.0
        # VoltageInstallation now sourced from `cp_level` (actual mains
        # voltage in V); the cloud `voltage` field is intentionally ignored.
        assert result["VoltageInstallation"] == 248.0
