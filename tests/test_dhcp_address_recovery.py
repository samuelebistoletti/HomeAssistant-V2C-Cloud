"""
Recovery when the charger's LAN address changes under it.

A Trydan on DHCP can be handed a new address at any time. Before these tests
the integration could not notice: `resolve_static_ip` ranked cloud-advertised
addresses above everything the LAN had actually proven, and the poll only ever
tried the single best-ranked address. So a lease change stranded a healthy LAN
install on a dead address — the poll hammered the old one, fell back to cloud
data, and stayed there until a human typed the new address into the options.

Worse, the self-healing that did exist was defeated by the ordering:
`_persist_lan_observed_ip` writes a proven address into `cached_pairings`,
which sits BELOW the stale cloud value, so the proof was recorded and then
immediately outranked on the next poll.

These tests pin the two properties that fix it: evidence outranks hearsay when
choosing an address, and a failing poll tries the other addresses it knows
before giving up on the LAN.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.v2c_cloud.const import (
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_MANUAL_IPS,
)
from custom_components.v2c_cloud.local_api import (
    candidate_ips,
    describe_ip_source,
    resolve_static_ip,
)

DEVICE_ID = "XQUXDU"
# The live addresses from the incident this test file was written for: the
# charger moved from .60 to .50 and the integration kept calling .60.
STALE_IP = "10.35.0.60"
LIVE_IP = "10.35.0.50"
THIRD_IP = "10.35.0.77"

REALTIME_BODY = '{"ChargeState":2,"ChargePower":7360,"Intensity":32}'


@pytest.fixture(autouse=True)
def no_sleep():
    """Disable real sleeps so retry backoff is instantaneous."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


def _runtime(
    *,
    entry_data: dict[str, Any] | None = None,
    coordinator_data: Any = None,
    local_data: Any = None,
) -> MagicMock:
    """Build a runtime-data double with a mappingproxy ``entry.data``."""
    runtime = MagicMock()
    runtime.coordinator.config_entry.data = MappingProxyType(dict(entry_data or {}))
    runtime.coordinator.config_entry.options = {}
    runtime.coordinator.data = coordinator_data
    if local_data is None:
        runtime.local_coordinators = {}
    else:
        local = MagicMock()
        local.data = local_data
        runtime.local_coordinators = {DEVICE_ID: local}
    return runtime


# ---------------------------------------------------------------------------
# Which address wins
# ---------------------------------------------------------------------------


