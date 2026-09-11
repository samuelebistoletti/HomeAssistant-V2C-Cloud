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
    _known_device_ids,
)
from custom_components.v2c_cloud.const import (
    ATTR_IP_ADDRESS,
    CONF_API_KEY,
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_LAN_ONLY,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MANUAL_IPS,
    CONF_SET_MANUAL_IPS,
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


class TestManualIpSteps:
    """
    One form per charger, so the address field keeps a translatable label.

    The first attempt put one field per charger in the main options form, with
    keys built from the device id. Home Assistant resolves field labels from
    static translation keys, so the UI rendered the raw `manual_ip_<id>` string.
    """

    def _flow(self, entry: MagicMock) -> V2COptionsFlow:
        flow = V2COptionsFlow(entry)
        flow.hass = MagicMock()
        flow.hass.config_entries.async_update_entry = MagicMock()
        return flow

    def _entry_with(self, *device_ids: str, manual: dict[str, str] | None = None):
        return _entry(
            **{
                CONF_CLOUD_ONLY: False,
                CONF_CACHED_PAIRINGS: [
                    {"deviceId": d, "ip": "192.168.1.9"} for d in device_ids
                ],
                CONF_MANUAL_IPS: manual or {},
            }
        )

    async def test_init_form_has_no_device_specific_keys(self):
        """Regression: no schema key may carry a device id."""
        flow = self._flow(self._entry_with(DEVICE_ID, "SECOND"))
        result = await flow.async_step_init()

        assert result["type"] == "form"
        keys = {str(k) for k in result["data_schema"].schema}
        assert not any(DEVICE_ID in k or "SECOND" in k for k in keys)
        assert CONF_SET_MANUAL_IPS in keys

    async def test_opting_out_saves_without_extra_steps(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        result = await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: False,
            }
        )
        assert result["type"] == "create_entry"

    async def test_opting_in_asks_per_charger(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        result = await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        assert result["type"] == "form"
        assert result["step_id"] == "manual_ip"
        # The field itself is a static key; the charger id travels separately.
        assert (
            list(result["data_schema"].schema) == [ATTR_IP_ADDRESS]
            or str(next(iter(result["data_schema"].schema))) == ATTR_IP_ADDRESS
        )

    async def test_charger_id_travels_as_a_placeholder(self):
        """The id must reach the UI as a placeholder, not as a field name."""
        flow = self._flow(self._entry_with(DEVICE_ID))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        result = await flow.async_step_manual_ip()

        assert result["description_placeholders"] == {"device": DEVICE_ID}

    async def test_address_is_persisted(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        result = await flow.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})

        assert result["type"] == "create_entry"
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}

    async def test_every_charger_is_asked_in_turn(self):
        flow = self._flow(self._entry_with(DEVICE_ID, "SECOND"))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        first = await flow.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})
        assert first["step_id"] == "manual_ip"  # still asking, second charger

        second = await flow.async_step_manual_ip({ATTR_IP_ADDRESS: "192.168.1.60"})
        assert second["type"] == "create_entry"
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {
            DEVICE_ID: LAN_IP,
            "SECOND": "192.168.1.60",
        }

    @pytest.mark.parametrize(
        "bad_ip", ["8.8.8.8", "127.0.0.1", "169.254.1.5", "not-an-ip"]
    )
    async def test_invalid_address_is_refused(self, bad_ip):
        flow = self._flow(self._entry_with(DEVICE_ID))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        result = await flow.async_step_manual_ip({ATTR_IP_ADDRESS: bad_ip})

        assert result["type"] == "form"
        assert result["step_id"] == "manual_ip"

    async def test_empty_address_clears_the_override(self):
        flow = self._flow(self._entry_with(DEVICE_ID, manual={DEVICE_ID: LAN_IP}))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        await flow.async_step_manual_ip({ATTR_IP_ADDRESS: ""})

        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {}

    def test_known_ids_merge_cache_and_overrides(self):
        entry = _entry(
            **{
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                CONF_MANUAL_IPS: {"SECOND": "192.168.1.60"},
            }
        )
        assert set(_known_device_ids(entry)) == {DEVICE_ID, "SECOND"}
