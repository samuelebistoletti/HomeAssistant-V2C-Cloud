"""
Resilience of a LAN entry to a total V2C Cloud outage.

If the V2C Cloud rejects valid API keys for an extended period, every LAN
install used to go dark with it, because:

* an authentication failure raised `ConfigEntryAuthFailed` unconditionally, so
  the entry was torn down even though the charger was reachable over HTTP; and
* every source `resolve_static_ip` consulted was derived from live cloud data,
  so with the cloud down the integration no longer knew where the charger was
  and silently behaved as if the entry were cloud-only.

These tests pin the opposite behaviour: a LAN entry with a known address keeps
working and only raises a repair issue, while a cloud-only (4G) entry — which
genuinely has no second transport — still asks for reauthentication.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.v2c_cloud import (
    _async_clear_cloud_auth_degraded,
    _async_flag_cloud_auth_degraded,
    _lan_addressable_records,
    _may_degrade_to_lan,
)
from custom_components.v2c_cloud.const import (
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_MANUAL_IPS,
    DOMAIN,
    ISSUE_CLOUD_AUTH_DEGRADED,
)
from custom_components.v2c_cloud.local_api import (
    active_transport,
    describe_ip_source,
    manual_ip_for,
    payload_is_empty,
    resolve_static_ip,
)

DEVICE_ID = "XQUXDU"
LAN_IP = "192.168.1.50"
OTHER_IP = "192.168.1.77"


def _entry(**data: Any) -> MagicMock:
    """
    Build a config-entry double whose ``data`` is a MappingProxyType.

    Home Assistant exposes ``entry.data`` as a mappingproxy, which is a Mapping
    but NOT a dict subclass. Doubles that hand back a plain dict hide type
    errors that break every live instance — that is exactly how an
    ``isinstance(data, dict)`` guard shipped in 1.4.0-beta.2 and silently
    discarded the manual IP overrides and the cached address book.
    """
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.title = "V2C Cloud"
    entry.data = MappingProxyType(dict(data))
    return entry


def _runtime(
    *,
    entry_data: dict[str, Any] | None = None,
    coordinator_data: Any = None,
    local_data: Any = None,
) -> MagicMock:
    runtime = MagicMock()
    runtime.coordinator.config_entry = _entry(**(entry_data or {}))
    runtime.coordinator.data = coordinator_data
    if local_data is None:
        runtime.local_coordinators = {}
    else:
        local = MagicMock()
        local.data = local_data
        runtime.local_coordinators = {DEVICE_ID: local}
    return runtime


# ---------------------------------------------------------------------------
# Address resolution without any cloud data
# ---------------------------------------------------------------------------


class TestAddressSurvivesCloudOutage:
    """With zero cloud data the LAN address must still be resolvable."""

    def test_cached_pairings_are_used(self):
        runtime = _runtime(
            entry_data={CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}]},
            coordinator_data=None,
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP

    def test_manual_override_is_used(self):
        runtime = _runtime(
            entry_data={CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}}, coordinator_data=None
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP
        assert manual_ip_for(runtime, DEVICE_ID) == LAN_IP

    def test_manual_override_beats_cloud_and_cache(self):
        """The user's explicit address wins over everything else."""
        runtime = _runtime(
            entry_data={
                CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP},
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": OTHER_IP}],
            },
            coordinator_data={
                "devices": {DEVICE_ID: {"additional": {"static_ip": OTHER_IP}}},
                "pairings": [{"deviceId": DEVICE_ID, "ip": OTHER_IP}],
            },
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP

    def test_cloud_beats_cache_when_both_present(self):
        """Live cloud data is fresher than the persisted snapshot."""
        runtime = _runtime(
            entry_data={
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": OTHER_IP}]
            },
            coordinator_data={
                "devices": {DEVICE_ID: {"additional": {"static_ip": LAN_IP}}}
            },
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP

    def test_unknown_device_resolves_to_none(self):
        runtime = _runtime(
            entry_data={CONF_CACHED_PAIRINGS: [{"deviceId": "OTHER", "ip": LAN_IP}]},
            coordinator_data=None,
        )
        assert resolve_static_ip(runtime, DEVICE_ID) is None

    def test_malformed_entry_data_does_not_raise(self):
        runtime = _runtime(
            entry_data={CONF_MANUAL_IPS: "not-a-dict", CONF_CACHED_PAIRINGS: [None, 5]},
            coordinator_data=None,
        )
        assert resolve_static_ip(runtime, DEVICE_ID) is None


# ---------------------------------------------------------------------------
# Degrade vs. tear down
# ---------------------------------------------------------------------------


class TestDegradeDecision:
    """Who may keep running when the cloud refuses to authenticate."""

    def test_lan_entry_with_cached_address_may_degrade(self):
        entry = _entry(
            **{CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}]}
        )
        assert _may_degrade_to_lan(entry) is True

    def test_lan_entry_with_manual_address_may_degrade(self):
        entry = _entry(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})
        assert _may_degrade_to_lan(entry) is True

    def test_cloud_only_entry_may_not_degrade(self):
        """A 4G charger has no second transport — it must still reauth."""
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            }
        )
        assert _may_degrade_to_lan(entry) is False

    def test_lan_entry_without_any_address_may_not_degrade(self):
        entry = _entry(**{CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": ""}]})
        assert _may_degrade_to_lan(entry) is False

    def test_records_merge_cache_and_overrides(self):
        entry = _entry(
            **{
                CONF_CACHED_PAIRINGS: [
                    {"deviceId": DEVICE_ID, "ip": OTHER_IP},
                    {"deviceId": "SECOND", "ip": LAN_IP},
                ],
                CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP},
            }
        )
        records = {r["deviceId"]: r["ip"] for r in _lan_addressable_records(entry)}
        assert records == {DEVICE_ID: LAN_IP, "SECOND": LAN_IP}


# ---------------------------------------------------------------------------
# Repair issue instead of a reauth storm
# ---------------------------------------------------------------------------


class TestDegradedRepairIssue:
    """The user is told, without the entry being unloaded."""

    def _reset(self) -> None:
        ir.created_issues.clear()
        ir.deleted_issues.clear()

    def test_issue_is_raised_and_cleared(self):
        self._reset()
        hass = MagicMock()
        entry = _entry(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})

        _async_flag_cloud_auth_degraded(hass, entry)
        key = (DOMAIN, f"{ISSUE_CLOUD_AUTH_DEGRADED}_{entry.entry_id}")
        assert key in ir.created_issues
        assert ir.created_issues[key]["translation_key"] == ISSUE_CLOUD_AUTH_DEGRADED
        assert ir.created_issues[key]["severity"] == ir.IssueSeverity.WARNING

        _async_clear_cloud_auth_degraded(hass, entry)
        assert key not in ir.created_issues
        assert key in ir.deleted_issues

    def test_issue_id_is_scoped_per_entry(self):
        self._reset()
        hass = MagicMock()
        first = _entry(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})
        second = _entry(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})
        second.entry_id = "entry-2"

        _async_flag_cloud_auth_degraded(hass, first)
        _async_flag_cloud_auth_degraded(hass, second)

        assert len(ir.created_issues) == 2