class TestLanVerifiedOutranksCloud:
    """An address that answered on the LAN beats one the cloud merely claims."""

    def test_proven_address_beats_stale_cloud_static_ip(self):
        runtime = _runtime(
            coordinator_data={
                "devices": {DEVICE_ID: {"additional": {"static_ip": STALE_IP}}}
            },
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LIVE_IP
        assert describe_ip_source(runtime, DEVICE_ID) == (LIVE_IP, "lan")

    def test_proven_address_beats_stale_cached_pairing(self):
        runtime = _runtime(
            entry_data={
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": STALE_IP}]
            },
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LIVE_IP

    def test_manual_override_still_outranks_a_proven_address(self):
        """The user's explicit choice is a decision, not a guess to be improved."""
        runtime = _runtime(
            entry_data={CONF_MANUAL_IPS: {DEVICE_ID: STALE_IP}},
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == STALE_IP
        assert describe_ip_source(runtime, DEVICE_ID) == (STALE_IP, "manual")

    def test_cloud_synthesised_payload_is_not_evidence(self):
        """
        A synthesised payload carries an address the cloud supplied, not one
        the LAN proved. Promoting it would make the cloud outrank itself.
        """
        runtime = _runtime(
            coordinator_data={
                "devices": {DEVICE_ID: {"additional": {"static_ip": STALE_IP}}}
            },
            local_data={
                "_data_source": "cloud_reported",
                "IP": LIVE_IP,
                "_static_ip": LIVE_IP,
            },
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == STALE_IP
        assert describe_ip_source(runtime, DEVICE_ID)[1] == "cloud"


class TestChargerSelfReportBeatsPortalField:
    """Inside the cloud payload, the charger's own report is the fresher one."""

    def test_reported_ip_wins_over_additional_static_ip(self):
        runtime = _runtime(
            coordinator_data={
                "devices": {
                    DEVICE_ID: {
                        "additional": {"static_ip": STALE_IP},
                        "reported": {"ip": LIVE_IP},
                    }
                }
            }
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == LIVE_IP

    def test_additional_static_ip_still_used_when_nothing_reported(self):
        runtime = _runtime(
            coordinator_data={
                "devices": {
                    DEVICE_ID: {"additional": {"static_ip": STALE_IP}, "reported": {}}
                }
            }
        )
        assert resolve_static_ip(runtime, DEVICE_ID) == STALE_IP


# ---------------------------------------------------------------------------
# The candidate list
# ---------------------------------------------------------------------------


class TestCandidateIps:
    """What the poll is allowed to try, and in what order."""

    def test_manual_override_is_returned_alone(self):
        """
        Pinning an address is a statement about where the charger must be.
        Succeeding quietly at some other address would hide the mistake the
        override exists to make visible.
        """
        runtime = _runtime(
            entry_data={
                CONF_MANUAL_IPS: {DEVICE_ID: STALE_IP},
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            },
            coordinator_data={"devices": {DEVICE_ID: {"reported": {"ip": THIRD_IP}}}},
        )
        assert candidate_ips(runtime, DEVICE_ID) == [STALE_IP]

    def test_every_known_address_is_offered_best_first(self):
        runtime = _runtime(
            entry_data={
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": THIRD_IP}]
            },
            coordinator_data={"devices": {DEVICE_ID: {"reported": {"ip": STALE_IP}}}},
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert candidate_ips(runtime, DEVICE_ID) == [LIVE_IP, STALE_IP, THIRD_IP]

    def test_duplicates_collapse(self):
        runtime = _runtime(
            entry_data={CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}]},
            coordinator_data={"devices": {DEVICE_ID: {"reported": {"ip": LIVE_IP}}}},
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert candidate_ips(runtime, DEVICE_ID) == [LIVE_IP]

    def test_non_routable_candidates_are_dropped(self):
        """The SSRF guard applies to every candidate, not just the first."""
        runtime = _runtime(
            entry_data={
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": "8.8.8.8"}]
            },
            coordinator_data={
                "devices": {DEVICE_ID: {"reported": {"ip": "127.0.0.1"}}}
            },
            local_data={"_static_ip": LIVE_IP, "ChargeState": 2},
        )
        assert candidate_ips(runtime, DEVICE_ID) == [LIVE_IP]

    def test_unsafe_manual_override_yields_nothing(self):
        runtime = _runtime(
            entry_data={
                CONF_MANUAL_IPS: {DEVICE_ID: "169.254.1.1"},
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            }
        )
        assert candidate_ips(runtime, DEVICE_ID) == []

    def test_no_addresses_at_all(self):
        assert candidate_ips(_runtime(), DEVICE_ID) == []


# ---------------------------------------------------------------------------
# The poll actually finding the charger again
# ---------------------------------------------------------------------------


class TestPollRecoversFromAddressChange:
    """Drive the real coordinator against a charger that has moved."""

    async def _coordinator(
        self, *, entry_data, serve: dict[str, str], cloud_ip: str | None = None
    ):
        """
        Build a real local coordinator.

        ``serve`` maps address -> response body; any address outside it
        refuses the connection, which is what a vacated DHCP lease looks like.
        ``cloud_ip`` is what the cloud claims, which outranks the cache — the
        two sources are how a poll ends up with more than one candidate, since
        the pairings cache only ever holds one address per charger.
        """
        from aiohttp import ClientSession
        from aioresponses import aioresponses

        from custom_components.v2c_cloud.local_api import (
            async_get_or_create_local_coordinator,
        )

        reported = {"ip": cloud_ip} if cloud_ip else {}
        runtime = _runtime(
            entry_data=entry_data,
            coordinator_data={"devices": {DEVICE_ID: {"reported": reported}}},
        )

        session = ClientSession()
        try:
            with (
                aioresponses() as m,
                patch(
                    "custom_components.v2c_cloud.local_api.async_get_clientsession",
                    return_value=session,
                ),
                patch(
                    "custom_components.v2c_cloud.local_api._persist_lan_observed_ip"
                ) as persist,
            ):
                for ip, body in serve.items():
                    m.get(
                        f"http://{ip}/RealTimeData",
                        status=200,
                        body=body,
                        repeat=True,
                    )
                coordinator = await async_get_or_create_local_coordinator(
                    MagicMock(), runtime, DEVICE_ID
                )
        finally:
            await session.close()
        return runtime, coordinator, persist

    async def test_falls_through_to_the_address_that_answers(self):
        """The headline case: the cloud's address is dead, the cache's works."""
        _runtime_data, coordinator, persist = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            },
            cloud_ip=STALE_IP,
            serve={LIVE_IP: REALTIME_BODY},
        )

        assert coordinator.data["ChargeState"] == 2
        assert coordinator.data["_static_ip"] == LIVE_IP
        # Real charger data, not a cloud-synthesised stand-in.
        assert "_data_source" not in coordinator.data
        # The address that worked is persisted, so the next poll starts there.
        assert persist.call_args[0][3] == LIVE_IP

    async def test_a_stranger_on_the_old_lease_is_not_adopted(self):
        """
        Another device may now hold the vacated address and answer with JSON.
        Anything that is not a RealTimeData document must be refused, even
        when it is the best-ranked candidate.
        """
        _runtime_data, coordinator, persist = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            },
            cloud_ip=STALE_IP,
            # .60 is now somebody's NAS; only .50 is the charger.
            serve={
                STALE_IP: '{"hostname":"nas","uptime":41}',
                LIVE_IP: REALTIME_BODY,
            },
        )

        assert coordinator.data["_static_ip"] == LIVE_IP
        assert "hostname" not in coordinator.data
        assert persist.call_args[0][3] == LIVE_IP

    async def test_a_pinned_address_is_never_abandoned(self):
        """
        With a manual override the poll must fail visibly rather than wander
        onto a different host — the override is the user's assertion.
        """
        _runtime_data, coordinator, persist = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: False,
                CONF_MANUAL_IPS: {DEVICE_ID: STALE_IP},
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            },
            serve={LIVE_IP: REALTIME_BODY},
        )

        # Never talked to .50, so nothing was proven and nothing persisted.
        assert persist.call_count == 0
        assert coordinator.data is None

    async def test_single_known_address_behaves_as_before(self):
        """The ordinary one-address install is untouched by candidate search."""
        _runtime_data, coordinator, persist = await self._coordinator(
            entry_data={
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LIVE_IP}],
            },
            serve={LIVE_IP: REALTIME_BODY},
        )

        assert coordinator.data["ChargeState"] == 2
        assert persist.call_args[0][3] == LIVE_IP
