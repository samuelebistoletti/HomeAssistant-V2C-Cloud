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
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        assert coord_a.update_interval == timedelta(seconds=60)
        assert coord_b.update_interval == timedelta(seconds=60)

    async def test_listener_skips_cloud_only(self, hass, entry) -> None:
        from custom_components.v2c_cloud import (
            V2CEntryRuntimeData,
            _async_options_updated,
        )

        # Cloud-only device
        entry.data = {"cloud_only": True}
        coord = MagicMock()
        coord.update_interval = timedelta(seconds=120)
        runtime = V2CEntryRuntimeData(
            client=MagicMock(),
            coordinator=MagicMock(),
            local_coordinators={"dev1": coord},
        )
        hass.data["v2c_cloud"][entry.entry_id] = runtime

        await _async_options_updated(hass, entry)

        # The cloud-only coordinator must NOT be touched by the listener.
        assert coord.update_interval == timedelta(seconds=120)
