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
    CONF_API_KEY,
    CONF_LOCAL_UPDATE_INTERVAL,
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
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """
        Handle the initial step.

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
                    "cached_pairings": cached_pairings,
                    "cloud_only": connection == "cloud_only",
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

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the connection type and local refresh interval."""
        errors: dict[str, str] = {}
        current_data = self._config_entry.data
        current_mode = _infer_connection_type(current_data)
        current_options = self._config_entry.options or {}
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

            new_data = dict(current_data)
            mode_changed = new_mode != current_mode

            if not errors:
                new_data["cloud_only"] = new_mode == "cloud_only"

                new_options = dict(current_options)
                new_options[CONF_LOCAL_UPDATE_INTERVAL] = interval

                # Persist entry.data via async_update_entry; entry.options is
                # written by the async_create_entry return below — passing
                # ``data=new_options`` to async_create_entry is the canonical
                # HA pattern to store options flow output. Passing ``data={}``
                # here would OVERWRITE the options the user just set.
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )

                if mode_changed:
                    # Switching modes restructures the coordinator topology
                    # (cloud-only vs LAN polling). Schedule a reload so the
                    # change takes effect immediately.
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(
                            self._config_entry.entry_id
                        )
                    )

                return self.async_create_entry(title="", data=new_options)

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
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
