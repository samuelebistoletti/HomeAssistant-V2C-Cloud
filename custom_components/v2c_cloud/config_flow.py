"""Config flow for the V2C Cloud integration."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import async_timeout
import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from ._net import validate_private_ip
from ._pairings import _normalise_pairings
from .const import (
    ATTR_IP_ADDRESS,
    CONF_API_KEY,
    CONF_CACHED_PAIRINGS,
    CONF_CLOUD_ONLY,
    CONF_LAN_ONLY,
    CONF_LOCAL_UPDATE_INTERVAL,
    CONF_MANUAL_IPS,
    CONF_SET_MANUAL_IPS,
    DEFAULT_LOCAL_INTERVAL,
    DOMAIN,
    MAX_LOCAL_INTERVAL,
    MIN_LOCAL_INTERVAL,
    SCHEMA_VERSION,
)
from .v2c_cloud import V2CAuthError, V2CClient, V2CRequestError


def _infer_connection_type(entry_data: dict[str, Any]) -> str:
    """
    Infer the declared connection mode from stored entry data.

    Cloud-only is encoded by ``entry_data['cloud_only'] is True``.
    Anything else is treated as local.
    """
    return "cloud_only" if entry_data.get("cloud_only") else "local"


_LOGGER = logging.getLogger(__name__)

_LOCAL_PROBE_TIMEOUT = 10


async def _validate_api_key(
    hass: HomeAssistant,
    api_key: str,
) -> list[dict[str, Any]]:
    """Ensure the provided API key works and return pairings."""
    session = aiohttp_client.async_get_clientsession(hass)
    client = V2CClient(session, api_key)
    return await client.async_get_pairings()


async def _probe_local_api(
    hass: HomeAssistant,
    ip: str,
) -> tuple[str | None, str | None]:
    """
    Probe the charger's local RealTimeData endpoint.

    Returns (device_id, None) on success or (None, error_key) on failure.
    """
    is_safe, error_key = validate_private_ip(ip)
    if not is_safe:
        return None, error_key

    session = aiohttp_client.async_get_clientsession(hass)
    url = f"http://{ip}/RealTimeData"
    try:
        async with (
            async_timeout.timeout(_LOCAL_PROBE_TIMEOUT),
            session.get(url) as response,
        ):
            if response.status >= 400:  # noqa: PLR2004
                return None, "cannot_connect_local"
            text = (await response.text()).strip().rstrip("%").strip()
            payload = json.loads(text)
            device_id = payload.get("ID") or payload.get("id")
            if not device_id:
                return None, "no_device_id"
            return str(device_id), None
    except (TimeoutError, ClientError, json.JSONDecodeError):
        return None, "cannot_connect_local"


def _describe_overrides(manual_ips: dict[str, str]) -> str:
    """
    Render the stored address overrides for the options dialog.

    The options form is the only place these addresses can be seen, so it
    shows them rather than merely offering to change them. The em dash stands
    in for "none set" because a placeholder cannot be translated.
    """
    if not manual_ips:
        return "—"
    return ", ".join(
        f"{device_id} → {ip}" for device_id, ip in sorted(manual_ips.items())
    )


def _known_device_ids(entry: ConfigEntry) -> list[str]:
    """Return every charger id the entry knows about, cache plus overrides."""
    ids = [
        pairing["deviceId"]
        for pairing in _normalise_pairings(entry.data.get(CONF_CACHED_PAIRINGS))
    ]
    overrides = entry.data.get(CONF_MANUAL_IPS)
    if isinstance(overrides, dict):
        ids.extend(device_id for device_id in overrides if device_id not in ids)
    return ids


class V2CConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for V2C Cloud."""

    VERSION = SCHEMA_VERSION

    def __init__(self) -> None:
        """Initialise flow state."""
        super().__init__()
        self._api_key: str = ""
        self._pairings: list[dict[str, Any]] = []

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry: ConfigEntry) -> V2COptionsFlow:
        """Return the options flow handler."""
        return V2COptionsFlow(config_entry)

    async def async_step_user(
        self,
        _user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Ask whether to set the integration up with or without a V2C account.

        The LAN-only branch exists because the cloud is not always available:
        during the 2026-09 V2C authentication outage a fresh install was
        impossible even for chargers sitting on the same network as Home
        Assistant (issue #54).
        """
        return self.async_show_menu(step_id="user", menu_options=["cloud", "lan_only"])

    async def async_step_lan_only(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Set the integration up against a charger on the LAN, with no account.

        The charger's own ``/RealTimeData`` response supplies the device id, so
        the user only has to provide an address. No cloud call is made here or
        later: cloud-only controls stay unavailable for this entry.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = str(user_input[ATTR_IP_ADDRESS]).strip()
            device_id, error_key = await _probe_local_api(self.hass, ip)
            if error_key or not device_id:
                errors["base"] = error_key or "cannot_connect_local"
            else:
                await self.async_set_unique_id(f"lan:{device_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"V2C {device_id} (LAN)",
                    data={
                        CONF_API_KEY: "",
                        CONF_LAN_ONLY: True,
                        CONF_CLOUD_ONLY: False,
                        CONF_CACHED_PAIRINGS: [{"deviceId": device_id, "ip": ip}],
                        CONF_MANUAL_IPS: {device_id: ip},
                    },
                )

        return self.async_show_form(
            step_id="lan_only",
            data_schema=vol.Schema({vol.Required(ATTR_IP_ADDRESS): str}),
            errors=errors,
        )

    async def async_step_cloud(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Handle the cloud-account step.

        Requires the cloud to be reachable: the API key is validated and the
        full pairings list (every charger linked to the account) is captured
        for persistence as ``cached_pairings``. A user-typed fallback IP is
        no longer collected — the per-device IP is sourced from the cloud's
        ``/pairings/me`` response and kept in sync automatically.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                pairings = await _validate_api_key(self.hass, api_key)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001 — last-resort guard for the flow
                # Use error+type instead of exception() to avoid logging
                # exception args (a future API-key-bearing exception message
                # would otherwise land in the traceback).
                _LOGGER.error(  # noqa: TRY400 — type-only on purpose (see comment)
                    "Unexpected error while validating API key: %s",
                    type(err).__name__,
                )
                errors["base"] = "unknown"
            else:
                self._api_key = api_key
                self._pairings = pairings
                return await self.async_step_connection_type()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_connection_type(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Ask the user how their charger connects to the network."""
        if user_input is not None:
            connection = user_input["connection_type"]

            unique_suffix = hashlib.pbkdf2_hmac(
                "sha256",
                self._api_key.encode(),
                b"v2c_cloud_unique_id",
                200_000,
            ).hex()
            await self.async_set_unique_id(unique_suffix)
            self._abort_if_unique_id_configured()

            cached_pairings = _normalise_pairings(self._pairings)
            return self.async_create_entry(
                title="V2C Cloud",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_CACHED_PAIRINGS: cached_pairings,
                    CONF_CLOUD_ONLY: connection == "cloud_only",
                    CONF_LAN_ONLY: False,
                    CONF_MANUAL_IPS: {},
                },
            )

        schema = vol.Schema(
            {
                vol.Required("connection_type", default="local"): SelectSelector(
                    SelectSelectorConfig(
                        options=["local", "cloud_only"],
                        translation_key="connection_type",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="connection_type",
            data_schema=schema,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Allow the user to change the API key from the integration panel."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                await _validate_api_key(self.hass, api_key)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                # Cloud unreachable or pairings endpoint restricted — save the key
                # anyway; the coordinator will validate connectivity on the next refresh.
                _LOGGER.warning(
                    "V2C Cloud unavailable during reconfigure; saving new API key without cloud validation"
                )
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_API_KEY: api_key},
                )
            except Exception as err:  # noqa: BLE001 — last-resort guard for the flow
                _LOGGER.error(  # noqa: TRY400 — type-only on purpose (see comment)
                    "Unexpected error while validating API key: %s",
                    type(err).__name__,
                )
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_API_KEY: api_key},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY,
                    default=reconfigure_entry.data.get(CONF_API_KEY, ""),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(self, _entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthentication when the API key expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm reauthentication by asking for a new API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            pairings: list[dict[str, Any]] = []
            try:
                pairings = await _validate_api_key(self.hass, api_key)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                # Cloud unreachable or pairings endpoint restricted — save the key
                # anyway; the coordinator will validate connectivity on the next refresh.
                _LOGGER.warning(
                    "V2C Cloud unavailable during reauth; saving new API key without cloud validation"
                )
            except Exception as err:  # noqa: BLE001 — last-resort guard for the flow
                _LOGGER.error(  # noqa: TRY400 — type-only on purpose (see comment)
                    "Unexpected error while validating API key: %s",
                    type(err).__name__,
                )
                errors["base"] = "unknown"

            if not errors:
                reauth_entry = self._get_reauth_entry()
                updates: dict[str, Any] = {CONF_API_KEY: api_key}
                if pairings:
                    updates["cached_pairings"] = _normalise_pairings(pairings)
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    reason="reauth_successful",
                    data_updates=updates,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )


class V2COptionsFlow(config_entries.OptionsFlow):
    """
    Allow post-setup tweaks: connection type + local refresh interval.

    The per-device LAN IP is auto-discovered from the cloud's
    ``/pairings/me`` response and kept in sync via ``cached_pairings``;
    no manual fallback IP is exposed to the user.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry
        self._pending_devices: list[str] = []
        self._manual_ips: dict[str, str] = {}
        self._pending_changes: dict[str, Any] = {}
        self._pending_options: dict[str, Any] = {}
        self._mode_changed: bool = False

    def _apply(
        self,
        changes: dict[str, Any],
        new_options: dict[str, Any],
        *,
        mode_changed: bool,
    ) -> FlowResult:
        """
        Commit the whole options flow at once, as its final act.

        Persisting earlier would leave the entry half-updated if the user
        abandons a later step, and would reload the integration while the flow
        is still open — rebuilding the coordinators without the addresses the
        user is in the middle of typing.

        ``changes`` carries only the keys this flow actually edited, and they
        are merged into ``entry.data`` as it stands RIGHT NOW rather than into
        the snapshot taken when the first step was shown. While the user works
        through the per-charger forms the cloud coordinator keeps running and
        may persist a freshly discovered charger into ``cached_pairings``;
        writing back the snapshot would drop it, and the lost address could
        leave that charger unreachable the next time the cloud goes down.

        ``entry.data`` goes through async_update_entry; ``entry.options`` is
        written by the async_create_entry return value, the canonical HA
        pattern for options-flow output (passing ``data={}`` there would
        overwrite the options just set).
        """
        new_data = dict(self._config_entry.data)
        new_data.update(changes)
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

        if mode_changed:
            # Switching modes restructures the coordinator topology (cloud-only
            # vs LAN polling), so the entry must be reloaded. Scheduled rather
            # than awaited: reloading inline re-enters the still-open flow.
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._config_entry.entry_id)
            )

        return self.async_create_entry(title="", data=new_options)

    async def async_step_manual_ip(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Ask for one charger's IP override, one charger per form.

        A separate step per charger is what makes the field translatable: the
        charger id travels in the step title as a placeholder, leaving the
        field itself on a static key.
        """
        errors: dict[str, str] = {}
        device_id = self._pending_devices[0]

        if user_input is not None:
            raw = str(user_input.get(ATTR_IP_ADDRESS, "") or "").strip()
            if not raw:
                self._manual_ips.pop(device_id, None)
            else:
                is_safe, error_key = validate_private_ip(raw)
                if not is_safe:
                    errors[ATTR_IP_ADDRESS] = error_key or "cannot_connect_local"
                else:
                    self._manual_ips[device_id] = raw

            if not errors:
                self._pending_devices.pop(0)
                if self._pending_devices:
                    return await self.async_step_manual_ip()

                changes = dict(self._pending_changes)
                changes[CONF_MANUAL_IPS] = self._manual_ips
                return self._apply(
                    changes,
                    self._pending_options,
                    mode_changed=self._mode_changed,
                )

        return self.async_show_form(
            step_id="manual_ip",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        ATTR_IP_ADDRESS,
                        description={
                            "suggested_value": self._manual_ips.get(device_id)
                        },
                    ): str
                }
            ),
            description_placeholders={"device": device_id},
            errors=errors,
        )

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the connection type and local refresh interval."""
        errors: dict[str, str] = {}
        current_data = self._config_entry.data
        current_mode = _infer_connection_type(current_data)
        current_options = self._config_entry.options or {}
        device_ids = _known_device_ids(self._config_entry)
        current_manual = self._config_entry.data.get(CONF_MANUAL_IPS)
        current_manual = current_manual if isinstance(current_manual, dict) else {}
        current_interval = int(
            current_options.get(CONF_LOCAL_UPDATE_INTERVAL, DEFAULT_LOCAL_INTERVAL)
        )

        if user_input is not None:
            new_mode = user_input.get("connection_type", current_mode)
            interval_raw = user_input.get(CONF_LOCAL_UPDATE_INTERVAL, current_interval)
            try:
                interval = int(interval_raw)
            except (TypeError, ValueError):
                interval = current_interval
                errors[CONF_LOCAL_UPDATE_INTERVAL] = "invalid_interval"

            if not errors and not MIN_LOCAL_INTERVAL <= interval <= MAX_LOCAL_INTERVAL:
                errors[CONF_LOCAL_UPDATE_INTERVAL] = "invalid_interval"

            mode_changed = new_mode != current_mode

            if not errors:
                changes: dict[str, Any] = {CONF_CLOUD_ONLY: new_mode == "cloud_only"}

                new_options = dict(current_options)
                new_options[CONF_LOCAL_UPDATE_INTERVAL] = interval

                # An address override is only ever read by the LAN transport,
                # so the DESTINATION mode decides what the box means — not the
                # current one. That is what lets a 4G entry be switched to
                # Wi-Fi and given its address in a single pass, which matters
                # most when the cloud is down and cannot supply one. Switching
                # the other way leaves stored overrides alone: they cost
                # nothing while unused and are still there on the way back.
                is_lan = not changes[CONF_CLOUD_ONLY]
                set_manual = bool(user_input.get(CONF_SET_MANUAL_IPS))
                wants_manual = is_lan and set_manual

                if wants_manual and not device_ids:
                    errors[CONF_SET_MANUAL_IPS] = "no_known_devices"
                elif wants_manual:
                    # Nothing is persisted yet: forms are still to come, and
                    # abandoning the flow half-way must leave the entry exactly
                    # as it was.
                    self._pending_devices = list(device_ids)
                    self._manual_ips = dict(current_manual)
                    self._pending_changes = changes
                    self._pending_options = new_options
                    self._mode_changed = mode_changed
                    return await self.async_step_manual_ip()
                else:
                    # The box now mirrors what is stored, so clearing it is the
                    # gesture that drops every override and hands the addresses
                    # back to cloud discovery — on a Cloud only (4G) entry too,
                    # where the box is still shown and still says so.
                    #
                    # The single exception is the move TO Cloud only: there the
                    # box is about to become irrelevant, and a user tidying it
                    # up on the way out must not silently lose the addresses
                    # they will need the moment they come back to Wi-Fi — which
                    # is exactly when the cloud may be unable to supply them.
                    switching_to_cloud = mode_changed and not is_lan
                    if current_manual and not set_manual and not switching_to_cloud:
                        changes[CONF_MANUAL_IPS] = {}
                    return self._apply(changes, new_options, mode_changed=mode_changed)

        schema = vol.Schema(
            {
                vol.Required("connection_type", default=current_mode): SelectSelector(
                    SelectSelectorConfig(
                        options=["local", "cloud_only"],
                        translation_key="connection_type",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_LOCAL_UPDATE_INTERVAL,
                    default=current_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_LOCAL_INTERVAL, max=MAX_LOCAL_INTERVAL),
                ),
                # Ticked whenever overrides are stored, so the box reports the
                # entry's state instead of resetting to "off" on every visit.
                # Opting in leads to one form per charger, each pre-filled with
                # the address in force. The address fields cannot live here:
                # Home Assistant resolves field labels from static translation
                # keys, and a key built from the device id would surface in the
                # UI as the raw `manual_ip_<id>` string.
                vol.Optional(
                    CONF_SET_MANUAL_IPS,
                    default=bool(current_manual),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "manual_ips": _describe_overrides(current_manual)
            },
            errors=errors,
        )
