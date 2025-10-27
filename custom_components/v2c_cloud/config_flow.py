"""Config flow for the V2C Cloud integration."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client

from .const import CONF_API_KEY, CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .v2c_cloud import V2CAuthError, V2CClient, V2CRequestError

_LOGGER = logging.getLogger(__name__)


async def _validate_api_key(
    hass: HomeAssistant,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Ensure the provided API key works and return pairings."""
    session = aiohttp_client.async_get_clientsession(hass)
    client = V2CClient(session, api_key, base_url=base_url)
    return await client.async_get_pairings()


class V2CConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for V2C Cloud."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = user_input.get(CONF_BASE_URL) or DEFAULT_BASE_URL

            try:
                pairings = await _validate_api_key(self.hass, api_key, base_url)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface as unknown
                _LOGGER.exception("Unexpected error while validating API key")
                errors["base"] = "unknown"
            else:
                unique_suffix = hashlib.sha256(api_key.encode()).hexdigest()
                await self.async_set_unique_id(unique_suffix)
                self._abort_if_unique_id_configured()

                title = "V2C Cloud"
                if pairings:
                    first = pairings[0]
                    label = first.get("tag") or first.get("deviceId")
                    if label:
                        title = f"V2C Cloud - {label}"

                data = {CONF_API_KEY: api_key}
                if base_url != DEFAULT_BASE_URL:
                    data[CONF_BASE_URL] = base_url

                return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )

        if self.show_advanced_options:
            schema = schema.extend(
                {
                    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthentication when the API key expires."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            entry_data["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm reauthentication by asking for a new API key."""
        errors: dict[str, str] = {}

        if user_input is not None and self._reauth_entry:
            api_key = user_input[CONF_API_KEY].strip()
            base_url = (
                self._reauth_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
                if CONF_BASE_URL not in user_input
                else user_input[CONF_BASE_URL]
            )

            try:
                await _validate_api_key(self.hass, api_key, base_url)
            except V2CAuthError:
                errors["base"] = "invalid_api_key"
            except V2CRequestError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while validating API key")
                errors["base"] = "unknown"
            else:
                new_data = dict(self._reauth_entry.data)
                new_data[CONF_API_KEY] = api_key
                if base_url != DEFAULT_BASE_URL:
                    new_data[CONF_BASE_URL] = base_url
                else:
                    new_data.pop(CONF_BASE_URL, None)

                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data=new_data,
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                )
                return self.async_abort(reason="reauth_successful")

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
