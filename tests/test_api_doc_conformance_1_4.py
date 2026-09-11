"""
Conformance tests against the published V2C API documentation (1.4.0).

Two documents are authoritative here and they disagree with each other on one
enum, so each is pinned separately:

* V2C Cloud OpenAPI 3.1.0 spec (`https://api.v2charge.com/`) — the documented
  `POST /device/timer` body and the cloud `charge_state` enum.
* Trydan local HTTP API keyword table, revision 14/07/26 — the canonical
  `ChargeState` and `DynamicPowerMode` enums for the entity layer, plus the
  per-phase measurement keys.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.const import (
    CHARGE_STATE_LABELS,
    DEFAULT_TIMER_DAYS,
    DYNAMIC_POWER_MODES,
)
from custom_components.v2c_cloud.local_api import (
    _CLOUD_TO_LAN_CHARGE_STATE,
    LAN_ONLY_KEYS,
    _build_realtime_from_reported,
    _normalise_realtime_keys,
)
from custom_components.v2c_cloud.v2c_cloud import V2CClient, V2CRequestError

BASE_URL = "https://v2c.cloud/kong/v2c_service"
API_KEY = "test-api-key-1-4-0"
DEVICE_ID = "DFL2JPV"

PER_PHASE_KEYS = (
    "IntensityMeasure_L1",
    "IntensityMeasure_L2",
    "IntensityMeasure_L3",
    "VoltageMeasure_L1",
    "VoltageMeasure_L2",
    "VoltageMeasure_L3",
)


@pytest.fixture
async def client():
    """V2CClient backed by a real session that aioresponses can intercept."""
    session = ClientSession()
    yield V2CClient(session, API_KEY)
    await session.close()


@pytest.fixture(autouse=True)
def no_sleep():
    """Disable real sleeps so retry loops are instantaneous."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


def _runtime_with_reported(reported: dict[str, Any]) -> Any:
    """Minimal V2CEntryRuntimeData mock exposing cloud reported data."""
    runtime = MagicMock()
    runtime.coordinator.data = {
        "devices": {"dev1": {"reported": reported, "additional": {}}}
    }
    return runtime


# ---------------------------------------------------------------------------
# POST /device/timer — documented body
# ---------------------------------------------------------------------------


