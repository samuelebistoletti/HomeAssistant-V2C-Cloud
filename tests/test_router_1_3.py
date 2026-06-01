"""Tests for the LAN-vs-cloud command router introduced in 1.3.0.

The router was promoted from private (__init__._async_route_local_or_cloud)
to public (local_api.async_route_local_or_cloud) so entity setters can use
the same routing logic as service handlers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.v2c_cloud.local_api import (
    V2CLocalApiError,
    async_route_local_or_cloud,
    is_cloud_only_device,
)


class TestIsCloudOnly:
    """Detection of the cloud-only signal in entry.data."""

    def test_no_cloud_only_key_means_lan(self) -> None:
        assert is_cloud_only_device({}) is False

    def test_cloud_only_false_means_lan(self) -> None:
        assert is_cloud_only_device({"cloud_only": False}) is False

    def test_cloud_only_true(self) -> None:
        assert is_cloud_only_device({"cloud_only": True}) is True


@pytest.fixture
def runtime_data() -> Any:
    """Minimal V2CEntryRuntimeData stand-in for the router."""
    rd = MagicMock()
    rd.coordinator.config_entry.data = {"cloud_only": False}
    return rd


class TestRouterLanFirst:
    """The router prefers the LAN path when cloud_only is False.

    ``cloud_call`` is a zero-arg factory: when LAN succeeds, the factory
    is never invoked and no awaitable is constructed. That eliminates the
    "coroutine was never awaited" warning that previously polluted logs
    on every successful LAN write.
    """

    async def test_lan_success_does_not_invoke_cloud_factory(
        self, monkeypatch, runtime_data
    ) -> None:
        lan_calls: list[Any] = []

        async def fake_write(hass, rd, device_id, kw, val, *, refresh_local=True):
            lan_calls.append((kw, val))

        monkeypatch.setattr(
            "custom_components.v2c_cloud.local_api.async_write_keyword", fake_write
        )

        factory_invocations = 0

        async def cloud_coro() -> None:
            raise AssertionError("cloud factory must not run when LAN succeeds")

        def cloud_factory():
            nonlocal factory_invocations
            factory_invocations += 1
            return cloud_coro()

        await async_route_local_or_cloud(
            MagicMock(),
            runtime_data,
            "DEV1",
            keyword="Paused",
            value=0,
            cloud_call=cloud_factory,
            config_data={"cloud_only": False},
        )

        assert lan_calls == [("Paused", 0)]
        # The whole point: the factory was never called, so no orphan
        # coroutine to clean up and no "never awaited" warning.
        assert factory_invocations == 0

    async def test_lan_failure_falls_back_to_cloud(
        self, monkeypatch, runtime_data
    ) -> None:
        async def fake_write(*args: Any, **kwargs: Any) -> None:
            raise V2CLocalApiError("LAN unreachable")

        monkeypatch.setattr(
            "custom_components.v2c_cloud.local_api.async_write_keyword", fake_write
        )

        cloud_called = []

        async def fake_cloud() -> None:
            cloud_called.append(True)

        await async_route_local_or_cloud(
            MagicMock(),
            runtime_data,
            "DEV1",
            keyword="Locked",
            value=1,
            cloud_call=lambda: fake_cloud(),
            config_data={"cloud_only": False},
        )

        assert cloud_called == [True]

    async def test_cloud_only_skips_lan(self, monkeypatch) -> None:
        lan_calls: list[Any] = []

        async def fake_write(*args: Any, **kwargs: Any) -> None:
            lan_calls.append(args)

        monkeypatch.setattr(
            "custom_components.v2c_cloud.local_api.async_write_keyword", fake_write
        )

        cloud_called = []

        async def fake_cloud() -> None:
            cloud_called.append(True)

        await async_route_local_or_cloud(
            MagicMock(),
            MagicMock(),
            "DEV2",
            keyword="Paused",
            value=1,
            cloud_call=lambda: fake_cloud(),
            config_data={"cloud_only": True},  # explicit cloud-only
        )

        assert lan_calls == []
        assert cloud_called == [True]


class TestRouterNoCloudEndpoint:
    """Some keywords (LightLED, ContractedPower, Timer, PauseDynamic,
    ChargeMode, DynamicPowerMode) have no V2C Cloud setter. The entity
    setters pass ``cloud_call=None`` so the router can raise a clear,
    user-facing error message in cloud-only mode.
    """

    async def test_cloud_only_raises_when_no_cloud_call(self) -> None:
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError) as excinfo:
            await async_route_local_or_cloud(
                MagicMock(),
                MagicMock(),
                "DEV3",
                keyword="LightLED",
                value=75,
                cloud_call=None,
                config_data={"cloud_only": True},  # cloud-only
            )
        msg = str(excinfo.value)
        assert "LightLED" in msg
        assert "cloud-only" in msg.lower()

    async def test_lan_only_with_none_cloud_call_uses_lan(
        self, monkeypatch, runtime_data
    ) -> None:
        lan_calls: list[Any] = []

        async def fake_write(hass, rd, device_id, kw, val, *, refresh_local=True):
            lan_calls.append((kw, val))

        monkeypatch.setattr(
            "custom_components.v2c_cloud.local_api.async_write_keyword", fake_write
        )

        # LAN device with cloud_call=None — LAN succeeds, no error raised.
        await async_route_local_or_cloud(
            MagicMock(),
            runtime_data,
            "DEV4",
            keyword="LightLED",
            value=42,
            cloud_call=None,
            config_data={"cloud_only": False},
        )
        assert lan_calls == [("LightLED", 42)]

    async def test_lan_fails_and_no_cloud_call_raises(
        self, monkeypatch, runtime_data
    ) -> None:
        from homeassistant.exceptions import HomeAssistantError

        async def fake_write(*args: Any, **kwargs: Any) -> None:
            raise V2CLocalApiError("LAN unreachable")

        monkeypatch.setattr(
            "custom_components.v2c_cloud.local_api.async_write_keyword", fake_write
        )

        # LAN device but LAN write fails AND no cloud fallback exists.
        # The router must raise rather than silently dropping the write.
        with pytest.raises(HomeAssistantError):
            await async_route_local_or_cloud(
                MagicMock(),
                runtime_data,
                "DEV5",
                keyword="ContractedPower",
                value=5000,
                cloud_call=None,
                config_data={"cloud_only": False},
            )
