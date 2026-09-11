"""
Tests for `async_unload_entry` — local-coordinator shutdown.

Regression cover for the bug reported through a user log in issue #54:
`DataUpdateCoordinator.async_shutdown` is a coroutine function, and it was
being CALLED but never AWAITED. The visible symptom was
`RuntimeWarning: coroutine 'DataUpdateCoordinator.async_shutdown' was never
awaited`; the real damage is that nothing was cancelled, so every unload or
reload leaked the coordinator's scheduled refresh timer.
"""

from __future__ import annotations

import gc
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.v2c_cloud import V2CEntryRuntimeData, async_unload_entry
from custom_components.v2c_cloud.const import DOMAIN

ENTRY_ID = "entry-unload-1"


def _hass_and_entry(runtime: Any) -> tuple[MagicMock, MagicMock]:
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.data = {DOMAIN: {ENTRY_ID: runtime}}
    hass.services.async_remove = MagicMock()
    hass.services.has_service.return_value = True

    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    return hass, entry


def _runtime(local_coordinators: dict[str, Any]) -> Any:
    runtime = MagicMock(spec=V2CEntryRuntimeData)
    runtime.local_coordinators = local_coordinators
    return runtime


class TestLocalCoordinatorShutdown:
    """Every local coordinator must be shut down exactly once, and awaited."""

    async def test_async_shutdown_is_awaited(self):
        coord = MagicMock()
        coord.async_shutdown = AsyncMock(return_value=None)
        hass, entry = _hass_and_entry(_runtime({"dev-1": coord}))

        assert await async_unload_entry(hass, entry) is True

        coord.async_shutdown.assert_awaited_once()

    async def test_every_coordinator_is_shut_down(self):
        coords = {}
        for dev in ("dev-1", "dev-2", "dev-3"):
            c = MagicMock()
            c.async_shutdown = AsyncMock(return_value=None)
            coords[dev] = c
        hass, entry = _hass_and_entry(_runtime(coords))

        await async_unload_entry(hass, entry)

        for dev, c in coords.items():
            c.async_shutdown.assert_awaited_once(), dev

    async def test_falls_back_to_unsub_refresh(self):
        """Coordinators without async_shutdown use the _unsub_refresh handle."""

        class _LegacyCoordinator:
            def __init__(self) -> None:
                self._unsub_refresh = MagicMock()

        coord = _LegacyCoordinator()
        hass, entry = _hass_and_entry(_runtime({"dev-1": coord}))

        await async_unload_entry(hass, entry)

        coord._unsub_refresh.assert_called_once()

    async def test_synchronous_shutdown_is_not_awaited(self):
        """A stub exposing a plain callable must not raise on await."""
        coord = MagicMock()
        coord.async_shutdown = MagicMock(return_value=None)
        hass, entry = _hass_and_entry(_runtime({"dev-1": coord}))

        assert await async_unload_entry(hass, entry) is True

        coord.async_shutdown.assert_called_once()

    async def test_entry_is_removed_from_hass_data(self):
        coord = MagicMock()
        coord.async_shutdown = AsyncMock(return_value=None)
        hass, entry = _hass_and_entry(_runtime({"dev-1": coord}))

        await async_unload_entry(hass, entry)

        assert ENTRY_ID not in hass.data[DOMAIN]

    async def test_failed_platform_unload_skips_shutdown(self):
        """Nothing is torn down when HA refuses to unload the platforms."""
        coord = MagicMock()
        coord.async_shutdown = AsyncMock(return_value=None)
        hass, entry = _hass_and_entry(_runtime({"dev-1": coord}))
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        assert await async_unload_entry(hass, entry) is False

        coord.async_shutdown.assert_not_awaited()
        assert ENTRY_ID in hass.data[DOMAIN]


class TestNoUnawaitedCoroutineWarning:
    """The original symptom: a coroutine created and dropped on the floor."""

    async def test_coroutine_runs_and_emits_no_runtime_warning(self, recwarn):
        """
        A coordinator shaped like HA's real one must actually execute.

        Before the fix the coroutine was created, never awaited, and garbage
        collected with a RuntimeWarning — so the body below never ran.
        """
        shutdown_calls: list[str] = []

        class _RealisticCoordinator:
            async def async_shutdown(self) -> None:
                shutdown_calls.append("called")

        hass, entry = _hass_and_entry(_runtime({"dev-1": _RealisticCoordinator()}))

        await async_unload_entry(hass, entry)
        gc.collect()  # force finalisation of any dropped coroutine

        assert shutdown_calls == ["called"]
        assert [w for w in recwarn if issubclass(w.category, RuntimeWarning)] == []
