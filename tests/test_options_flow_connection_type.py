"""Tests for the connection_type toggle in V2COptionsFlow (post-v2 schema)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.v2c_cloud.config_flow import (
    V2COptionsFlow,
    _infer_connection_type,
)
from custom_components.v2c_cloud.const import CONF_LOCAL_UPDATE_INTERVAL

# ---------------------------------------------------------------------------
# _infer_connection_type helper
# ---------------------------------------------------------------------------


class TestInferConnectionType:
    def test_no_cloud_only_key_is_local(self) -> None:
        assert _infer_connection_type({}) == "local"

    def test_cloud_only_false_is_local(self) -> None:
        assert _infer_connection_type({"cloud_only": False}) == "local"

    def test_cloud_only_true_is_cloud_only(self) -> None:
        assert _infer_connection_type({"cloud_only": True}) == "cloud_only"


# ---------------------------------------------------------------------------
# V2COptionsFlow.async_step_init — mode toggle behaviour
# ---------------------------------------------------------------------------


class TestOptionsFlowConnectionTypeToggle:
    """Verify the options flow can switch between local and cloud_only."""

    def _flow(
        self,
        *,
        entry_data: dict[str, Any] | None = None,
        entry_options: dict[str, Any] | None = None,
    ) -> tuple[V2COptionsFlow, MagicMock, MagicMock]:
        entry = MagicMock()
        entry.entry_id = "abc"
        entry.data = entry_data if entry_data is not None else {}
        entry.options = entry_options or {}

        hass = MagicMock()
        hass.data = {"v2c_cloud": {}}
        hass.config_entries = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        def _capture_task(coro: Any) -> Any:
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        hass.async_create_task = MagicMock(side_effect=_capture_task)

        flow = V2COptionsFlow(entry)
        flow.hass = hass
        flow.async_create_entry = MagicMock(
            side_effect=lambda *, title, data: {"type": "create_entry", "data": data}
        )
        flow.async_show_form = MagicMock(
            side_effect=lambda *, step_id, data_schema, errors=None: {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
            }
        )
        return flow, hass, entry

    async def test_default_mode_for_local_entry(self) -> None:
        flow, _hass, _entry = self._flow(entry_data={"cloud_only": False})
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["errors"] == {}

    async def test_default_mode_for_cloud_only_entry(self) -> None:
        flow, _hass, _entry = self._flow(entry_data={"cloud_only": True})
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["errors"] == {}

    async def test_switch_local_to_cloud_only(self) -> None:
        flow, hass, _entry = self._flow(entry_data={"cloud_only": False})
        result = await flow.async_step_init(
            user_input={
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "create_entry"
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is True
        # Mode change → reload scheduled
        hass.async_create_task.assert_called_once()

    async def test_switch_cloud_only_to_local(self) -> None:
        flow, hass, _entry = self._flow(entry_data={"cloud_only": True})
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "create_entry"
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is False
        # Mode change → reload scheduled
        hass.async_create_task.assert_called_once()

    async def test_no_mode_change_does_not_reload(self) -> None:
        flow, hass, _entry = self._flow(entry_data={"cloud_only": False})
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 45,
            }
        )
        assert result["type"] == "create_entry"
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["cloud_only"] is False
        # Interval lives in entry.options, written via async_create_entry's data arg.
        assert result["data"][CONF_LOCAL_UPDATE_INTERVAL] == 45
        hass.async_create_task.assert_not_called()

    async def test_interval_is_persisted_via_create_entry(self) -> None:
        """Regression: passing data={} to async_create_entry overwrites the options
        the user just set. HA's OptionsFlow uses the create_entry data argument as
        the new entry.options; the interval must be carried there explicitly."""
        flow, _hass, _entry = self._flow(
            entry_data={"cloud_only": False},
            entry_options={CONF_LOCAL_UPDATE_INTERVAL: 30},
        )
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 5,
            }
        )
        assert result["type"] == "create_entry"
        # The data argument of async_create_entry becomes entry.options in HA.
        assert result["data"][CONF_LOCAL_UPDATE_INTERVAL] == 5

    async def test_invalid_interval_rejected(self) -> None:
        flow, hass, _entry = self._flow(entry_data={"cloud_only": False})
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 9999,
            }
        )
        assert result["type"] == "form"
        assert result["errors"] == {CONF_LOCAL_UPDATE_INTERVAL: "invalid_interval"}
        hass.config_entries.async_update_entry.assert_not_called()
