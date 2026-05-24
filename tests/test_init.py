"""Tests for async_setup_entry coordinator setup and fallback behaviour."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.v2c_cloud.const import DOMAIN
from custom_components.v2c_cloud.v2c_cloud import V2CAuthError, V2CRateLimitError

DEVICE_ID = "device-abc123"
FALLBACK_IP = "192.168.1.50"
API_KEY = "test-api-key"
ENTRY_ID = "entry-xyz"

SAMPLE_PAIRING: dict[str, Any] = {"deviceId": DEVICE_ID}
SAMPLE_DEVICES: dict[str, Any] = {
    DEVICE_ID: {
        "device_id": DEVICE_ID,
        "pairing": SAMPLE_PAIRING,
        "connected": True,
        "current_state": {},
        "reported_raw": {},
        "reported": {},
        "rfid_cards": [],
        "version": "1.0",
        "additional": {"static_ip": FALLBACK_IP},
    }
}


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    # Return True so _async_register_services exits early (already registered)
    hass.services.has_service.return_value = True
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
    return hass


def _make_entry(*, fallback: bool = False) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.version = 2
    data: dict[str, Any] = {"api_key": API_KEY, "cloud_only": False}
    if fallback:
        data["cached_pairings"] = [{"deviceId": DEVICE_ID, "ip": FALLBACK_IP}]
    entry.data = data
    return entry


def _make_client(
    *,
    pairings_side_effect: Exception | None = None,
    pairings_return: list | None = None,
) -> MagicMock:
    client = MagicMock()
    if pairings_side_effect is not None:
        client.async_get_pairings = AsyncMock(side_effect=pairings_side_effect)
    else:
        client.async_get_pairings = AsyncMock(
            return_value=pairings_return
            if pairings_return is not None
            else [SAMPLE_PAIRING]
        )
    client.last_rate_limit = None
    client.preload_pairings = MagicMock()
    return client


def _patch_setup(mock_client: MagicMock, *, gather_return: dict | None = None):
    """Return a context manager patching the three external dependencies of async_setup_entry."""
    from contextlib import ExitStack

    stack = ExitStack()

    def _enter():
        stack.enter_context(
            patch("custom_components.v2c_cloud.__init__.async_get_clientsession")
        )
        stack.enter_context(
            patch(
                "custom_components.v2c_cloud.__init__.V2CClient",
                return_value=mock_client,
            )
        )
        stack.enter_context(
            patch(
                "custom_components.v2c_cloud.__init__.async_gather_devices_state",
                AsyncMock(return_value=gather_return or SAMPLE_DEVICES),
            )
        )
        return stack

    class _CM:
        def __enter__(self):
            return _enter()

        def __exit__(self, *args):
            return stack.__exit__(*args)

    return _CM()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoordinatorStartup:
    """Coordinator initialisation scenarios in async_setup_entry."""

    async def test_normal_startup_populates_coordinator_data(self):
        """Happy path: coordinator data contains the device returned by the API."""
        from custom_components.v2c_cloud.__init__ import async_setup_entry

        hass = _make_hass()
        entry = _make_entry()
        client = _make_client()

        with _patch_setup(client):
            result = await async_setup_entry(hass, entry)

        assert result is True
        runtime = hass.data[DOMAIN][ENTRY_ID]
        assert runtime.coordinator.data is not None
        assert DEVICE_ID in runtime.coordinator.data["devices"]

    async def test_rate_limit_no_fallback_raises_config_entry_not_ready(self):
        """With no LAN fallback, a rate-limit at startup prevents integration load."""
        from custom_components.v2c_cloud.__init__ import async_setup_entry

        hass = _make_hass()
        entry = _make_entry(fallback=False)
        client = _make_client(pairings_side_effect=V2CRateLimitError("429", status=429))

        with _patch_setup(client):
            with pytest.raises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)

    async def test_rate_limit_with_fallback_loads_synthetic_data(self):
        """With LAN fallback configured, a rate-limit at startup succeeds with synthetic state."""
        from custom_components.v2c_cloud.__init__ import async_setup_entry

        hass = _make_hass()
        entry = _make_entry(fallback=True)
        client = _make_client(pairings_side_effect=V2CRateLimitError("429", status=429))

        with _patch_setup(client):
            result = await async_setup_entry(hass, entry)

        assert result is True
        runtime = hass.data[DOMAIN][ENTRY_ID]
        devices = runtime.coordinator.data["devices"]
        assert DEVICE_ID in devices
        # Synthetic state: no real cloud data yet
        assert devices[DEVICE_ID]["connected"] is None
        assert devices[DEVICE_ID]["reported"] == {}
        assert devices[DEVICE_ID]["additional"]["static_ip"] == FALLBACK_IP
        # Pairings list is also present
        pairings = runtime.coordinator.data["pairings"]
        assert len(pairings) == 1
        assert pairings[0]["deviceId"] == DEVICE_ID

    async def test_rate_limit_with_existing_data_preserves_previous(self):
        """During a running poll, a rate-limit keeps the last known coordinator data intact."""
        from custom_components.v2c_cloud.__init__ import async_setup_entry

        hass = _make_hass()
        entry = _make_entry(fallback=False)
        client = _make_client()

        with _patch_setup(client):
            await async_setup_entry(hass, entry)

        runtime = hass.data[DOMAIN][ENTRY_ID]
        original_data = runtime.coordinator.data
        assert original_data is not None

        # Simulate rate-limit on next polling cycle
        client.async_get_pairings.side_effect = V2CRateLimitError("429", status=429)
        await runtime.coordinator.async_refresh()

        assert runtime.coordinator.data is original_data

    async def test_rate_limit_doubles_coordinator_interval(self):
        """Each rate-limit cycle doubles the polling interval up to MAX_RATE_LIMIT_INTERVAL."""

        from custom_components.v2c_cloud.__init__ import async_setup_entry
        from custom_components.v2c_cloud.const import (
            DEFAULT_UPDATE_INTERVAL,
            MAX_RATE_LIMIT_INTERVAL,
        )

        hass = _make_hass()
        entry = _make_entry(fallback=True)
        client = _make_client()

        with _patch_setup(client):
            await async_setup_entry(hass, entry)

        runtime = hass.data[DOMAIN][ENTRY_ID]
        # After the first refresh, the coordinator recalculates the interval based
        # on the device count and the daily-budget formula (2 calls per device per
        # cycle). With one device the result (~204 s) exceeds DEFAULT (120 s); the
        # exact value depends on device count, so we just assert it is *at least*
        # DEFAULT and then verify the doubling behaviour relative to that.
        starting_interval = runtime.coordinator.update_interval
        assert starting_interval >= DEFAULT_UPDATE_INTERVAL

        client.async_get_pairings.side_effect = V2CRateLimitError("429", status=429)

        # First rate-limit: interval doubles relative to whatever it currently is
        await runtime.coordinator.async_refresh()
        first_backoff = runtime.coordinator.update_interval
        assert first_backoff == min(starting_interval * 2, MAX_RATE_LIMIT_INTERVAL)

        # Repeated rate-limits keep doubling, still capped
        await runtime.coordinator.async_refresh()
        assert runtime.coordinator.update_interval == min(
            first_backoff * 2, MAX_RATE_LIMIT_INTERVAL
        )

        # Eventually pinned at MAX_RATE_LIMIT_INTERVAL
        for _ in range(10):
            await runtime.coordinator.async_refresh()
        assert runtime.coordinator.update_interval == MAX_RATE_LIMIT_INTERVAL

    async def test_rate_limit_pacing_on_low_remaining(self):
        """When RateLimit-Remaining drops below threshold, the interval stretches to pace calls."""
        import math
        from datetime import timedelta

        from custom_components.v2c_cloud.__init__ import async_setup_entry
        from custom_components.v2c_cloud.const import RATE_LIMIT_COMMAND_RESERVE

        hass = _make_hass()
        entry = _make_entry(fallback=False)
        client = _make_client()

        remaining = 80  # below RATE_LIMIT_LOW_THRESHOLD (150)
        client.last_rate_limit = {"limit": 1000, "remaining": remaining, "reset": None}

        with _patch_setup(client):
            await async_setup_entry(hass, entry)

        runtime = hass.data[DOMAIN][ENTRY_ID]

        # Trigger a successful poll that reads the low remaining value
        await runtime.coordinator.async_refresh()

        available = max(remaining - RATE_LIMIT_COMMAND_RESERVE, 1)
        expected = timedelta(seconds=math.ceil(86400 / available))
        assert runtime.coordinator.update_interval == expected

    async def test_auth_error_raises_config_entry_auth_failed(self):
        """A 401 at startup raises ConfigEntryAuthFailed to trigger the HA re-auth flow."""
        from custom_components.v2c_cloud.__init__ import async_setup_entry

        hass = _make_hass()
        entry = _make_entry()
        client = _make_client(pairings_side_effect=V2CAuthError("Unauthorized"))

        with _patch_setup(client):
            with pytest.raises(ConfigEntryAuthFailed):
                await async_setup_entry(hass, entry)


class TestBuildSyntheticFallback:
    """Unit tests for the _build_synthetic_fallback helper.

    Post v2 schema the helper takes the persisted cached_pairings list so
    every known charger is addressable during a cloud outage, not just one.
    """

    def test_single_device_structure_is_complete(self):
        from custom_components.v2c_cloud.__init__ import _build_synthetic_fallback

        data = _build_synthetic_fallback([{"deviceId": "dev-1", "ip": "10.0.0.5"}])

        assert "pairings" in data
        assert "devices" in data
        assert len(data["pairings"]) == 1
        assert data["pairings"][0] == {"deviceId": "dev-1", "ip": "10.0.0.5"}

        device = data["devices"]["dev-1"]
        assert device["device_id"] == "dev-1"
        assert device["connected"] is None
        assert device["reported"] == {}
        assert device["additional"]["static_ip"] == "10.0.0.5"

    def test_multi_device_emits_every_device(self):
        from custom_components.v2c_cloud.__init__ import _build_synthetic_fallback

        data = _build_synthetic_fallback(
            [
                {"deviceId": "dev-a", "ip": "10.0.0.5"},
                {"deviceId": "dev-b", "ip": "10.0.0.6"},
                {"deviceId": "dev-c", "ip": ""},  # cloud-only device
            ]
        )
        assert set(data["devices"]) == {"dev-a", "dev-b", "dev-c"}
        # Device with empty IP gets no static_ip in additional
        assert "static_ip" not in data["devices"]["dev-c"]["additional"]

    def test_empty_pairings_produces_empty_structure(self):
        from custom_components.v2c_cloud.__init__ import _build_synthetic_fallback

        data = _build_synthetic_fallback([])
        assert data == {"pairings": [], "devices": {}}


class TestMigration:
    """Unit tests for the v1 -> v2 schema migration."""

    async def test_migrate_local_no_fallback(self) -> None:
        from custom_components.v2c_cloud.__init__ import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {"api_key": "K"}
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        result = await async_migrate_entry(hass, entry)

        assert result is True
        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        new_data = kwargs["data"]
        assert kwargs["version"] == 2
        assert new_data["cloud_only"] is False
        assert new_data["cached_pairings"] == []
        assert "fallback_ip" not in new_data
        assert "fallback_device_id" not in new_data
        assert "initial_pairings" not in new_data

    async def test_migrate_cloud_only_sentinel(self) -> None:
        from custom_components.v2c_cloud.__init__ import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {
            "api_key": "K",
            "fallback_ip": "",
            "fallback_device_id": "DEV1",
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        await async_migrate_entry(hass, entry)
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is True
        assert new_data["cached_pairings"] == [{"deviceId": "DEV1", "ip": ""}]

    async def test_migrate_single_fallback_ip(self) -> None:
        from custom_components.v2c_cloud.__init__ import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {
            "api_key": "K",
            "fallback_ip": "192.168.1.50",
            "fallback_device_id": "DEV1",
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        await async_migrate_entry(hass, entry)
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is False
        assert new_data["cached_pairings"] == [
            {"deviceId": "DEV1", "ip": "192.168.1.50"}
        ]

    async def test_migrate_prefers_initial_pairings_when_present(self) -> None:
        from custom_components.v2c_cloud.__init__ import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {
            "api_key": "K",
            "initial_pairings": [
                {"deviceId": "A", "ip": "10.0.0.1"},
                {"deviceId": "B", "ip": "10.0.0.2"},
            ],
            "fallback_ip": "192.168.1.50",
            "fallback_device_id": "DEV1",
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        await async_migrate_entry(hass, entry)
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is False
        # initial_pairings wins over the single fallback IP
        assert new_data["cached_pairings"] == [
            {"deviceId": "A", "ip": "10.0.0.1"},
            {"deviceId": "B", "ip": "10.0.0.2"},
        ]

    async def test_migrate_already_v2_is_noop(self) -> None:
        from custom_components.v2c_cloud.__init__ import async_migrate_entry

        entry = MagicMock()
        entry.version = 2
        entry.data = {"api_key": "K", "cloud_only": False, "cached_pairings": []}
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        result = await async_migrate_entry(hass, entry)
        assert result is True
        hass.config_entries.async_update_entry.assert_not_called()


class TestPairingsPersistence:
    """Cached pairings are kept in sync with the cloud's /pairings/me."""

    def test_pairings_changed_detects_diff(self) -> None:
        from custom_components.v2c_cloud.__init__ import _pairings_changed

        assert (
            _pairings_changed(
                [{"deviceId": "A", "ip": "1.1.1.1"}],
                [{"deviceId": "A", "ip": "1.1.1.2"}],
            )
            is True
        )

    def test_pairings_changed_ignores_order(self) -> None:
        from custom_components.v2c_cloud.__init__ import _pairings_changed

        assert (
            _pairings_changed(
                [
                    {"deviceId": "A", "ip": "1.1.1.1"},
                    {"deviceId": "B", "ip": "2.2.2.2"},
                ],
                [
                    {"deviceId": "B", "ip": "2.2.2.2"},
                    {"deviceId": "A", "ip": "1.1.1.1"},
                ],
            )
            is False
        )

    def test_normalise_pairings_drops_extras(self) -> None:
        from custom_components.v2c_cloud.__init__ import _normalise_pairings

        raw = [
            {"deviceId": "A", "ip": "1.1.1.1", "alias": "ignored", "rssi": -55},
            {"deviceId": "B", "ip": "1.1.1.2"},
            {"device_id": "C", "static_ip": "1.1.1.3"},  # alternate spellings
            {"alias": "no-id"},  # dropped
            "not-a-dict",  # dropped
        ]
        assert _normalise_pairings(raw) == [
            {"deviceId": "A", "ip": "1.1.1.1"},
            {"deviceId": "B", "ip": "1.1.1.2"},
            {"deviceId": "C", "ip": "1.1.1.3"},
        ]

    def test_persist_writes_when_changed(self) -> None:
        from custom_components.v2c_cloud.__init__ import _persist_pairings_if_changed

        entry = MagicMock()
        entry.data = {
            "api_key": "K",
            "cached_pairings": [{"deviceId": "A", "ip": "1.1.1.1"}],
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        _persist_pairings_if_changed(hass, entry, [{"deviceId": "A", "ip": "1.1.1.2"}])
        assert hass.config_entries.async_update_entry.called
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cached_pairings"] == [{"deviceId": "A", "ip": "1.1.1.2"}]

    def test_persist_noop_when_unchanged(self) -> None:
        from custom_components.v2c_cloud.__init__ import _persist_pairings_if_changed

        entry = MagicMock()
        entry.data = {
            "api_key": "K",
            "cached_pairings": [{"deviceId": "A", "ip": "1.1.1.1"}],
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        _persist_pairings_if_changed(hass, entry, [{"deviceId": "A", "ip": "1.1.1.1"}])
        hass.config_entries.async_update_entry.assert_not_called()

    def test_persist_noop_on_empty_input(self) -> None:
        from custom_components.v2c_cloud.__init__ import _persist_pairings_if_changed

        entry = MagicMock()
        entry.data = {"api_key": "K"}
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        _persist_pairings_if_changed(hass, entry, [])
        _persist_pairings_if_changed(hass, entry, None)
        hass.config_entries.async_update_entry.assert_not_called()
