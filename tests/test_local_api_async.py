"""Tests for async local_api functions: resolve_static_ip and async_write_keyword SSRF guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.local_api import (
    V2CLocalApiError,
    async_write_keyword,
    resolve_static_ip,
)


# ---------------------------------------------------------------------------
# resolve_static_ip
# ---------------------------------------------------------------------------


def _make_runtime(*, additional=None, local_data=None, pairing_ip=None):
    """Build a minimal runtime_data with a cloud coordinator and optional local coordinator."""
    device_state = {
        "device_id": "dev-1",
        "pairing": {"deviceId": "dev-1"},
        "reported": {},
        "additional": additional or {},
    }
    coord = MagicMock()
    coord.data = {
        "devices": {"dev-1": device_state},
        "pairings": [{"deviceId": "dev-1", "ip": pairing_ip}] if pairing_ip else [{"deviceId": "dev-1"}],
    }

    runtime_data = MagicMock()
    runtime_data.coordinator = coord

    if local_data is not None:
        local_coord = MagicMock()
        local_coord.data = local_data
        runtime_data.local_coordinators = {"dev-1": local_coord}
    else:
        runtime_data.local_coordinators = {}

    return runtime_data


class TestResolveStaticIp:
    """Tests for resolve_static_ip lookup chain."""

    def test_returns_ip_from_additional(self):
        rd = _make_runtime(additional={"static_ip": "192.168.1.100"})
        assert resolve_static_ip(rd, "dev-1") == "192.168.1.100"

    def test_returns_ip_from_local_coordinator_data(self):
        rd = _make_runtime(local_data={"_static_ip": "192.168.1.50"})
        assert resolve_static_ip(rd, "dev-1") == "192.168.1.50"

    def test_returns_ip_key_from_local_data(self):
        rd = _make_runtime(local_data={"IP": "192.168.1.55"})
        assert resolve_static_ip(rd, "dev-1") == "192.168.1.55"

    def test_returns_ip_from_pairing(self):
        rd = _make_runtime(pairing_ip="192.168.1.10")
        assert resolve_static_ip(rd, "dev-1") == "192.168.1.10"

    def test_returns_none_when_no_ip_anywhere(self):
        rd = _make_runtime()
        assert resolve_static_ip(rd, "dev-1") is None

    def test_returns_ip_from_reported(self):
        device_state = {
            "device_id": "dev-1",
            "pairing": {"deviceId": "dev-1"},
            "reported": {"ip": "192.168.5.5"},
            "additional": {},
        }
        coord = MagicMock()
        coord.data = {"devices": {"dev-1": device_state}, "pairings": []}
        runtime_data = MagicMock()
        runtime_data.coordinator = coord
        runtime_data.local_coordinators = {}
        assert resolve_static_ip(runtime_data, "dev-1") == "192.168.5.5"

    def test_additional_takes_priority_over_pairing(self):
        rd = _make_runtime(
            additional={"static_ip": "192.168.1.99"},
            pairing_ip="192.168.1.1",
        )
        assert resolve_static_ip(rd, "dev-1") == "192.168.1.99"


# ---------------------------------------------------------------------------
# async_write_keyword — SSRF guard
# ---------------------------------------------------------------------------


def _make_hass_with_session(session: ClientSession) -> MagicMock:
    hass = MagicMock()
    with patch("custom_components.v2c_cloud.local_api.async_get_clientsession", return_value=session):
        pass
    return hass


class TestAsyncWriteKeywordSsrfGuard:
    """Tests for SSRF guard in async_write_keyword."""

    def _runtime(self, ip: str) -> MagicMock:
        return _make_runtime(additional={"static_ip": ip})

    async def test_loopback_raises_local_api_error(self):
        hass = MagicMock()
        rd = self._runtime("127.0.0.1")
        with pytest.raises(V2CLocalApiError, match="SSRF"):
            await async_write_keyword(hass, rd, "dev-1", "Intensity", 16)

    async def test_public_ip_raises_local_api_error(self):
        hass = MagicMock()
        rd = self._runtime("8.8.8.8")
        with pytest.raises(V2CLocalApiError, match="SSRF"):
            await async_write_keyword(hass, rd, "dev-1", "Intensity", 16)

    async def test_no_ip_raises_local_api_error(self):
        hass = MagicMock()
        rd = _make_runtime()  # no static_ip
        with pytest.raises(V2CLocalApiError, match="Static IP"):
            await async_write_keyword(hass, rd, "dev-1", "Intensity", 16)

    async def test_invalid_ip_raises_local_api_error(self):
        hass = MagicMock()
        rd = self._runtime("not-an-ip")
        with pytest.raises(V2CLocalApiError, match="Invalid IP"):
            await async_write_keyword(hass, rd, "dev-1", "Intensity", 16)

    async def test_private_ip_sends_request(self):
        """A valid private IP must reach the HTTP write endpoint."""
        session = ClientSession()
        rd = self._runtime("192.168.1.100")
        with aioresponses() as m:
            m.get(
                "http://192.168.1.100/write/Intensity=16",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            with patch(
                "custom_components.v2c_cloud.local_api.async_get_clientsession",
                return_value=session,
            ):
                hass = MagicMock()
                # Suppress follow-up local refresh
                rd.local_coordinators = {}
                await async_write_keyword(hass, rd, "dev-1", "Intensity", 16, refresh_local=False)
        await session.close()

    async def test_bool_value_serialized_as_int(self):
        """True should become '1' in the URL, not 'True'."""
        session = ClientSession()
        rd = self._runtime("192.168.1.100")
        with aioresponses() as m:
            m.get(
                "http://192.168.1.100/write/Locked=1",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            with patch(
                "custom_components.v2c_cloud.local_api.async_get_clientsession",
                return_value=session,
            ):
                hass = MagicMock()
                rd.local_coordinators = {}
                await async_write_keyword(hass, rd, "dev-1", "Locked", True, refresh_local=False)
        await session.close()

    async def test_http_error_raises_local_api_error(self):
        session = ClientSession()
        rd = self._runtime("192.168.1.100")
        with aioresponses() as m:
            m.get(
                "http://192.168.1.100/write/Intensity=16",
                status=500,
                body="error",
            )
            with patch(
                "custom_components.v2c_cloud.local_api.async_get_clientsession",
                return_value=session,
            ):
                hass = MagicMock()
                rd.local_coordinators = {}
                with pytest.raises(V2CLocalApiError, match="HTTP 500"):
                    await async_write_keyword(hass, rd, "dev-1", "Intensity", 16, refresh_local=False)
        await session.close()


# ---------------------------------------------------------------------------
# SSRF guard — parametrized boundary tests
# ---------------------------------------------------------------------------


class TestSsrfBoundaries:
    """Parametrized test verifying exactly which IPs are allowed / blocked."""

    @pytest.mark.parametrize("ip", [
        "127.0.0.1",
        "127.255.255.255",
        "8.8.8.8",
        "1.0.0.1",
        "169.254.1.1",    # link-local — is_private=True on Python 3.11+ but must be rejected
    ])
    async def test_rejected_ips(self, ip):
        hass = MagicMock()
        rd = _make_runtime(additional={"static_ip": ip})
        with pytest.raises(V2CLocalApiError):
            await async_write_keyword(hass, rd, "dev-1", "Intensity", 1)

    @pytest.mark.parametrize("ip", [
        "192.168.1.1",
        "10.10.10.10",
        "172.16.0.1",
        "172.31.255.254",
    ])
    async def test_allowed_ips_reach_http(self, ip):
        session = ClientSession()
        rd = _make_runtime(additional={"static_ip": ip})
        encoded_ip = ip
        with aioresponses() as m:
            m.get(
                f"http://{encoded_ip}/write/Dynamic=1",
                status=200,
                body="ok",
                content_type="text/plain",
            )
            with patch(
                "custom_components.v2c_cloud.local_api.async_get_clientsession",
                return_value=session,
            ):
                hass = MagicMock()
                rd.local_coordinators = {}
                await async_write_keyword(hass, rd, "dev-1", "Dynamic", 1, refresh_local=False)
        await session.close()
