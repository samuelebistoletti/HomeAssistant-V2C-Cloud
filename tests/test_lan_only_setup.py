"""
Phase 2 of the issue #54 plan: running without a reachable V2C cloud.

Covers the schema v3 additions (`manual_ips`, `lan_only`), the account-less
config-flow branch, and the per-charger IP overrides in the options flow.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.v2c_cloud.config_flow import (
    V2CConfigFlow,
    V2COptionsFlow,
    _collect_manual_ips,
    _known_device_ids,
    _manual_ip_field,
)
from custom_components.v2c_cloud.const import (
    CONF_API_KEY,
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_LAN_ONLY,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MANUAL_IPS,
    SCHEMA_VERSION,
)

DEVICE_ID = "XQUXDU"
LAN_IP = "192.168.1.50"


def _entry(**data: Any) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = data
    entry.options = {}
    return entry


# ---------------------------------------------------------------------------
# Config flow: setting up with no V2C account at all
# ---------------------------------------------------------------------------


class TestLanOnlyConfigFlow:
    """The charger itself supplies the device id — no cloud call is made."""

    def _flow(self) -> V2CConfigFlow:
        flow = V2CConfigFlow()
        flow.hass = MagicMock()
        return flow

    async def test_first_step_offers_both_paths(self):
        result = await self._flow().async_step_user()
        assert result["type"] == "menu"
        assert set(result["menu_options"]) == {"cloud", "lan_only"}

    async def test_entry_is_created_from_a_probe(self):
        flow = self._flow()
        with patch(
            "custom_components.v2c_cloud.config_flow._probe_local_api",
            new=AsyncMock(return_value=(DEVICE_ID, None)),
        ):
            result = await flow.async_step_lan_only({"ip_address": LAN_IP})

        data = result["data"]
        assert data[CONF_LAN_ONLY] is True
        assert data[CONF_CLOUD_ONLY] is False
        assert data[CONF_API_KEY] == ""
        assert data[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}
        assert data[CONF_CACHED_PAIRINGS] == [{"deviceId": DEVICE_ID, "ip": LAN_IP}]

    async def test_unreachable_charger_is_reported(self):
        flow = self._flow()
        with patch(
            "custom_components.v2c_cloud.config_flow._probe_local_api",
            new=AsyncMock(return_value=(None, "cannot_connect_local")),
        ):
            result = await flow.async_step_lan_only({"ip_address": LAN_IP})

        assert result["type"] == "form"
        assert result["step_id"] == "lan_only"

    async def test_public_address_never_creates_an_entry(self):
        """The probe applies the SSRF policy; the flow must not bypass it."""
        flow = self._flow()
        with patch(
            "custom_components.v2c_cloud.config_flow._probe_local_api",
            new=AsyncMock(return_value=(None, "invalid_ip")),
        ):
            result = await flow.async_step_lan_only({"ip_address": "8.8.8.8"})

        assert result["type"] == "form"

    async def test_flow_version_matches_schema(self):
        assert V2CConfigFlow.VERSION == SCHEMA_VERSION == 3


# ---------------------------------------------------------------------------
# Manual IP overrides
# ---------------------------------------------------------------------------


class TestManualIpCollection:
    """Overrides are validated with the same policy as the write path."""

    def test_valid_private_ip_is_kept(self):
        errors: dict[str, str] = {}
        result = _collect_manual_ips(
            {_manual_ip_field(DEVICE_ID): LAN_IP}, [DEVICE_ID], errors
        )
        assert result == {DEVICE_ID: LAN_IP}
        assert errors == {}

    def test_empty_field_clears_the_override(self):
        errors: dict[str, str] = {}
        result = _collect_manual_ips(
            {_manual_ip_field(DEVICE_ID): "   "}, [DEVICE_ID], errors
        )
        assert result == {}
        assert errors == {}

    @pytest.mark.parametrize(
        "bad_ip", ["8.8.8.8", "127.0.0.1", "169.254.1.5", "0.0.0.0", "not-an-ip"]
    )
    def test_non_private_or_malformed_is_rejected(self, bad_ip):
        errors: dict[str, str] = {}
        result = _collect_manual_ips(
            {_manual_ip_field(DEVICE_ID): bad_ip}, [DEVICE_ID], errors
        )
        assert result == {}
        assert _manual_ip_field(DEVICE_ID) in errors

    def test_one_bad_entry_does_not_discard_the_others(self):
        errors: dict[str, str] = {}
        result = _collect_manual_ips(
            {
                _manual_ip_field(DEVICE_ID): LAN_IP,
                _manual_ip_field("SECOND"): "8.8.8.8",
            },
            [DEVICE_ID, "SECOND"],
            errors,
        )
        assert result == {DEVICE_ID: LAN_IP}
        assert list(errors) == [_manual_ip_field("SECOND")]

    def test_known_ids_merge_cache_and_overrides(self):
        entry = _entry(
            **{
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                CONF_MANUAL_IPS: {"SECOND": "192.168.1.60"},
            }
        )
        assert set(_known_device_ids(entry)) == {DEVICE_ID, "SECOND"}


class TestOptionsFlowPersistsOverrides:
    """The options flow writes overrides into entry.data, where the resolver reads them."""

    async def _submit(self, entry: MagicMock, user_input: dict[str, Any]) -> Any:
        flow = V2COptionsFlow(entry)
        flow.hass = MagicMock()
        flow.hass.config_entries.async_update_entry = MagicMock()
        result = await flow.async_step_init(user_input)
        return flow, result

    async def test_override_is_written_to_entry_data(self):
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": "192.168.1.9"}],
            }
        )
        flow, _ = await self._submit(
            entry,
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                _manual_ip_field(DEVICE_ID): LAN_IP,
            },
        )
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}

    async def test_invalid_override_blocks_the_save(self):
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            }
        )
        flow, result = await self._submit(
            entry,
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                _manual_ip_field(DEVICE_ID): "8.8.8.8",
            },
        )
        assert result["type"] == "form"
        flow.hass.config_entries.async_update_entry.assert_not_called()

    async def test_clearing_the_field_removes_the_override(self):
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP},
            }
        )
        flow, _ = await self._submit(
            entry,
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                _manual_ip_field(DEVICE_ID): "",
            },
        )
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {}
