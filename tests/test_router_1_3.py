"""Tests for the LAN-vs-cloud command router introduced in 1.3.0."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# The router lives in __init__ but isn't part of the public surface.
from custom_components.v2c_cloud import (
    _async_route_local_or_cloud,
    _is_cloud_only_device,
)
from custom_components.v2c_cloud.local_api import V2CLocalApiError


class TestIsCloudOnly:
    """Detection of the cloud-only signal in entry.data."""

    def test_no_fallback_key_means_lan(self) -> None:
        assert _is_cloud_only_device({}) is False

    def test_present_fallback_with_value_means_lan(self) -> None:
        assert _is_cloud_only_device({"fallback_ip": "192.168.1.20"}) is False

    def test_empty_fallback_means_cloud_only(self) -> None:
        assert _is_cloud_only_device({"fallback_ip": ""}) is True

    def test_unspecified_fallback_means_cloud_only(self) -> None:
        assert _is_cloud_only_device({"fallback_ip": "0.0.0.0"}) is True


@pytest.fixture
def runtime_data() -> Any:
    """Minimal V2CEntryRuntimeData stand-in for the router."""
    rd = MagicMock()
    rd.coordinator.config_entry.data = {"fallback_ip": "192.168.1.20"}
    return rd


class TestRouterLanFirst:
    """The router prefers the LAN path when a fallback_ip is present."""

    async def test_lan_success_skips_cloud(self, monkeypatch, runtime_data) -> None:
        lan_calls: list[Any] = []

        async def fake_write(hass, rd, device_id, kw, val, *, refresh_local=True):
            lan_calls.append((kw, val))

        monkeypatch.setattr(
            "custom_components.v2c_cloud.async_write_keyword", fake_write
        )

        cloud_mock = AsyncMock()
        cloud_call = cloud_mock(MagicMock())  # awaitable not yet awaited

        await _async_route_local_or_cloud(
            hass=MagicMock(),
            entry_data=runtime_data,
            config_data={"fallback_ip": "192.168.1.20"},
            device_id="DEV1",
            keyword="Paused",
            value=0,
            cloud_call=cloud_call,
        )

        assert lan_calls == [("Paused", 0)]
        # The cloud coroutine was created but should NOT have been awaited again.
        # Close it explicitly to avoid the "never awaited" warning.
        cloud_call.close()

    async def test_lan_failure_falls_back_to_cloud(
        self, monkeypatch, runtime_data
    ) -> None:
        async def fake_write(*args: Any, **kwargs: Any) -> None:
            raise V2CLocalApiError("LAN unreachable")

        monkeypatch.setattr(
            "custom_components.v2c_cloud.async_write_keyword", fake_write
        )

        cloud_called = []

        async def fake_cloud() -> None:
            cloud_called.append(True)

        await _async_route_local_or_cloud(
            hass=MagicMock(),
            entry_data=runtime_data,
            config_data={"fallback_ip": "192.168.1.20"},
            device_id="DEV1",
            keyword="Locked",
            value=1,
            cloud_call=fake_cloud(),
        )

        assert cloud_called == [True]

    async def test_cloud_only_skips_lan(self, monkeypatch) -> None:
        lan_calls: list[Any] = []

        async def fake_write(*args: Any, **kwargs: Any) -> None:
            lan_calls.append(args)

        monkeypatch.setattr(
            "custom_components.v2c_cloud.async_write_keyword", fake_write
        )

        cloud_called = []

        async def fake_cloud() -> None:
            cloud_called.append(True)

        await _async_route_local_or_cloud(
            hass=MagicMock(),
            entry_data=MagicMock(),
            config_data={"fallback_ip": ""},  # explicit cloud-only
            device_id="DEV2",
            keyword="Paused",
            value=1,
            cloud_call=fake_cloud(),
        )

        assert lan_calls == []
        assert cloud_called == [True]
