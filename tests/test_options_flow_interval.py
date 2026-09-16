"""Tests for the local_update_interval option (added in 1.3.0)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.v2c_cloud.const import (
    CONF_LOCAL_UPDATE_INTERVAL,
    DEFAULT_LOCAL_INTERVAL,
    MAX_LOCAL_INTERVAL,
    MIN_LOCAL_INTERVAL,
)
from custom_components.v2c_cloud.local_api import _build_local_interval


class TestBuildLocalInterval:
    """`_build_local_interval` is the source of truth for resolving the cadence."""

    def test_default_when_no_option(self) -> None:
        td = _build_local_interval({}, {})
        assert isinstance(td, timedelta)
        assert td.total_seconds() == DEFAULT_LOCAL_INTERVAL

    def test_uses_custom_option_when_present(self) -> None:
        td = _build_local_interval({}, {CONF_LOCAL_UPDATE_INTERVAL: 45})
        assert td.total_seconds() == 45

    def test_cloud_only_overrides_user_option(self) -> None:
        """A device flagged as cloud-only always uses CLOUD_ONLY_UPDATE_INTERVAL."""
        td = _build_local_interval(
            {"cloud_only": True}, {CONF_LOCAL_UPDATE_INTERVAL: 10}
        )
        # CLOUD_ONLY_UPDATE_INTERVAL is 120s
        assert td.total_seconds() == 120

    def test_local_with_cloud_only_false(self) -> None:
        td = _build_local_interval(
            {"cloud_only": False}, {CONF_LOCAL_UPDATE_INTERVAL: 5}
        )
        assert td.total_seconds() == 5

    def test_invalid_option_falls_back_to_default(self) -> None:
        td = _build_local_interval({}, {CONF_LOCAL_UPDATE_INTERVAL: "not-int"})
        assert td.total_seconds() == DEFAULT_LOCAL_INTERVAL


class TestOptionsBounds:
    """Ensure the configured bounds are sensible."""

    def test_min_is_5(self) -> None:
        assert MIN_LOCAL_INTERVAL == 5

    def test_max_is_300(self) -> None:
        assert MAX_LOCAL_INTERVAL == 300

    def test_default_within_bounds(self) -> None:
        assert MIN_LOCAL_INTERVAL <= DEFAULT_LOCAL_INTERVAL <= MAX_LOCAL_INTERVAL


class TestOptionsListenerApplyInterval:
    """The update listener should propagate options to local coordinators."""

    @pytest.fixture
    def hass(self) -> Any:
        h = MagicMock()
        h.data = {"v2c_cloud": {}}
        return h

    @pytest.fixture
    def entry(self) -> Any:
        e = MagicMock()
        e.entry_id = "abc"
        e.data = {"cloud_only": False}
        e.options = {CONF_LOCAL_UPDATE_INTERVAL: 60}
        return e

    async def test_listener_updates_coordinator_interval(self, hass, entry) -> None:
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_options_updated,
        )

        coord_a = MagicMock()
        coord_a.update_interval = timedelta(seconds=30)
        coord_b = MagicMock()
        coord_b.update_interval = timedelta(seconds=30)
        runtime = V2CEntryRuntimeData(
            client=MagicMock(),
            coordinator=MagicMock(),
            local_coordinators={"dev1": coord_a, "dev2": coord_b},
            cloud_only=False,
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        assert coord_a.update_interval == timedelta(seconds=60)
        assert coord_b.update_interval == timedelta(seconds=60)
        hass.async_create_task.assert_not_called()

    async def test_listener_skips_cloud_only(self, hass, entry) -> None:
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_options_updated,
        )

        # Cloud-only device, and the runtime already reflects it — no mode
        # change here, just confirming the interval update is skipped.
        entry.data = {"cloud_only": True}
        coord = MagicMock()
        coord.update_interval = timedelta(seconds=120)
        runtime = V2CEntryRuntimeData(
            client=MagicMock(),
            coordinator=MagicMock(),
            local_coordinators={"dev1": coord},
            cloud_only=True,
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        # The cloud-only coordinator must NOT be touched by the listener.
        assert coord.update_interval == timedelta(seconds=120)
        hass.async_create_task.assert_not_called()


class TestOptionsListenerReloadsOnModeChange:
    """
    The update listener is now the ONLY place a reload is scheduled.

    HA treats a config flow calling async_reload directly, on an entry that
    also has an update listener, as a deprecated double-reload pattern
    (warns on HA core 2026.9, breaks in 2026.12.0). So V2COptionsFlow no
    longer reloads itself on a connection_type change: this listener detects
    the mismatch between the freshly-updated entry data and the runtime's
    last-known cloud_only flag, and reloads from here instead.
    """

    @pytest.fixture
    def hass(self) -> Any:
        h = MagicMock()
        h.data = {"v2c_cloud": {}}
        h.config_entries.async_reload = MagicMock()

        def _capture_task(coro: Any) -> Any:
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        h.async_create_task = MagicMock(side_effect=_capture_task)
        return h

    async def test_cloud_only_flip_schedules_reload(self, hass) -> None:
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_options_updated,
        )

        entry = MagicMock()
        entry.entry_id = "abc"
        entry.data = {"cloud_only": True}
        entry.options = {}
        runtime = V2CEntryRuntimeData(
            client=MagicMock(), coordinator=MagicMock(), cloud_only=False
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        hass.async_create_task.assert_called_once()
        hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)

    async def test_no_flip_does_not_reload(self, hass) -> None:
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_options_updated,
        )

        entry = MagicMock()
        entry.entry_id = "abc"
        entry.data = {"cloud_only": False}
        entry.options = {}
        runtime = V2CEntryRuntimeData(
            client=MagicMock(), coordinator=MagicMock(), cloud_only=False
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        hass.async_create_task.assert_not_called()
