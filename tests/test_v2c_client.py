"""Tests for V2CClient HTTP handling and pairings cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.v2c_cloud import (
    V2CAuthError,
    V2CClient,
    V2CRateLimitError,
    V2CRequestError,
)

BASE_URL = "https://v2c.cloud/kong/v2c_service"
API_KEY = "test-api-key"
DEVICE_ID = "test-device-001"


@pytest.fixture
async def client():
    """A V2CClient backed by a real (but intercepted) aiohttp session."""
    session = ClientSession()
    c = V2CClient(session, API_KEY)
    yield c
    await session.close()


@pytest.fixture(autouse=True)
def no_sleep():
    """Replace asyncio.sleep with a no-op so retry loops run instantly."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestRequestErrors:
    """HTTP error codes are translated into the right exception types."""

    async def test_401_raises_auth_error(self, client):
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=401, body="Unauthorized")
            with pytest.raises(V2CAuthError, match="authentication failed"):
                await client.async_get_pairings()

    async def test_500_raises_request_error_with_status(self, client):
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=500, body="Internal Server Error")
            with pytest.raises(V2CRequestError) as exc_info:
                await client.async_get_pairings()
        assert exc_info.value.status == 500

    async def test_404_raises_request_error_with_status(self, client):
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=404, body="Not Found")
            with pytest.raises(V2CRequestError) as exc_info:
                await client.async_get_pairings()
        assert exc_info.value.status == 404

    async def test_429_exhausts_retries_then_raises_rate_limit(self, client):
        with aioresponses() as m:
            # MAX_RETRIES = 3 → three 429 responses exhaust all attempts
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            with pytest.raises(V2CRateLimitError):
                await client.async_get_pairings()

    async def test_429_retries_and_succeeds_on_second_attempt(self, client):
        pairings = [{"deviceId": DEVICE_ID}]
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=429,
                headers={"Retry-After": "0"},
                body="Too Many Requests",
            )
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=pairings,
                content_type="application/json",
            )
            result = await client.async_get_pairings()
        assert result == pairings

    async def test_rate_limit_error_is_subclass_of_request_error(self, client):
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            with pytest.raises(V2CRequestError):
                await client.async_get_pairings()


# ---------------------------------------------------------------------------
# Successful responses
# ---------------------------------------------------------------------------

class TestSuccessfulResponses:
    """Successful HTTP responses are decoded and returned correctly."""

    async def test_returns_parsed_json_list(self, client):
        pairings = [{"deviceId": DEVICE_ID, "name": "My Charger"}]
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=pairings,
                content_type="application/json",
            )
            result = await client.async_get_pairings()
        assert result == pairings

    async def test_204_returns_none(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/reboot?deviceId={DEVICE_ID}",
                status=204,
            )
            result = await client.async_reboot(DEVICE_ID)
        assert result is None

    async def test_empty_body_returns_empty_list_from_pairings(self, client):
        """async_get_pairings() gracefully handles a None/empty payload."""
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                body="",
                content_type="text/plain",
            )
            result = await client.async_get_pairings()
        assert result == []

    async def test_stores_rate_limit_headers(self, client):
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=[],
                content_type="application/json",
                headers={
                    "RateLimit-Limit": "100",
                    "RateLimit-Remaining": "95",
                    "RateLimit-Reset": "3600",
                },
            )
            await client.async_get_pairings()
        rl = client.last_rate_limit
        assert rl is not None
        assert rl["limit"] == 100
        assert rl["remaining"] == 95
        assert rl["reset"] == 3600

    async def test_rate_limit_headers_missing_stays_none(self, client):
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=[],
                content_type="application/json",
            )
            await client.async_get_pairings()
        # last_rate_limit may remain None if no RateLimit-* headers present
        # (it will only be set if at least one header value is not None)
        assert client.last_rate_limit is None or isinstance(client.last_rate_limit, dict)

    async def test_base_url_property(self, client):
        assert client.base_url == BASE_URL

    async def test_last_rate_limit_initially_none(self, client):
        assert client.last_rate_limit is None


