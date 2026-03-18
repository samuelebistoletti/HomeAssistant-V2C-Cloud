"""Tests for async_gather_devices_state and _fetch_single_device_state."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.v2c_cloud.v2c_cloud import (
    V2CRateLimitError,
    V2CRequestError,
    async_gather_devices_state,
)


def _make_client(
    *,
    reported=None,
    rfid=None,
    version=None,
    reported_error=None,
    rfid_error=None,
    version_error=None,
):
    client = MagicMock()
    client.async_get_reported = AsyncMock(
        side_effect=reported_error,
        return_value=None if reported_error else (reported or {}),
    )
    client.async_get_rfid_cards = AsyncMock(
        side_effect=rfid_error,
        return_value=None if rfid_error else (rfid or []),
    )
    client.async_get_version = AsyncMock(
        side_effect=version_error,
        return_value=None if version_error else (version or {"versionId": "1.0"}),
    )
    return client


# ---------------------------------------------------------------------------
# async_gather_devices_state
# ---------------------------------------------------------------------------


class TestAsyncGatherDevicesState:
    """Tests for the top-level gather function."""

    async def test_empty_pairings_returns_empty_dict(self):
        client = _make_client()
        result = await async_gather_devices_state(client, [])
        assert result == {}

    async def test_pairing_without_device_id_is_skipped(self):
        client = _make_client()
        result = await async_gather_devices_state(client, [{"name": "no-id"}])
        assert result == {}

    async def test_single_device_happy_path(self):
        client = _make_client(
            reported={"ChargeState": 2, "Dynamic": 1},
            rfid=[{"code": "abc"}],
            version={"versionId": "2.3.4"},
        )
        result = await async_gather_devices_state(
            client,
            [{"deviceId": "dev-1"}],
            previous_devices=None,
        )
        assert "dev-1" in result
        state = result["dev-1"]
        assert state["reported"] == {"ChargeState": 2, "Dynamic": 1}
        assert state["rfid_cards"] == [{"code": "abc"}]
        assert state["version"] == "2.3.4"

    async def test_rate_limit_error_propagates(self):
        client = _make_client(reported_error=V2CRateLimitError("429", status=429))
        with pytest.raises(V2CRateLimitError):
            await async_gather_devices_state(client, [{"deviceId": "dev-1"}])

    async def test_generic_exception_skips_device(self):
        # V2CRequestError on `reported` is caught inside _fetch_single_device_state;
        # the device is still returned with fallback (None) reported data.
        client = _make_client(reported_error=V2CRequestError("500", status=500))
        result = await async_gather_devices_state(client, [{"deviceId": "dev-1"}])
        assert "dev-1" in result

    async def test_multiple_devices_processed_independently(self):
        client = _make_client(reported={"ChargeState": 0})
        result = await async_gather_devices_state(
            client,
            [{"deviceId": "dev-A"}, {"deviceId": "dev-B"}],
        )
        assert "dev-A" in result
        assert "dev-B" in result


# ---------------------------------------------------------------------------
# _fetch_single_device_state (via async_gather_devices_state)
# ---------------------------------------------------------------------------


class TestFetchSingleDeviceState:
    """Tests for the per-device fetch logic."""

    async def test_reported_error_logs_and_uses_previous(self):
        """If reported fetch fails, previous reported data is preserved."""
        previous = {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": {"ChargeState": 1},
                "reported_raw": {"ChargeState": 1},
                "connected": True,
                "current_state": {"ChargeState": 1},
                "rfid_cards": [],
                "version": "1.0",
                "additional": {
                    "static_ip": "192.168.1.1",
                    "reported_lower": {"chargestate": 1},
                    "_rfid_next_refresh": 0.0,
                    "_version_next_refresh": 0.0,
                },
            }
        }
        client = _make_client(reported_error=V2CRequestError("err", status=500))
        result = await async_gather_devices_state(
            client,
            [{"deviceId": "dev-1"}],
            previous_devices=previous,
        )
        assert "dev-1" in result
        # Falls back to previous reported
        assert result["dev-1"]["reported"] == {"ChargeState": 1}

    async def test_version_cached_between_refreshes(self):
        """Version is not re-fetched when the refresh interval has not elapsed."""
        import time

        far_future = time.time() + 99999
        previous = {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": {},
                "reported_raw": {},
                "connected": None,
                "current_state": {},
                "rfid_cards": None,
                "version": "cached-1.0",
                "additional": {
                    "_rfid_next_refresh": far_future,
                    "_version_next_refresh": far_future,
                },
            }
        }
        client = _make_client()
        result = await async_gather_devices_state(
            client,
            [{"deviceId": "dev-1"}],
            previous_devices=previous,
        )
        assert result["dev-1"]["version"] == "cached-1.0"
        # Version endpoint should NOT have been called
        client.async_get_version.assert_not_called()

    async def test_rfid_error_preserves_previous_cards(self):
        """RFID fetch error must not wipe out previously known cards."""
        previous = {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": {},
                "reported_raw": {},
                "connected": None,
                "current_state": {},
                "rfid_cards": [{"code": "AABB"}],
                "version": None,
                "additional": {
                    "_rfid_next_refresh": 0.0,
                    "_version_next_refresh": 0.0,
                },
            }
        }
        client = _make_client(rfid_error=V2CRequestError("err", status=503))
        result = await async_gather_devices_state(
            client,
            [{"deviceId": "dev-1"}],
            previous_devices=previous,
        )
        # Previous RFID cards should be carried over
        assert result["dev-1"]["rfid_cards"] == [{"code": "AABB"}]

    async def test_connected_extracted_from_reported(self):
        client = _make_client(reported={"connected": True})
        result = await async_gather_devices_state(client, [{"deviceId": "dev-1"}])
        assert result["dev-1"]["connected"] is True

    async def test_static_ip_extracted_from_reported(self):
        client = _make_client(reported={"ip": "192.168.10.5"})
        result = await async_gather_devices_state(client, [{"deviceId": "dev-1"}])
        assert result["dev-1"]["additional"].get("static_ip") == "192.168.10.5"

    async def test_rate_limit_in_any_call_propagates(self):
        """Even if only RFID is rate-limited, the whole fetch must abort."""
        client = _make_client(rfid_error=V2CRateLimitError("429", status=429))
        with pytest.raises(V2CRateLimitError):
            await async_gather_devices_state(client, [{"deviceId": "dev-1"}])
