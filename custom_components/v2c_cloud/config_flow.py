"""Config flow for the V2C Cloud integration."""

from __future__ import annotations

import hashlib
import ipaddress
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

from .const import CONF_API_KEY, DOMAIN
from .v2c_cloud import V2CAuthError, V2CClient, V2CRequestError

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
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None, "cannot_connect_local"

    if not addr.is_private or addr.is_loopback or addr.is_link_local:
        return None, "cannot_connect_local"

    session = aiohttp_client.async_get_clientsession(hass)
    url = f"http://{ip}/RealTimeData"
    try:
        async with async_timeout.timeout(_LOCAL_PROBE_TIMEOUT), session.get(url) as response:
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

    VERSION = 1

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
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                pairings = await _validate_api_key(self.hass, api_key)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                # Cloud unreachable — save the key and ask for a fallback IP
                self._api_key = api_key
                return await self.async_step_fallback_ip()
            except Exception:
                _LOGGER.exception("Unexpected error while validating API key")
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

            if connection == "cloud_only":
                # 4G/cloud-only: extract device ID from pairings
                device_id = ""
                if self._pairings:
                    device_id = self._pairings[0].get("deviceId", "")
                return self.async_create_entry(
                    title="V2C Cloud",
                    data={
                        CONF_API_KEY: self._api_key,
                        "initial_pairings": self._pairings,
                        "fallback_ip": "",
                        "fallback_device_id": device_id,
                    },
                )

            # Local Wi-Fi: no fallback_ip key → standard local behavior
            return self.async_create_entry(
                title="V2C Cloud",
                data={
                    CONF_API_KEY: self._api_key,
                    "initial_pairings": self._pairings,
                },
            )

        schema = vol.Schema(
            {
                vol.Required("connection_type", default="local"): vol.In(
                    {
                        "local": "Local (Wi-Fi)",
                        "cloud_only": "Cloud only (4G)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="connection_type",
            data_schema=schema,
        )

    async def async_step_fallback_ip(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Ask for a fallback local IP when the cloud is unreachable."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input["fallback_ip"].strip()
            device_id, error_key = await _probe_local_api(self.hass, ip)
            if error_key:
                errors["base"] = error_key
            else:
                unique_suffix = hashlib.pbkdf2_hmac(
                    "sha256",
                    self._api_key.encode(),
                    b"v2c_cloud_unique_id",
                    200_000,
                ).hex()
                await self.async_set_unique_id(unique_suffix)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="V2C Cloud",
                    data={
                        CONF_API_KEY: self._api_key,
                        "fallback_ip": ip,
                        "fallback_device_id": device_id,
                    },
                )

        schema = vol.Schema({vol.Required("fallback_ip"): str})
        return self.async_show_form(
            step_id="fallback_ip",
            data_schema=schema,
            errors=errors,
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
            except Exception:
                _LOGGER.exception("Unexpected error while validating API key")
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
            except Exception:
                _LOGGER.exception("Unexpected error while validating API key")
                errors["base"] = "unknown"

            if not errors:
                reauth_entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    reason="reauth_successful",
                    data_updates={
                        CONF_API_KEY: api_key,
                        "initial_pairings": pairings,
                    },
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
    """Allow post-setup configuration of the fallback local IP."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the fallback IP option."""
        errors: dict[str, str] = {}
        current_ip = self._config_entry.data.get("fallback_ip", "")

        if user_input is not None:
            ip = user_input.get("fallback_ip", "").strip()
            if ip:
                device_id, error_key = await _probe_local_api(self.hass, ip)
                if error_key:
                    errors["base"] = error_key
                else:
                    new_data = dict(self._config_entry.data)
                    new_data["fallback_ip"] = ip
                    new_data["fallback_device_id"] = device_id
                    self.hass.config_entries.async_update_entry(
                        self._config_entry, data=new_data
                    )
                    return self.async_create_entry(title="", data={})
            else:
                # Empty field → remove fallback
                new_data = dict(self._config_entry.data)
                new_data.pop("fallback_ip", None)
                new_data.pop("fallback_device_id", None)
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional("fallback_ip", default=current_ip): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
