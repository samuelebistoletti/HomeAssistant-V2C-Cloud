"""Asynchronous client for the V2C Cloud public API."""

from __future__ import annotations

import json
import logging
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import async_timeout
from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://v2c.cloud/kong/v2c_service"
DEFAULT_TIMEOUT = 15
PAIRINGS_CACHE_TTL = 300  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


class V2CError(Exception):
    """Base exception for V2C client errors."""


class V2CAuthError(V2CError):
    """Raised when authentication fails (HTTP 401)."""


class V2CRequestError(V2CError):
    """Raised when the V2C API responds with an unexpected error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class V2CRateLimitError(V2CRequestError):
    """Raised when the V2C API responds with HTTP 429."""


def _coerce_scalar(text: str) -> Any:
    """Try to interpret a textual response as JSON, number or boolean."""
    stripped = text.strip()
    if not stripped:
        return None

    # Some endpoints reply with json encoded as text/plain.
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return lowered == "true"

    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


@dataclass(slots=True)
class V2CDeviceState:
    """State snapshot for a single V2C device."""

    device_id: str
    pairing: dict[str, Any]
    connected: bool | None = None
    current_state: Any | None = None
    reported_raw: Any | None = None
    reported: dict[str, Any] | None = None
    rfid_cards: list[dict[str, Any]] | None = None
    version: str | None = None
    mac_address: str | None = None
    additional: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation for coordinator storage."""
        return {
            "device_id": self.device_id,
            "pairing": self.pairing,
            "connected": self.connected,
            "current_state": self.current_state,
            "reported_raw": self.reported_raw,
            "reported": self.reported,
            "rfid_cards": self.rfid_cards,
            "version": self.version,
            "mac_address": self.mac_address,
            "additional": self.additional,
        }


