"""
Resilience of a LAN entry to a total V2C Cloud outage (issue #54).

The V2C Cloud rejected valid API keys for days. Every LAN install went dark
with it, because:

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

from typing import Any
from unittest.mock import MagicMock

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
from custom_components.v2c_cloud.local_api import manual_ip_for, resolve_static_ip

DEVICE_ID = "XQUXDU"
LAN_IP = "192.168.1.50"
OTHER_IP = "192.168.1.77"


def _entry(**data: Any) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.title = "V2C Cloud"
    entry.data = data
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