# ---------------------------------------------------------------------------
# End-to-end outage simulation
# ---------------------------------------------------------------------------


class TestOutageSimulation:
    """The three combinations that matter, driven through the real coordinator."""

    async def _coordinator(self, *, entry_data, lan_serves: bool):
        """Build a real local coordinator; `lan_serves` decides if HTTP answers."""
        from aiohttp import ClientSession
        from aioresponses import aioresponses

        from custom_components.v2c_cloud.local_api import (
            async_get_or_create_local_coordinator,
        )

        runtime = MagicMock()
        runtime.local_coordinators = {}
        runtime.coordinator.config_entry.data = entry_data
        runtime.coordinator.config_entry.options = {}
        runtime.coordinator.data = {"devices": {DEVICE_ID: {"reported": {}}}}

        session = ClientSession()
        try:
            with (
                aioresponses() as m,
                patch(
                    "custom_components.v2c_cloud.local_api.async_get_clientsession",
                    return_value=session,
                ),
                patch("custom_components.v2c_cloud.local_api._persist_lan_observed_ip"),
            ):
                if lan_serves:
                    m.get(
                        f"http://{LAN_IP}/RealTimeData",
                        status=200,
                        body='{"ChargeState":2,"ChargePower":7360,"Intensity":32}',
                        repeat=True,
                    )
                coordinator = await async_get_or_create_local_coordinator(
                    MagicMock(), runtime, DEVICE_ID
                )
        finally:
            await session.close()
        return runtime, coordinator

    async def test_cloud_down_but_lan_reachable_keeps_real_data(self):
        """The headline case: cloud dead, charger on Wi-Fi, entities alive."""
        runtime, coordinator = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            },
            lan_serves=True,
        )

        assert coordinator.data["ChargeState"] == 2
        assert coordinator.data["ChargePower"] == 7360
        # The payload came off the charger, not from cloud synthesis.
        assert "_data_source" not in coordinator.data
        assert active_transport(runtime, DEVICE_ID) == "lan"

    async def test_manual_override_alone_is_enough(self):
        """No cache, no cloud — just the address the user typed."""
        runtime, coordinator = await self._coordinator(
            entry_data={CONF_CLOUD_ONLY: False, CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}},
            lan_serves=True,
        )

        assert coordinator.data["Intensity"] == 32
        assert active_transport(runtime, DEVICE_ID) == "lan"
        assert describe_ip_source(runtime, DEVICE_ID) == (LAN_IP, "manual")

    async def test_cloud_down_and_no_address_reports_offline(self):
        """Nothing to talk to: say so, instead of a wall of Unknown."""
        runtime, coordinator = await self._coordinator(
            entry_data={CONF_CLOUD_ONLY: False},
            lan_serves=False,
        )

        assert payload_is_empty(coordinator.data)
        assert active_transport(runtime, DEVICE_ID) == "offline"
        assert describe_ip_source(runtime, DEVICE_ID) == (None, None)

    async def test_lan_entry_keeps_lan_cadence_without_an_address(self):
        """A LAN entry must not be demoted to the cloud-only poll interval."""
        from custom_components.v2c_cloud.const import CLOUD_ONLY_UPDATE_INTERVAL

        _, coordinator = await self._coordinator(
            entry_data={CONF_CLOUD_ONLY: False},
            lan_serves=False,
        )
        assert coordinator.update_interval != CLOUD_ONLY_UPDATE_INTERVAL

    async def test_cloud_only_entry_uses_cloud_cadence(self):
        """A 4G entry is unaffected by any of this."""
        from custom_components.v2c_cloud.const import CLOUD_ONLY_UPDATE_INTERVAL

        _, coordinator = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            },
            lan_serves=False,
        )
        assert coordinator.update_interval == CLOUD_ONLY_UPDATE_INTERVAL


