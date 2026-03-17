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
    data: dict[str, Any] = {"api_key": API_KEY}
    if fallback:
        data["fallback_ip"] = FALLBACK_IP
        data["fallback_device_id"] = DEVICE_ID
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
            return_value=pairings_return if pairings_return is not None else [SAMPLE_PAIRING]
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
            patch("custom_components.v2c_cloud.__init__.V2CClient", return_value=mock_client)
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
    """Unit tests for the _build_synthetic_fallback helper."""

    def test_structure_is_complete(self):
        from custom_components.v2c_cloud.__init__ import _build_synthetic_fallback

        data = _build_synthetic_fallback("dev-1", "10.0.0.5")

        assert "pairings" in data
        assert "devices" in data
        assert len(data["pairings"]) == 1
        assert data["pairings"][0] == {"deviceId": "dev-1", "ip": "10.0.0.5"}

        device = data["devices"]["dev-1"]
        assert device["device_id"] == "dev-1"
        assert device["connected"] is None
        assert device["reported"] == {}
        assert device["additional"]["static_ip"] == "10.0.0.5"
        # Pairing reference in device matches the pairings list entry
        assert device["pairing"] is data["pairings"][0]
