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

    def test_light_led_from_cloud(self) -> None:
        runtime = _runtime_with_reported({"light_led": "1.000000"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["LightLED"] == 1

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
        # Real cloud key is `contract_power` (NOT `contractedpower`).
        # The bug pre-2026-05-19 was that the entity read `contractedpower`
        # but the cloud key didn't match.
        runtime = _runtime_with_reported({"contract_power": "7"})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ContractedPower"] == 7

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
        assert result["LightLED"] == 1
        assert result["LogoLED"] == 1
        assert result["ContractedPower"] == 7

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
        # Power values scaled from kW → W (csc voltage 0.0728 = kV → scale 1000)
        assert result["HousePower"] == 212.0
        assert result["VoltageInstallation"] == 72.8
