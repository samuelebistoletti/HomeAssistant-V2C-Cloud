"""
Running without a reachable V2C cloud.

Covers the schema v3 additions (`manual_ips`, `lan_only`), the account-less
config-flow branch, and the per-charger IP overrides in the options flow.
"""

from __future__ import annotations

from types import MappingProxyType
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
    # mappingproxy, as Home Assistant really exposes it.
    entry.data = MappingProxyType(dict(data))
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

    async def test_cloud_only_entry_is_still_offered_manual_ips(self):
        """
        The checkbox must be available on a 4G entry too.

        Converting a cloud-only entry to Wi-Fi is exactly when the address has
        to be typed by hand — the cloud that would otherwise supply it is the
        thing that is down. Hiding the checkbox based on the *current* mode
        forced the user to save, reload and reopen Options first.
        """
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            }
        )
        result = await self._flow(entry).async_step_init()

        assert CONF_SET_MANUAL_IPS in {str(k) for k in result["data_schema"].schema}

    async def test_switching_from_cloud_only_to_local_asks_for_the_address(self):
        """The whole conversion happens in one pass."""
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": ""}],
            }
        )
        flow = self._flow(entry)
        result = await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        assert result["step_id"] == "manual_ip"

        final = await flow.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})
        assert final["type"] == "create_entry"
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_CLOUD_ONLY] is False
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}

    async def test_switching_to_cloud_only_skips_the_forms(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        result = await flow.async_step_init(
            {
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        assert result["type"] == "create_entry"

    async def test_nothing_is_persisted_until_the_flow_completes(self):
        """
        Abandoning a later form must leave the entry untouched.

        The mode change used to be written — and the reload scheduled — as
        soon as the first step was submitted, so a user who closed the dialog
        on the address form ended up with a half-applied configuration and an
        integration reloading underneath the open flow.
        """
        flow = self._flow(self._entry_with(DEVICE_ID))
        await flow.async_step_init(
            {
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: False,
            }
        )
        flow.hass.config_entries.async_update_entry.reset_mock()

        flow2 = self._flow(self._entry_with(DEVICE_ID))
        await flow2.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        # Still inside the manual-IP form: nothing written, no reload queued.
        flow2.hass.config_entries.async_update_entry.assert_not_called()
        flow2.hass.async_create_task.assert_not_called()

        await flow2.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})
        flow2.hass.config_entries.async_update_entry.assert_called_once()

    async def test_reload_is_scheduled_once_at_the_end(self):
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
            }
        )
        flow = self._flow(entry)
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        assert flow.hass.async_create_task.call_count == 0

        await flow.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})
        assert flow.hass.async_create_task.call_count == 1

    async def test_cloud_updates_during_the_flow_are_not_lost(self):
        """
        The commit must merge into entry.data as it stands, not a snapshot.

        The cloud coordinator keeps running while the user fills in the
        per-charger forms and can persist a newly discovered charger into
        `cached_pairings`. Writing back the snapshot taken at the first step
        would drop it, and the lost address could leave that charger
        unreachable the next time the cloud goes down.
        """
        entry = self._entry_with(DEVICE_ID)
        flow = self._flow(entry)

        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )

        # Meanwhile the cloud discovers a second charger and persists it.
        entry.data = MappingProxyType(
            {
                **dict(entry.data),
                CONF_CACHED_PAIRINGS: [
                    {"deviceId": DEVICE_ID, "ip": "192.168.1.9"},
                    {"deviceId": "DISCOVERED", "ip": "192.168.1.77"},
                ],
            }
        )

        await flow.async_step_manual_ip({ATTR_IP_ADDRESS: LAN_IP})

        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert {p["deviceId"] for p in written[CONF_CACHED_PAIRINGS]} == {
            DEVICE_ID,
            "DISCOVERED",
        }
        # ...and the flow's own edits are still applied.
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}
        assert written[CONF_CLOUD_ONLY] is False

    # -- the box reports state, it is not just a door ------------------------

    @staticmethod
    def _checkbox_default(result: dict[str, Any]) -> bool:
        """Read the rendered default of the manual-IP checkbox."""
        for key in result["data_schema"].schema:
            if str(key) == CONF_SET_MANUAL_IPS:
                default = key.default
                return bool(default() if callable(default) else default)
        raise AssertionError(f"{CONF_SET_MANUAL_IPS} missing from the options form")

    async def test_box_is_ticked_when_overrides_are_stored(self):
        """
        Regression: the box used to default to off on every visit.

        It read as "manual addresses are not configured" to anyone reopening
        the dialog, even with addresses stored and in use.
        """
        flow = self._flow(self._entry_with(DEVICE_ID, manual={DEVICE_ID: LAN_IP}))
        result = await flow.async_step_init()

        assert self._checkbox_default(result) is True

    async def test_box_is_clear_when_no_override_is_stored(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        result = await flow.async_step_init()

        assert self._checkbox_default(result) is False

    async def test_stored_addresses_are_shown_in_the_form(self):
        """The options dialog is the only place these addresses can be read."""
        flow = self._flow(
            self._entry_with(
                DEVICE_ID,
                "SECOND",
                manual={DEVICE_ID: LAN_IP, "SECOND": "192.168.1.60"},
            )
        )
        result = await flow.async_step_init()

        shown = result["description_placeholders"]["manual_ips"]
        assert DEVICE_ID in shown
        assert LAN_IP in shown
        assert "SECOND" in shown
        assert "192.168.1.60" in shown

    async def test_no_stored_addresses_reads_as_none(self):
        flow = self._flow(self._entry_with(DEVICE_ID))
        result = await flow.async_step_init()

        assert result["description_placeholders"]["manual_ips"] == "—"

    async def test_prefills_the_address_already_in_force(self):
        flow = self._flow(self._entry_with(DEVICE_ID, manual={DEVICE_ID: LAN_IP}))
        await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )
        result = await flow.async_step_manual_ip()

        key = next(iter(result["data_schema"].schema))
        assert key.description == {"suggested_value": LAN_IP}

    async def test_clearing_the_box_drops_every_override(self):
        """Unticking is how an address goes back to cloud discovery."""
        flow = self._flow(
            self._entry_with(
                DEVICE_ID,
                "SECOND",
                manual={DEVICE_ID: LAN_IP, "SECOND": "192.168.1.60"},
            )
        )
        result = await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: False,
            }
        )

        assert result["type"] == "create_entry"
        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {}

    async def test_switching_to_cloud_only_keeps_the_overrides(self):
        """
        A 4G stint must not cost the addresses.

        They are inert while the entry is cloud-only and are needed again the
        moment it goes back to Wi-Fi — which is exactly when the cloud may be
        unable to supply them.
        """
        flow = self._flow(self._entry_with(DEVICE_ID, manual={DEVICE_ID: LAN_IP}))
        await flow.async_step_init(
            {
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: False,
            }
        )

        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}

    async def test_clearing_the_box_works_on_a_cloud_only_entry_too(self):
        """
        The box is shown on 4G entries and says it removes the addresses.

        Gating the clear on the destination being LAN made that promise a
        no-op for an entry that was already Cloud only: the only way to drop
        an address was to detour through Local (Wi-Fi) and back.
        """
        entry = _entry(
            **{
                CONF_CLOUD_ONLY: True,
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP},
            }
        )
        flow = self._flow(entry)
        await flow.async_step_init(
            {
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: False,
            }
        )

        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {}

    async def test_leaving_the_box_alone_on_a_cloud_only_entry_keeps_them(self):
        flow = self._flow(
            _entry(
                **{
                    CONF_CLOUD_ONLY: True,
                    CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                    CONF_MANUAL_IPS: {DEVICE_ID: LAN_IP},
                }
            )
        )
        await flow.async_step_init(
            {
                "connection_type": "cloud_only",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )

        written = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert written[CONF_MANUAL_IPS] == {DEVICE_ID: LAN_IP}

    async def test_opting_in_with_no_known_charger_reports_an_error(self):
        """Silently saving nothing would look like the box never stuck."""
        flow = self._flow(_entry(**{CONF_CLOUD_ONLY: False}))
        result = await flow.async_step_init(
            {
                "connection_type": "local",
                CONF_LOCAL_UPDATE_INTERVAL: 30,
                CONF_SET_MANUAL_IPS: True,
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        assert result["errors"] == {CONF_SET_MANUAL_IPS: "no_known_devices"}
        flow.hass.config_entries.async_update_entry.assert_not_called()

    def test_known_ids_merge_cache_and_overrides(self):
        entry = _entry(
            **{
                CONF_CACHED_PAIRINGS: [{"deviceId": DEVICE_ID, "ip": LAN_IP}],
                CONF_MANUAL_IPS: {"SECOND": "192.168.1.60"},
            }
        )
        assert set(_known_device_ids(entry)) == {DEVICE_ID, "SECOND"}
