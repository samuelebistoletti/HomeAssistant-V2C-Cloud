"""Tests for config_flow helpers and flow steps."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses
from aiohttp import ClientSession

from custom_components.v2c_cloud.config_flow import _probe_local_api
from custom_components.v2c_cloud.v2c_cloud import V2CAuthError, V2CRequestError


# ---------------------------------------------------------------------------
# _probe_local_api — SSRF guard and local API probing
# ---------------------------------------------------------------------------


class TestProbeLocalApi:
    """Tests for _probe_local_api."""

    def _hass(self, session: ClientSession) -> MagicMock:
        hass = MagicMock()
        ha_aiohttp = __import__("homeassistant.helpers.aiohttp_client", fromlist=["async_get_clientsession"])
        ha_aiohttp.async_get_clientsession = MagicMock(return_value=session)
        hass.helpers = MagicMock()
        return hass

    async def test_valid_private_ip_returns_device_id(self):
        session = ClientSession()
        hass = self._hass(session)
        payload = '{"ID": "abc123", "ChargeState": 0}'
        with aioresponses() as m:
            m.get("http://192.168.1.50/RealTimeData", status=200, body=payload, content_type="text/plain")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                device_id, error_key = await _probe_local_api(hass, "192.168.1.50")
        await session.close()
        assert device_id == "abc123"
        assert error_key is None

    async def test_loopback_ip_is_rejected(self):
        hass = MagicMock()
        device_id, error_key = await _probe_local_api(hass, "127.0.0.1")
        assert device_id is None
        assert error_key == "cannot_connect_local"

    async def test_public_ip_is_rejected(self):
        hass = MagicMock()
        device_id, error_key = await _probe_local_api(hass, "8.8.8.8")
        assert device_id is None
        assert error_key == "cannot_connect_local"

    async def test_invalid_ip_returns_error(self):
        hass = MagicMock()
        device_id, error_key = await _probe_local_api(hass, "not-an-ip")
        assert device_id is None
        assert error_key == "cannot_connect_local"

    async def test_http_error_returns_error(self):
        session = ClientSession()
        hass = self._hass(session)
        with aioresponses() as m:
            m.get("http://192.168.1.50/RealTimeData", status=500, body="error")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                device_id, error_key = await _probe_local_api(hass, "192.168.1.50")
        await session.close()
        assert device_id is None
        assert error_key == "cannot_connect_local"

    async def test_json_without_id_returns_no_device_id_error(self):
        session = ClientSession()
        hass = self._hass(session)
        payload = '{"ChargeState": 2}'
        with aioresponses() as m:
            m.get("http://192.168.1.50/RealTimeData", status=200, body=payload, content_type="text/plain")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                device_id, error_key = await _probe_local_api(hass, "192.168.1.50")
        await session.close()
        assert device_id is None
        assert error_key == "no_device_id"

    async def test_invalid_json_returns_error(self):
        session = ClientSession()
        hass = self._hass(session)
        with aioresponses() as m:
            m.get("http://192.168.1.50/RealTimeData", status=200, body="not json", content_type="text/plain")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                device_id, error_key = await _probe_local_api(hass, "192.168.1.50")
        await session.close()
        assert device_id is None
        assert error_key == "cannot_connect_local"

    async def test_payload_with_percent_suffix_is_handled(self):
        """Some firmware versions append '%' to the JSON body."""
        session = ClientSession()
        hass = self._hass(session)
        payload = '{"ID": "xyz99"}%'
        with aioresponses() as m:
            m.get("http://192.168.1.50/RealTimeData", status=200, body=payload, content_type="text/plain")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                device_id, error_key = await _probe_local_api(hass, "192.168.1.50")
        await session.close()
        assert device_id == "xyz99"
        assert error_key is None


# ---------------------------------------------------------------------------
# SSRF guard — parametrized
# ---------------------------------------------------------------------------


class TestSsrfGuardAddresses:
    """Parametrized SSRF boundary tests for _probe_local_api."""

    @pytest.mark.parametrize("ip", [
        "127.0.0.1",      # loopback
        "127.1.2.3",      # loopback range
        "8.8.8.8",        # public
        "1.1.1.1",        # public
        "169.254.1.1",    # link-local — is_private=True on Python 3.11+ but must be rejected
    ])
    async def test_non_routable_ips_rejected(self, ip):
        hass = MagicMock()
        device_id, error_key = await _probe_local_api(hass, ip)
        assert device_id is None
        assert error_key == "cannot_connect_local"

    @pytest.mark.parametrize("ip", [
        "192.168.0.1",
        "192.168.100.50",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.255",
    ])
    async def test_private_ips_are_probed(self, ip):
        """Private (non-loopback) IPs should reach the HTTP layer, not be short-circuited."""
        session = ClientSession()
        with aioresponses() as m:
            m.get(f"http://{ip}/RealTimeData", status=200, body='{"ID": "dev1"}', content_type="text/plain")
            with patch("custom_components.v2c_cloud.config_flow.aiohttp_client.async_get_clientsession", return_value=session):
                hass = MagicMock()
                device_id, error_key = await _probe_local_api(hass, ip)
        await session.close()
        assert device_id == "dev1"
        assert error_key is None