class TestAvailabilitySemantics:
    """Unavailable means "cannot exist", Unknown means "value not reported"."""

    def _sensor(self, *, key: str, data: Any, cloud_only: bool = False):
        from custom_components.v2c_cloud.sensor import (
            REALTIME_SENSOR_DESCRIPTIONS,
            V2CLocalRealtimeSensor,
        )

        description = next(d for d in REALTIME_SENSOR_DESCRIPTIONS if d.key == key)
        sensor = V2CLocalRealtimeSensor.__new__(V2CLocalRealtimeSensor)
        sensor.entity_description = description
        runtime = MagicMock()
        runtime.cloud_only = cloud_only
        sensor._runtime_data = runtime
        coordinator = MagicMock()
        coordinator.data = data
        coordinator.last_update_success = True
        sensor.coordinator = coordinator
        return sensor

    def test_empty_payload_is_unavailable_not_unknown(self):
        sensor = self._sensor(
            key="ChargePower", data={"_data_source": "cloud_reported_empty"}
        )
        assert sensor.available is False

    def test_lan_only_key_unavailable_while_synthesised(self):
        sensor = self._sensor(
            key="SignalStatus", data={"_data_source": "cloud_reported", "Intensity": 6}
        )
        assert sensor.available is False

    def test_cloud_backed_key_stays_available_while_synthesised(self):
        sensor = self._sensor(
            key="ChargePower",
            data={"_data_source": "cloud_reported", "ChargePower": 10},
        )
        assert sensor.available is True

    def test_real_lan_payload_keeps_lan_only_keys_available(self):
        sensor = self._sensor(key="SignalStatus", data={"SignalStatus": 3})
        assert sensor.available is True