class TestTimerBodyConformance:
    """The request must carry exactly the documented body and query params."""

    async def test_sends_documented_body_and_params(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as request:
            await client.async_program_timer(
                DEVICE_ID,
                1,
                time_start="22:00",
                time_end="06:00",
                days_of_week="123",
            )

        assert request.await_count == 1
        method, path = request.await_args.args
        assert method == "POST"
        assert path == "/device/timer"
        assert request.await_args.kwargs["params"] == {
            "deviceId": DEVICE_ID,
            "timerId": "1",
        }
        assert request.await_args.kwargs["json_body"] == {
            "timeStart": "22:00",
            "timeEnd": "06:00",
            "daysOfWeek": "123",
        }

    async def test_days_default_to_every_day(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as request:
            await client.async_program_timer(
                DEVICE_ID, 0, time_start="00:30", time_end="07:30"
            )

        body = request.await_args.kwargs["json_body"]
        assert body["daysOfWeek"] == DEFAULT_TIMER_DAYS == "1234567"

    async def test_no_undocumented_keys_are_sent(self, client):
        """Guards against the pre-1.4.0 guessed aliases coming back."""
        with patch.object(client, "_request", new_callable=AsyncMock) as request:
            await client.async_program_timer(
                DEVICE_ID, 1, time_start="22:00", time_end="06:00"
            )

        body = request.await_args.kwargs["json_body"]
        params = request.await_args.kwargs["params"]
        assert set(body) == {"timeStart", "timeEnd", "daysOfWeek"}
        assert set(params) == {"deviceId", "timerId"}
        for stray in ("start_time", "end_time", "active"):
            assert stray not in body
        assert "timer id" not in params

    @pytest.mark.parametrize(
        "days", ["", "0", "8", "12345678", "abc", "1,2", "1 2", "07"]
    )
    async def test_invalid_days_rejected(self, client, days):
        with (
            patch.object(client, "_request", new_callable=AsyncMock) as request,
            pytest.raises(V2CRequestError, match="daysOfWeek"),
        ):
            await client.async_program_timer(
                DEVICE_ID,
                1,
                time_start="22:00",
                time_end="06:00",
                days_of_week=days,
            )
        request.assert_not_awaited()

    async def test_round_trip_against_mocked_endpoint(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/timer?deviceId={DEVICE_ID}&timerId=1",
                status=200,
                body="",
            )
            await client.async_program_timer(
                DEVICE_ID, 1, time_start="22:00", time_end="06:00"
            )


# ---------------------------------------------------------------------------
# ChargeState — LAN enum is canonical, cloud codes are translated
# ---------------------------------------------------------------------------


class TestChargeStateEnum:
    """LAN keyword doc: states A/B/C/F/E/D map to 0/1/2/4/5/6, with no 3."""

    def test_lan_codes_are_pinned(self):
        assert set(CHARGE_STATE_LABELS) == {0, 1, 2, 4, 5, 6}
        assert CHARGE_STATE_LABELS[6] == "Ventilation required"

    def test_cloud_translation_table_is_pinned(self):
        assert _CLOUD_TO_LAN_CHARGE_STATE == {3: 6, 4: 5, 5: 4}

    @pytest.mark.parametrize(
        ("cloud_code", "lan_code"),
        [(0, 0), (1, 1), (2, 2), (3, 6), (4, 5), (5, 4)],
    )
    def test_synthesis_translates_cloud_codes(self, cloud_code, lan_code):
        runtime = _runtime_with_reported({"charge_state": str(cloud_code)})
        result = _build_realtime_from_reported(runtime, "dev1")
        assert result["ChargeState"] == lan_code

    def test_translation_is_applied_once(self):
        """4 <-> 5 is a swap; a double application would cancel out."""
        runtime = _runtime_with_reported({"charge_state": "4"})
        assert _build_realtime_from_reported(runtime, "dev1")["ChargeState"] == 5

    def test_unknown_code_passes_through(self):
        runtime = _runtime_with_reported({"charge_state": "9"})
        assert _build_realtime_from_reported(runtime, "dev1")["ChargeState"] == 9


# ---------------------------------------------------------------------------
# DynamicPowerMode — codes 2 and 3 per the LAN doc
# ---------------------------------------------------------------------------


def test_dynamic_power_mode_codes_match_lan_doc():
    assert DYNAMIC_POWER_MODES[2]["en"] == "Minimum power mode"
    assert DYNAMIC_POWER_MODES[3]["en"] == "Exclusive PV mode"
    assert DYNAMIC_POWER_MODES[4]["en"] == "Grid + PV mode"
    assert DYNAMIC_POWER_MODES[5]["en"] == "Stop mode"


# ---------------------------------------------------------------------------
# Per-phase measurements
# ---------------------------------------------------------------------------


class TestPerPhaseSensors:
    """Documented /RealTimeData per-phase keys are exposed as sensors."""

    def test_sensor_descriptions_exist(self):
        from custom_components.v2c_cloud.sensor import REALTIME_SENSOR_DESCRIPTIONS

        by_key = {d.key: d for d in REALTIME_SENSOR_DESCRIPTIONS}
        for key in PER_PHASE_KEYS:
            assert key in by_key, key

        # Home Assistant is stubbed in the test harness, so compare against the
        # very symbols the module resolved rather than their string values.
        from homeassistant.components.sensor import (
            SensorDeviceClass,
            SensorStateClass,
        )

        for key in PER_PHASE_KEYS[:3]:
            assert by_key[key].device_class is SensorDeviceClass.CURRENT
            assert by_key[key].state_class is SensorStateClass.MEASUREMENT
        for key in PER_PHASE_KEYS[3:]:
            assert by_key[key].device_class is SensorDeviceClass.VOLTAGE
            assert by_key[key].state_class is SensorStateClass.MEASUREMENT
        # Currents and voltages must not share a unit.
        current_units = {
            by_key[k].native_unit_of_measurement for k in PER_PHASE_KEYS[:3]
        }
        voltage_units = {
            by_key[k].native_unit_of_measurement for k in PER_PHASE_KEYS[3:]
        }
        assert len(current_units) == 1
        assert len(voltage_units) == 1
        assert current_units != voltage_units
        # The voltage unit matches the existing installation-voltage sensor.
        assert (
            by_key["VoltageMeasure_L1"].native_unit_of_measurement
            == by_key["VoltageInstallation"].native_unit_of_measurement
        )

    def test_unique_id_suffixes_are_distinct(self):
        from custom_components.v2c_cloud.sensor import REALTIME_SENSOR_DESCRIPTIONS

        suffixes = [d.unique_id_suffix for d in REALTIME_SENSOR_DESCRIPTIONS]
        assert len(suffixes) == len(set(suffixes))

    def test_translation_keys_exist_in_every_language(self):
        import json
        from pathlib import Path

        base = Path("custom_components/v2c_cloud")
        files = [
            base / "strings.json",
            base / "translations/en.json",
            base / "translations/it.json",
            base / "translations/es.json",
        ]
        expected = {
            "intensity_l1",
            "intensity_l2",
            "intensity_l3",
            "voltage_l1",
            "voltage_l2",
            "voltage_l3",
        }
        for path in files:
            sensors = json.loads(path.read_text())["entity"]["sensor"]
            missing = expected - set(sensors)
            assert not missing, f"{path}: missing {missing}"
            for key in expected:
                assert sensors[key]["name"], f"{path}: empty name for {key}"

    def test_are_lan_only(self):
        """Absent from every cloud endpoint → Unavailable in cloud-only mode."""
        for key in PER_PHASE_KEYS:
            assert key in LAN_ONLY_KEYS


class TestRealtimeKeyAliases:
    """The published sample payload spells L1 current as `IntensityMeasure_L1y`."""

    def test_alias_is_normalised(self):
        payload = _normalise_realtime_keys({"IntensityMeasure_L1y": 6})
        assert payload["IntensityMeasure_L1"] == 6

    def test_documented_key_wins(self):
        payload = _normalise_realtime_keys(
            {"IntensityMeasure_L1y": 6, "IntensityMeasure_L1": 10}
        )
        assert payload["IntensityMeasure_L1"] == 10

    def test_payload_without_alias_is_untouched(self):
        payload = _normalise_realtime_keys({"IntensityMeasure_L2": 6})
        assert payload == {"IntensityMeasure_L2": 6}


# ---------------------------------------------------------------------------
# End-to-end wiring: alias normalisation inside the LAN coordinator fetch
# ---------------------------------------------------------------------------


class TestAliasReachesCoordinatorPayload:
    """The alias map must be wired into the real /RealTimeData fetch path."""

    async def test_coordinator_payload_exposes_documented_key(self):
        from custom_components.v2c_cloud.local_api import (
            async_get_or_create_local_coordinator,
        )

        ip = "192.168.1.50"
        runtime = MagicMock()
        runtime.local_coordinators = {}
        runtime.coordinator.config_entry.data = {"cloud_only": False}
        runtime.coordinator.config_entry.options = {}
        runtime.coordinator.data = {
            "devices": {
                "dev-1": {
                    "device_id": "dev-1",
                    "pairing": {"deviceId": "dev-1", "ip": ip},
                    "reported": {},
                    "additional": {"static_ip": ip},
                }
            },
            "pairings": [{"deviceId": "dev-1", "ip": ip}],
        }

        session = ClientSession()
        try:
            with (
                aioresponses() as m,
                patch(
                    "custom_components.v2c_cloud.local_api.async_get_clientsession",
                    return_value=session,
                ),
            ):
                # Two refreshes are issued (creation + explicit one below).
                for _ in range(2):
                    m.get(
                        f"http://{ip}/RealTimeData",
                        status=200,
                        body='{"ChargeState":2,"IntensityMeasure_L1y":6,'
                        '"VoltageMeasure_L1":231}',
                    )
                coordinator = await async_get_or_create_local_coordinator(
                    MagicMock(), runtime, "dev-1"
                )
                await coordinator.async_refresh()
        finally:
            await session.close()

        assert coordinator.data["IntensityMeasure_L1"] == 6
        assert coordinator.data["VoltageMeasure_L1"] == 231
        # The lowercase index is built after normalisation, so entity lookups
        # resolve the documented spelling too.
        assert "intensitymeasure_l1" in coordinator.data["_lower_index"]


# ---------------------------------------------------------------------------
# program_timer service handler
# ---------------------------------------------------------------------------


class TestProgramTimerService:
    """Handler wiring: days default, pass-through and `active` deprecation."""

    def _register(self, client):
        """Register services against a mock hass and return the handler map."""
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_register_services,
        )
        from custom_components.v2c_cloud.const import DOMAIN

        runtime = MagicMock(spec=V2CEntryRuntimeData)
        runtime.client = client
        runtime.coordinator = MagicMock()
        runtime.coordinator.data = {"devices": {DEVICE_ID: {}}}
        runtime.coordinator.async_request_refresh = AsyncMock(return_value=None)

        hass = MagicMock()
        hass.services.has_service.return_value = False
        hass.data = {DOMAIN: {"entry-1": runtime}}

        _async_register_services(hass)

        handlers = {}
        schemas = {}
        for call in hass.services.async_register.call_args_list:
            _domain, name, handler = call.args[:3]
            handlers[name] = handler
            schemas[name] = call.kwargs.get("schema")
        return handlers, schemas

    async def _call(self, data):
        client = MagicMock()
        client.async_program_timer = AsyncMock(return_value=None)
        handlers, _ = self._register(client)
        call = MagicMock()
        call.data = data
        await handlers["program_timer"](call)
        return client.async_program_timer

    async def test_days_default_when_field_omitted(self):
        called = await self._call(
            {
                "device_id": DEVICE_ID,
                "timer_id": 1,
                "start_time": "22:00",
                "end_time": "06:00",
            }
        )
        assert called.await_args.kwargs["days_of_week"] == DEFAULT_TIMER_DAYS

    async def test_days_passed_through(self):
        called = await self._call(
            {
                "device_id": DEVICE_ID,
                "timer_id": 0,
                "start_time": "22:00",
                "end_time": "06:00",
                "days_of_week": "67",
            }
        )
        assert called.await_args.kwargs["days_of_week"] == "67"
        assert "active" not in called.await_args.kwargs

    async def test_active_is_ignored_and_warns(self, caplog):
        with caplog.at_level("WARNING"):
            called = await self._call(
                {
                    "device_id": DEVICE_ID,
                    "timer_id": 1,
                    "start_time": "22:00",
                    "end_time": "06:00",
                    "active": False,
                }
            )
        assert "active" not in called.await_args.kwargs
        assert "deprecated" in caplog.text

    def test_schema_declares_days_with_default(self):
        """
        The service schema accepts `days_of_week` and defaults it.

        Rejection of malformed day strings is NOT asserted here: the schema
        delegates it to `cv.matches_regex`, and Home Assistant's
        config_validation module is stubbed in this test harness so any value
        would pass. The enforced rejection is covered where it actually
        protects the request — see TestTimerBodyConformance.
        """
        _, schemas = self._register(MagicMock())
        schema = schemas["program_timer"]
        base = {
            "device_id": DEVICE_ID,
            "timer_id": 1,
            "start_time": "22:00",
            "end_time": "06:00",
        }
        assert schema({**base, "days_of_week": "1234567"})
        assert schema(base)["days_of_week"] == DEFAULT_TIMER_DAYS
        assert "active" not in schema(base)
