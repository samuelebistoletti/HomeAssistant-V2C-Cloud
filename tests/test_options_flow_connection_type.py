"""Tests for the connection_type toggle in V2COptionsFlow (added in 1.3.x)."""

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
    def test_no_fallback_ip_key_is_local(self) -> None:
        assert _infer_connection_type({}) == "local"

    def test_empty_fallback_ip_is_cloud_only(self) -> None:
        assert _infer_connection_type({"fallback_ip": ""}) == "cloud_only"

    def test_zero_sentinel_is_cloud_only(self) -> None:
        assert _infer_connection_type({"fallback_ip": "0.0.0.0"}) == "cloud_only"

    def test_real_ip_is_local_with_fallback(self) -> None:
        assert _infer_connection_type({"fallback_ip": "192.168.1.42"}) == "local"


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
        coordinator_data: dict[str, Any] | None = None,
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
            # Close the coroutine so Python doesn't warn about it being
            # scheduled but never awaited.
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        hass.async_create_task = MagicMock(side_effect=_capture_task)

        if coordinator_data is not None:
            runtime = MagicMock()
            runtime.coordinator = MagicMock()
            runtime.coordinator.data = coordinator_data
            hass.data["v2c_cloud"][entry.entry_id] = runtime

        flow = V2COptionsFlow(entry)
        flow.hass = hass
        # Mock the async_create_entry / async_show_form helpers HA injects
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
        flow, _hass, _entry = self._flow(entry_data={})
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        # Just confirm the form renders without errors; default plumbed via schema.
        assert result["errors"] == {}

    async def test_default_mode_for_cloud_only_entry(self) -> None:
        flow, _hass, _entry = self._flow(
            entry_data={"fallback_ip": "", "fallback_device_id": "dev1"}
        )
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["errors"] == {}

    async def test_switch_local_to_cloud_only_picks_device_from_runtime(self) -> None:
        flow, hass, _entry = self._flow(
            entry_data={},
            coordinator_data={"dev-X": {"state": "ready"}, "dev-Y": {}},
        )
        result = await flow.async_step_init(
            user_input={
                "connection_type": "cloud_only",
                "fallback_ip": "",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "create_entry"
        # Persisted: cloud-only sentinel + device_id from runtime
        call = hass.config_entries.async_update_entry.call_args
        assert call.kwargs["data"]["fallback_ip"] == ""
        assert call.kwargs["data"]["fallback_device_id"] == "dev-X"
        # Mode change → reload scheduled
        hass.async_create_task.assert_called_once()

    async def test_switch_local_to_cloud_only_without_device_errors(self) -> None:
        flow, hass, _entry = self._flow(entry_data={})  # no runtime, no device
        result = await flow.async_step_init(
            user_input={
                "connection_type": "cloud_only",
                "fallback_ip": "",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "no_device_id"}
        hass.config_entries.async_update_entry.assert_not_called()
        hass.async_create_task.assert_not_called()

    async def test_switch_cloud_only_to_local_pops_keys_and_reloads(self) -> None:
        flow, hass, _entry = self._flow(
            entry_data={"fallback_ip": "", "fallback_device_id": "dev1"},
        )
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                "fallback_ip": "",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "create_entry"
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert "fallback_ip" not in new_data
        assert "fallback_device_id" not in new_data
        hass.async_create_task.assert_called_once()

    async def test_cloud_only_ignores_typed_fallback_ip(self) -> None:
        """If the user types a LAN IP while picking cloud_only, the IP is dropped."""
        flow, hass, _entry = self._flow(
            entry_data={"fallback_ip": "", "fallback_device_id": "dev1"},
        )
        result = await flow.async_step_init(
            user_input={
                "connection_type": "cloud_only",
                "fallback_ip": "192.168.1.42",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
            }
        )
        assert result["type"] == "create_entry"
        new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data["fallback_ip"] == ""
        assert new_data["fallback_device_id"] == "dev1"
        # Same mode, no reload needed
        hass.async_create_task.assert_not_called()

    async def test_stay_local_set_fallback_ip_validates(self) -> None:
        flow, hass, _entry = self._flow(entry_data={})
        # Patch _probe_local_api at the module level
        from custom_components.v2c_cloud import config_flow as cf

        original = cf._probe_local_api
        cf._probe_local_api = AsyncMock(return_value=("dev-Z", None))
        try:
            result = await flow.async_step_init(
                user_input={
                    "connection_type": "local",
                    "fallback_ip": "192.168.1.50",
                    CONF_LOCAL_UPDATE_INTERVAL: 45,
                }
            )
        finally:
            cf._probe_local_api = original
        assert result["type"] == "create_entry"
        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        assert kwargs["data"]["fallback_ip"] == "192.168.1.50"
        assert kwargs["data"]["fallback_device_id"] == "dev-Z"
        assert kwargs["options"][CONF_LOCAL_UPDATE_INTERVAL] == 45
        # Same mode → no reload
        hass.async_create_task.assert_not_called()

    async def test_invalid_interval_rejected(self) -> None:
        flow, hass, _entry = self._flow(entry_data={})
        result = await flow.async_step_init(
            user_input={
                "connection_type": "local",
                "fallback_ip": "",
                CONF_LOCAL_UPDATE_INTERVAL: 9999,
            }
        )
        assert result["type"] == "form"
        assert result["errors"] == {CONF_LOCAL_UPDATE_INTERVAL: "invalid_interval"}
        hass.config_entries.async_update_entry.assert_not_called()