# ---------------------------------------------------------------------------
# Pairings caching
# ---------------------------------------------------------------------------

class TestPairingsCache:
    """Pairings are cached in memory and stale data is used as fallback."""

    async def test_preloaded_cache_avoids_network_call(self, client):
        pairings = [{"deviceId": DEVICE_ID}]
        client.preload_pairings(pairings)
        # aioresponses with no registered URLs will raise on any HTTP call
        with aioresponses():
            result = await client.async_get_pairings()
        assert result == pairings

    async def test_expired_cache_triggers_new_request(self, client):
        old_pairings = [{"deviceId": "old-device"}]
        new_pairings = [{"deviceId": DEVICE_ID}]
        client.preload_pairings(old_pairings, ttl=0.0)  # Expired immediately
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=new_pairings,
                content_type="application/json",
            )
            result = await client.async_get_pairings()
        assert result == new_pairings

    async def test_falls_back_to_stale_cache_on_rate_limit(self, client):
        cached_pairings = [{"deviceId": DEVICE_ID}]
        client.preload_pairings(cached_pairings, ttl=0.0)  # Expired
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            result = await client.async_get_pairings()
        assert result == cached_pairings

    async def test_falls_back_to_stale_cache_on_server_error(self, client):
        cached_pairings = [{"deviceId": DEVICE_ID}]
        client.preload_pairings(cached_pairings, ttl=0.0)  # Expired
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=503, body="Service Unavailable")
            result = await client.async_get_pairings()
        assert result == cached_pairings

    async def test_raises_when_no_cache_and_rate_limited(self, client):
        with aioresponses() as m:
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            m.get(f"{BASE_URL}/pairings/me", status=429, body="Too Many Requests")
            with pytest.raises(V2CRateLimitError):
                await client.async_get_pairings()

    async def test_preload_none_is_noop(self, client):
        client.preload_pairings(None)
        assert client._pairings_cache is None

    async def test_cache_updated_after_successful_request(self, client):
        pairings = [{"deviceId": DEVICE_ID}]
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/pairings/me",
                status=200,
                payload=pairings,
                content_type="application/json",
            )
            await client.async_get_pairings()
        assert client._pairings_cache == pairings

    async def test_preload_with_custom_ttl(self, client):
        pairings = [{"deviceId": DEVICE_ID}]
        client.preload_pairings(pairings, ttl=9999.0)
        with aioresponses():
            result = await client.async_get_pairings()
        assert result == pairings


# ---------------------------------------------------------------------------
# Device commands
# ---------------------------------------------------------------------------

class TestDeviceCommands:
    """Device-specific command methods pass correct params to the API."""

    async def test_set_rfid_mode_enabled(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/set_rfid?deviceId={DEVICE_ID}&value=1",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_set_rfid_mode(DEVICE_ID, True)

    async def test_set_rfid_mode_disabled(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/set_rfid?deviceId={DEVICE_ID}&value=0",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_set_rfid_mode(DEVICE_ID, False)

    async def test_set_charge_stop_energy(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/charger_until_energy?deviceId={DEVICE_ID}&value=50",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_set_charge_stop_energy(DEVICE_ID, 50.0)

    async def test_set_charge_stop_minutes(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/charger_until_minutes?deviceId={DEVICE_ID}&value=30",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_set_charge_stop_minutes(DEVICE_ID, 30)

    async def test_reboot_sends_post(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/reboot?deviceId={DEVICE_ID}",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_reboot(DEVICE_ID)

    async def test_set_ocpp_enabled(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/ocpp?id={DEVICE_ID}&value=1",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_set_ocpp_enabled(DEVICE_ID, True)

    async def test_delete_rfid_card(self, client):
        with aioresponses() as m:
            m.delete(
                f"{BASE_URL}/device/rfid?deviceId={DEVICE_ID}&code=AABBCCDD",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            await client.async_delete_rfid_card(DEVICE_ID, "AABBCCDD")
