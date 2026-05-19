"""Shared networking helpers for the V2C Cloud integration."""

from __future__ import annotations

import ipaddress


def validate_private_ip(addr: str | None) -> tuple[bool, str | None]:
    """
    Validate that a user-supplied IP is safe for outbound HTTP calls.

    Returns ``(is_safe, error_translation_key)``. The boolean is ``True`` only
    when the address parses as a private, non-loopback, non-link-local,
    non-unspecified IPv4/IPv6 host. On any failure, the returned translation
    key matches the strings.json schema (``cannot_connect_local`` for both
    parse errors and policy violations — the user-facing UX is the same).

    Python 3.11+ classifies link-local addresses (e.g. ``169.254.x.x``) as
    ``is_private=True``, so an explicit ``is_link_local`` check is required.
    """
    if not addr:
        return False, "cannot_connect_local"
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return False, "cannot_connect_local"
    if (
        not parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_unspecified
    ):
        return False, "cannot_connect_local"
    return True, None