class V2CClient:
    """Simple asynchronous client for the V2C Cloud API."""

    def __init__(
        self,
        session: ClientSession,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._pairings_cache: list[dict[str, Any]] | None = None
        self._pairings_cache_expiry: float = 0.0

    @property
    def base_url(self) -> str:
        """Return the base URL used by the client."""
        return self._base_url

    def preload_pairings(self, pairings: list[dict[str, Any]] | None, ttl: float | None = None) -> None:
        """Preload cached pairings to avoid initial rate-limit failures."""
        if pairings is None:
            return
        self._pairings_cache = pairings
        expiry = ttl if ttl is not None else PAIRINGS_CACHE_TTL
        self._pairings_cache_expiry = time.monotonic() + expiry

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        """Perform an HTTP request and normalise the response."""
        url = f"{self._base_url}{path}"
        headers = {
            "apikey": self._api_key,
        }

        _LOGGER.debug(
            "V2C request %s %s params=%s body=%s", method, url, params, json_body
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                async with async_timeout.timeout(self._timeout):
                    async with self._session.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    ) as response:
                        status = response.status
                        content_type = response.headers.get("Content-Type", "")

                        if status == 401:
                            text = await response.text()
                            raise V2CAuthError(f"V2C authentication failed: {text}")

                        if status == 429:
                            text = await response.text()
                            retry_after = response.headers.get("Retry-After")
                            if attempt < MAX_RETRIES:
                                try:
                                    delay = float(retry_after) if retry_after else None
                                except (TypeError, ValueError):
                                    delay = None
                                if delay is None:
                                    delay = RETRY_BACKOFF * attempt
                                _LOGGER.warning(
                                    "Rate limited by V2C Cloud (attempt %s/%s), retrying in %.1f s",
                                    attempt,
                                    MAX_RETRIES,
                                    delay,
                                )
                                await asyncio.sleep(delay)
                                continue
                            raise V2CRateLimitError(
                                f"V2C API rate limit reached: {text or 'unknown error'}",
                                status=status,
                            )

                        if status >= 400:
                            text = await response.text()
                            raise V2CRequestError(
                                f"V2C API error {status}: {text or 'unknown error'}",
                                status=status,
                            )

                        if status == 204:
                            return None

                        if "application/json" in content_type:
                            return await response.json(content_type=None)

                        text = await response.text()
                        return _coerce_scalar(text)
            except asyncio.TimeoutError:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Timeout contacting V2C Cloud (attempt %s/%s), retrying",
                        attempt,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(RETRY_BACKOFF * attempt)
                    continue
                raise V2CRequestError("Request to V2C API timed out") from None
            except ClientError as err:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "HTTP error contacting V2C Cloud (attempt %s/%s): %s. Retrying.",
                        attempt,
                        MAX_RETRIES,
                        err,
                    )
                    await asyncio.sleep(RETRY_BACKOFF * attempt)
                    continue
                raise V2CRequestError(f"HTTP error while calling V2C API: {err}") from err

    async def async_get_pairings(self) -> list[dict[str, Any]]:
        """Return the pairings linked to the current account."""
        now = time.monotonic()
        if (
            self._pairings_cache is not None
            and now < self._pairings_cache_expiry
        ):
            return self._pairings_cache

        try:
            data = await self._request("GET", "/pairings/me")
        except V2CRateLimitError as err:
            if self._pairings_cache is not None:
                _LOGGER.warning("V2C rate limit reached when fetching pairings; using cached data")
                return self._pairings_cache
            raise err

        if isinstance(data, list):
            self._pairings_cache = data
            self._pairings_cache_expiry = now + PAIRINGS_CACHE_TTL
            return data
        if data is None:
            self._pairings_cache = []
            self._pairings_cache_expiry = now + PAIRINGS_CACHE_TTL
            return []
        _LOGGER.debug("Unexpected pairings payload type: %s", type(data))
        return []

    async def async_get_global_statistics(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return aggregated statistics across all devices."""
        params: dict[str, Any] = {}
        if start:
            params["endChargeDateStart"] = start
        if end:
            params["endChargeDateEnd"] = end
        data = await self._request(
            "GET",
            "/stadistic/global/me",
            params=params if params else None,
        )
        if isinstance(data, list):
            return data
        return []

    async def async_get_device_statistics(
        self,
        device_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return charge statistics for a single device."""
        params: dict[str, Any] = {"deviceId": device_id}
        if start:
            params["chargeDateStart"] = start
        if end:
            params["chargeDateEnd"] = end
        data = await self._request(
            "GET",
            "/stadistic/device",
            params=params,
        )
        if isinstance(data, list):
            return data
        return []

    async def async_get_version(self, device_id: str) -> Any:
        """Return the firmware version for the given device."""
        return await self._request(
            "GET",
            "/version",
            params={"deviceId": device_id},
        )

    async def async_get_connected(self, device_id: str) -> Any:
        """Return whether the device is connected."""
        return await self._request(
            "GET",
            "/device/connected",
            params={"deviceId": device_id},
        )

    async def async_get_reported(self, device_id: str) -> Any:
        """Return the reported state of the device."""
        return await self._request(
            "GET",
            "/device/reported",
            params={"deviceId": device_id},
        )

    async def async_get_current_state_charge(self, device_id: str) -> Any:
        """Return the current charging state of the device."""
        return await self._device_command("/device/currentstatecharge", device_id)

    async def async_get_rfid_cards(self, device_id: str) -> Any:
        """Return registered RFID cards for the device."""
        return await self._request(
            "GET",
            "/device/rfid",
            params={"deviceId": device_id},
        )

    async def async_set_rfid_mode(self, device_id: str, enabled: bool) -> Any:
        """Enable or disable the RFID reader."""
        value = "1" if enabled else "0"
        return await self._device_command(
            "/device/set_rfid",
            device_id,
            extra_params={"value": value},
        )

    async def async_register_rfid_card(
        self,
        device_id: str,
        tag: str,
    ) -> Any:
        """Put device in registration mode for a new RFID tag."""
        return await self._device_command(
            "/device/rfid",
            device_id,
            extra_params={"tag": tag},
        )

    async def async_update_rfid_tag(
        self,
        device_id: str,
        code: str,
        tag: str,
    ) -> Any:
        """Update the description for an existing RFID card."""
        params = {"code": code, "tag": tag}
        return await self._device_command(
            "/device/rfid/tag",
            device_id,
            extra_params=params,
        )

    async def async_delete_rfid_card(
        self,
        device_id: str,
        code: str,
    ) -> Any:
        """Delete an RFID card from the device."""
        params = {"code": code}
        return await self._request(
            "DELETE",
            "/device/rfid",
            params={"deviceId": device_id, **params},
        )

    async def async_start_charge(self, device_id: str) -> Any:
        """Start charging."""
        return await self._device_command("/device/startcharge", device_id)

    async def async_pause_charge(self, device_id: str) -> Any:
        """Pause charging."""
        return await self._device_command("/device/pausecharge", device_id)

    async def async_reboot(self, device_id: str) -> Any:
        """Reboot the charger."""
        return await self._device_command("/device/reboot", device_id)

    async def async_trigger_update(self, device_id: str) -> Any:
        """Trigger firmware update."""
        return await self._device_command("/device/update", device_id)

    async def async_get_mac(self, device_id: str) -> Any:
        """Retrieve device MAC address."""
        return await self._device_command("/device/mac", device_id)

    async def async_set_dynamic(self, device_id: str, enabled: bool) -> Any:
        """Enable or disable dynamic mode."""
        value = "1" if enabled else "0"
        return await self._device_command(
            "/device/dynamic",
            device_id,
            extra_params={"value": value},
        )

    async def async_set_fv_mode(self, device_id: str, mode: int) -> Any:
        """Set the FV mode of the charger."""
        return await self._device_command(
            "/device/chargefvmode",
            device_id,
            extra_params={"value": str(mode)},
        )

    async def async_set_installation_type(self, device_id: str, value: int) -> Any:
        """Set the installation type."""
        return await self._device_command(
            "/device/inst_type",
            device_id,
            extra_params={"value": str(value)},
        )

    async def async_set_slave_type(self, device_id: str, value: int) -> Any:
        """Set the slave type."""
        return await self._device_command(
            "/device/slave_type",
            device_id,
            extra_params={"value": str(value)},
        )

    async def async_set_language(self, device_id: str, value: int) -> Any:
        """Set the charger language."""
        return await self._device_command(
            "/device/language",
            device_id,
            extra_params={"value": str(value)},
        )

    async def async_lock(self, device_id: str, locked: bool) -> Any:
        """Lock or unlock the charge point."""
        value = "1" if locked else "0"
        return await self._device_command(
            "/device/locked",
            device_id,
            extra_params={"value": value},
        )

    async def async_set_logo_led(self, device_id: str, enabled: bool) -> Any:
        """Turn the logo LED on or off."""
        value = "1" if enabled else "0"
        return await self._device_command(
            "/device/logo_led",
            device_id,
            extra_params={"value": value},
        )

    async def async_set_min_car_intensity(self, device_id: str, amps: int) -> Any:
        """Set minimum car intensity."""
        return await self._device_command(
            "/device/min_car_int",
            device_id,
            extra_params={"value": str(amps)},
        )

    async def async_set_max_car_intensity(self, device_id: str, amps: int) -> Any:
        """Set maximum car intensity."""
        return await self._device_command(
            "/device/max_car_int",
            device_id,
            extra_params={"value": str(amps)},
        )

    async def async_set_intensity(self, device_id: str, amps: int) -> Any:
        """Set current charging intensity."""
        return await self._device_command(
            "/device/intensity",
            device_id,
            extra_params={"value": str(amps)},
        )

    async def async_set_max_power(self, device_id: str, kw: float) -> Any:
        """Set maximum power delivery."""
        return await self._device_command(
            "/device/maxpower",
            device_id,
            extra_params={"value": str(kw)},
        )

    async def async_set_wifi(
        self,
        device_id: str,
        ssid: str,
        password: str,
    ) -> Any:
        """Update Wi-Fi credentials for the device."""
        params = {"ssid": ssid, "password": password}
        return await self._device_command(
            "/device/wifi",
            device_id,
            extra_params=params,
        )

    async def async_program_timer(
        self,
        device_id: str,
        timer_id: int,
        *,
        days_of_week: str,
        time_start: str,
        time_end: str,
    ) -> Any:
        """Configure a timer slot on the charger."""
        timer_value = str(timer_id)
        params = {"timerId": timer_value, "timer id": timer_value}
        body = {
            "daysOfWeek": days_of_week,
            "timeStart": time_start,
            "timeEnd": time_end,
        }
        return await self._device_command(
            "/device/timer",
            device_id,
            extra_params=params,
            json_body=body,
        )

    async def _device_command(
        self,
        path: str,
        device_id: str,
        *,
        extra_params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        """Helper for POST commands that target a specific device."""
        params = {"deviceId": device_id}
        if extra_params:
            params.update(extra_params)
        return await self._request(
            "POST",
            path,
            params=params,
            json_body=json_body,
        )


async def async_gather_devices_state(
    client: V2CClient,
    pairings: Iterable[dict[str, Any]],
    previous_devices: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch the current state for each paired device."""
    results: dict[str, dict[str, Any]] = {}

    for pairing in pairings:
        device_id = pairing.get("deviceId")
        if not device_id:
            continue

        state = V2CDeviceState(device_id=device_id, pairing=pairing)
        previous_state = (
            previous_devices.get(device_id, {}) if previous_devices else {}
        )

        try:
            connected = await client.async_get_connected(device_id)
            state.connected = bool(connected) if connected is not None else None
        except V2CRateLimitError:
            raise
        except V2CError as err:
            _LOGGER.warning("Failed to fetch connection status for %s: %s", device_id, err)

        try:
            reported = await client.async_get_reported(device_id)
            state.reported_raw = reported
            if isinstance(reported, dict):
                state.reported = reported
                state.additional["reported_lower"] = {
                    str(key).lower(): value for key, value in reported.items()
                }
            elif isinstance(reported, str):
                try:
                    parsed = json.loads(reported)
                    if isinstance(parsed, dict):
                        state.reported = parsed
                        state.additional["reported_lower"] = {
                            str(key).lower(): value for key, value in parsed.items()
                        }
                    else:
                        state.reported_raw = parsed
                except json.JSONDecodeError:
                    pass
        except V2CRateLimitError:
            raise
        except V2CError as err:
            _LOGGER.warning("Failed to fetch reported state for %s: %s", device_id, err)

        try:
            current_state = await client.async_get_current_state_charge(device_id)
            state.current_state = current_state
        except V2CRateLimitError:
            raise
        except V2CError as err:
            _LOGGER.debug(
                "Failed to fetch current state charge for %s: %s", device_id, err
            )

        try:
            rfid_cards = await client.async_get_rfid_cards(device_id)
            if isinstance(rfid_cards, list):
                state.rfid_cards = rfid_cards
            elif rfid_cards is not None:
                state.additional["rfid_cards_raw"] = rfid_cards
        except V2CRateLimitError:
            raise
        except V2CError as err:
            _LOGGER.debug("Failed to fetch RFID cards for %s: %s", device_id, err)

        if previous_state.get("version") is not None:
            state.version = previous_state.get("version")
            version_info_prev = (
                previous_state.get("additional", {}).get("version_info")
            )
            if isinstance(version_info_prev, dict):
                state.additional["version_info"] = version_info_prev
        else:
            try:
                version_response = await client.async_get_version(device_id)
                version_info: dict[str, Any] | None = None

                if isinstance(version_response, dict):
                    version_info = version_response
                elif isinstance(version_response, str):
                    try:
                        parsed_version = json.loads(version_response)
                        if isinstance(parsed_version, dict):
                            version_info = parsed_version
                        else:
                            state.version = str(version_response)
                    except json.JSONDecodeError:
                        state.version = version_response
                elif version_response is not None:
                    state.version = str(version_response)

                if version_info:
                    state.version = (
                        version_info.get("versionId")
                        or version_info.get("version")
                        or version_info.get("version_id")
                    )
                    state.additional["version_info"] = version_info
            except V2CRateLimitError:
                raise
            except V2CError as err:
                _LOGGER.debug("Failed to fetch version for %s: %s", device_id, err)

        if previous_state.get("mac_address") is not None:
            state.mac_address = previous_state.get("mac_address")
        else:
            try:
                mac_address = await client.async_get_mac(device_id)
                if mac_address:
                    if isinstance(mac_address, dict) and "mac" in mac_address:
                        state.mac_address = str(mac_address["mac"])
                    else:
                        state.mac_address = str(mac_address)
            except V2CRateLimitError:
                raise
            except V2CError as err:
                _LOGGER.debug("Failed to fetch MAC address for %s: %s", device_id, err)

        results[device_id] = state.as_dict()

    return results
