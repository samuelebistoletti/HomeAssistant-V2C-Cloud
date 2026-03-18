"""Tests for V2CButton entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError


def _make_button(*, coroutine_factory=None, refresh_after_call=True):
    from custom_components.v2c_cloud.button import V2CButton

    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    coord.last_update_success = True

    client = MagicMock()
    client.async_reboot = AsyncMock(return_value=None)

    if coroutine_factory is None:
        coroutine_factory = lambda: client.async_reboot("dev-1")  # noqa: E731

    button = V2CButton(
        coord,
        client,
        "dev-1",
        name_key="reboot",
        unique_suffix="reboot",
        coroutine_factory=coroutine_factory,
        icon="mdi:restart",
        refresh_after_call=refresh_after_call,
    )
    return button, coord, client


class TestV2CButtonAsyncPress:
    """Tests for V2CButton.async_press."""

    async def test_calls_factory_and_refreshes(self):
        action = AsyncMock(return_value=None)
        button, coord, _ = _make_button(
            coroutine_factory=lambda: action(),
            refresh_after_call=True,
        )
        await button.async_press()
        action.assert_called_once()
        coord.async_request_refresh.assert_called_once()

    async def test_does_not_refresh_when_disabled(self):
        action = AsyncMock(return_value=None)
        button, coord, _ = _make_button(
            coroutine_factory=lambda: action(),
            refresh_after_call=False,
        )
        await button.async_press()
        action.assert_called_once()
        coord.async_request_refresh.assert_not_called()

    async def test_v2c_error_raises_ha_error(self):
        from custom_components.v2c_cloud.v2c_cloud import V2CError

        async def _fail():
            raise V2CError("reboot failed")

        button, _, _ = _make_button(coroutine_factory=_fail, refresh_after_call=False)
        with pytest.raises(HomeAssistantError, match="reboot failed"):
            await button.async_press()

    async def test_local_api_error_raises_ha_error(self):
        from custom_components.v2c_cloud.local_api import V2CLocalApiError

        async def _fail():
            raise V2CLocalApiError("local error")

        button, _, _ = _make_button(coroutine_factory=_fail, refresh_after_call=False)
        with pytest.raises(HomeAssistantError, match="local error"):
            await button.async_press()

    def test_unique_id(self):
        button, _, _ = _make_button()
        assert button._attr_unique_id == "v2c_dev-1_reboot"

    def test_icon(self):
        button, _, _ = _make_button()
        assert button._attr_icon == "mdi:restart"
