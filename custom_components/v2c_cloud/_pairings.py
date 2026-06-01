"""
Shared helpers for the cached V2C ``(deviceId, ip)`` pairings list.

The cloud's ``/pairings/me`` endpoint is the source of truth for the
``(deviceId, ip)`` map. A normalised snapshot is persisted as
``entry.data['cached_pairings']`` so every charger remains addressable
during a cloud outage. These helpers live in their own module because
the same logic is consumed from two unrelated code paths — the
initial-setup + reauth flows in ``config_flow.py`` and the running
coordinator + migration in ``__init__.py`` — and previously each
maintained its own bit-for-bit copy that could drift independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# Defensive cap on the persisted list. Realistic accounts hold a handful
# of chargers; anything above this is either a runaway cloud response or
# tampered HA storage, and we'd rather truncate than load unbounded data
# into every entity refresh.
_MAX_CACHED_PAIRINGS = 64


def _normalise_pairings(raw: object) -> list[dict[str, str]]:
    """
    Reduce a pairings list to the ``(deviceId, ip)`` records we cache.

    Pure: never mutates ``raw``. Returns a freshly-allocated list of
    freshly-allocated dicts, capped at ``_MAX_CACHED_PAIRINGS`` records.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dev = item.get("deviceId") or item.get("device_id")
        if not isinstance(dev, str) or not dev:
            continue
        ip_raw = item.get("ip") or item.get("static_ip") or ""
        out.append({"deviceId": dev, "ip": str(ip_raw) if ip_raw else ""})
        if len(out) >= _MAX_CACHED_PAIRINGS:
            break
    return out


def _pairings_changed(
    a: list[dict[str, str]],
    b: list[dict[str, str]],
) -> bool:
    """Return True when two normalised pairing lists differ as sets."""
    set_a = {(p["deviceId"], p["ip"]) for p in a}
    set_b = {(p["deviceId"], p["ip"]) for p in b}
    return set_a != set_b


def _persist_pairings_if_changed(
    hass: HomeAssistant,
    entry: ConfigEntry,
    latest_pairings: list[dict[str, object]] | None,
) -> None:
    """
    Update ``entry.data['cached_pairings']`` when the cloud list changes.

    A no-op when the snapshot matches the cache or when the latest payload
    is empty / unparseable. ``latest_pairings`` is treated as read-only.
    """
    if not latest_pairings:
        return
    normalised = _normalise_pairings(latest_pairings)
    if not normalised:
        return
    # Normalise the cached side too: a malformed persisted entry (manual
    # edit, partial migration) would otherwise KeyError out of
    # _pairings_changed. _normalise_pairings is the trust boundary for
    # every read from entry.data["cached_pairings"].
    current = _normalise_pairings(entry.data.get("cached_pairings"))
    if not _pairings_changed(current, normalised):
        return
    new_data = dict(entry.data)
    new_data["cached_pairings"] = normalised
    hass.config_entries.async_update_entry(entry, data=new_data)
