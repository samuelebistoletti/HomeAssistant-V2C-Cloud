"""Tests for the 10 cloud endpoints added in 1.3.0.

Each method is exercised against a mocked V2C Cloud endpoint to verify URL,
method, query parameters and response normalisation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.v2c_cloud import V2CClient

BASE_URL = "https://v2c.cloud/kong/v2c_service"
API_KEY = "test-api-key-1-3-0"
DEVICE_ID = "DFL2JPV"


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


class TestCloudChargeControl:
    """Start/pause charging endpoints."""

    async def test_start_charge_posts_to_startcharge(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/startcharge?deviceId={DEVICE_ID}",
                status=200,
                body="",
            )
            await client.async_cloud_start_charge(DEVICE_ID)

    async def test_pause_charge_posts_to_pausecharge(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/pausecharge?deviceId={DEVICE_ID}",
                status=200,
                body="",
            )
            await client.async_cloud_pause_charge(DEVICE_ID)


class TestCloudIntensity:
    """Intensity / locked / dynamic endpoints."""

    async def test_set_intensity_serialises_amp_value(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/intensity?deviceId={DEVICE_ID}&value=16",
                status=200,
                body="",
            )
            await client.async_cloud_set_intensity(DEVICE_ID, 16)

    async def test_set_locked_true_serialises_one(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/locked?deviceId={DEVICE_ID}&value=1",
                status=200,
                body="",
            )
            await client.async_cloud_set_locked(DEVICE_ID, locked=True)

    async def test_set_locked_false_serialises_zero(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/locked?deviceId={DEVICE_ID}&value=0",
                status=200,
                body="",
            )
            await client.async_cloud_set_locked(DEVICE_ID, locked=False)

    async def test_set_dynamic_serialises_one_for_enabled(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/dynamic?deviceId={DEVICE_ID}&value=1",
                status=200,
                body="",
            )
            await client.async_cloud_set_dynamic(DEVICE_ID, enabled=True)


class TestCloudFvAndCarLimits:
    """Photovoltaic mode + min/max car intensity + Denka power."""

    @pytest.mark.parametrize("mode", [0, 1, 2])
    async def test_set_fv_mode_accepts_valid_modes(self, client, mode):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/chargefvmode?deviceId={DEVICE_ID}&value={mode}",
                status=200,
                body="",
            )
            await client.async_cloud_set_fv_mode(DEVICE_ID, mode)

    async def test_set_fv_mode_rejects_invalid(self, client):
        with pytest.raises(Exception, match="Invalid FV mode"):
            await client.async_cloud_set_fv_mode(DEVICE_ID, 5)

    async def test_set_max_car_intensity(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/max_car_int?deviceId={DEVICE_ID}&value=32",
                status=200,
                body="",
            )
            await client.async_cloud_set_max_car_intensity(DEVICE_ID, 32)

    async def test_set_min_car_intensity(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/min_car_int?deviceId={DEVICE_ID}&value=6",
                status=200,
                body="",
            )
            await client.async_cloud_set_min_car_intensity(DEVICE_ID, 6)

    async def test_set_denka_max_power_serialises_watts(self, client):
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/device/denka/max_power?deviceId={DEVICE_ID}&value=5000",
                status=200,
                body="",
            )
            await client.async_cloud_set_denka_max_power(DEVICE_ID, 5000)


class TestCloudConnected:
    """GET /device/connected normalisation."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ('{"online": true}', False),  # unknown payload shape → falsy default
        ],
    )
    async def test_connected_normalisation(self, client, body, expected):
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/device/connected?deviceId={DEVICE_ID}",
                status=200,
                body=body,
            )
            result = await client.async_cloud_get_connected(DEVICE_ID)
            assert isinstance(result, bool)
            assert result is expected