class TestEntryDataIsReadThroughMappingProxy:
    """
    Home Assistant hands out ``entry.data`` as a mappingproxy, not a dict.

    Regression cover for 1.4.0-beta.2, where an ``isinstance(data, dict)``
    guard made the integration ignore both the manual overrides and the cached
    address book on every real instance while the suite stayed green.
    """

    def _runtime_with_proxy(self, **data: Any) -> MagicMock:
        runtime = MagicMock()
        runtime.coordinator.config_entry.data = MappingProxyType(dict(data))
        runtime.coordinator.data = None
        runtime.local_coordinators = {}
        return runtime

    def test_manual_override_is_read_from_a_mappingproxy(self):
        runtime = self._runtime_with_proxy(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP

    def test_cached_pairings_are_read_from_a_mappingproxy(self):
        runtime = self._runtime_with_proxy(
            **{CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}]}
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP

    def test_transport_reports_the_source_from_a_mappingproxy(self):
        runtime = self._runtime_with_proxy(**{CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}})
        assert describe_ip_source(runtime, DEVICE_ID) == (LAN_IP, "manual")

    def test_a_plain_dict_keeps_working_too(self):
        """Other callers (and older HA versions) may still pass a real dict."""
        runtime = MagicMock()
        runtime.coordinator.config_entry.data = {CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP}}
        runtime.coordinator.data = None
        runtime.local_coordinators = {}
        assert resolve_static_ip(runtime, DEVICE_ID) == LAN_IP


class TestRejectedKeyIsReportedNotSwallowed:
    """
    A command that cannot be delivered must say so, in words.

    The cloud answers a rejected key with an empty-bodied 401, so the raw
    exception reads "V2C authentication failed: " and nothing more. Pressing
    the OCPP switch while the cloud is unauthenticated used to put that, plus
    a traceback, in the log and leave the UI with no explanation at all.
    """

    async def test_entity_command_raises_a_readable_error(self) -> None:
        from unittest.mock import AsyncMock

        from homeassistant.exceptions import HomeAssistantError

        from custom_components.v2c_cloud.entity import V2CEntity
        from custom_components.v2c_cloud.v2c_cloud import V2CAuthError

        entity = V2CEntity.__new__(V2CEntity)
        entity.coordinator = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()

        async def _rejected() -> None:
            raise V2CAuthError("V2C authentication failed: ")

        try:
            await entity._async_call_and_refresh(_rejected())
        except HomeAssistantError as err:
            message = str(err)
        else:
            raise AssertionError("a rejected key must surface as an error")

        assert "rejected the API key" in message
        assert "local network" in message

    async def test_failed_command_tells_the_coordinator(self) -> None:
        """
        The command proved the cloud is unauthenticated — don't wait for a poll.

        Without this, the cloud-only controls stayed available until the next
        scheduled refresh independently rediscovered what the command had
        already established. The coordinator is asked to refresh rather than
        being told what to conclude: degrade-to-LAN versus ask-for-a-new-key
        depends on the entry, and that decision lives in one place.
        """
        from unittest.mock import AsyncMock

        from homeassistant.exceptions import HomeAssistantError

        from custom_components.v2c_cloud.entity import V2CEntity
        from custom_components.v2c_cloud.v2c_cloud import V2CAuthError

        entity = V2CEntity.__new__(V2CEntity)
        entity.coordinator = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()

        async def _rejected() -> None:
            raise V2CAuthError("401")

        with pytest.raises(HomeAssistantError):
            await entity._async_call_and_refresh(_rejected())

        entity.coordinator.async_request_refresh.assert_awaited_once()

    async def test_successful_command_still_refreshes(self) -> None:
        from unittest.mock import AsyncMock

        from custom_components.v2c_cloud.entity import V2CEntity

        entity = V2CEntity.__new__(V2CEntity)
        entity.coordinator = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()

        async def _ok() -> None:
            return None

        await entity._async_call_and_refresh(_ok())
        entity.coordinator.async_request_refresh.assert_awaited_once()
