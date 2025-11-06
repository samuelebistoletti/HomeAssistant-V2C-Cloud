"""Asynchronous client for the V2C Cloud public API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import async_timeout
from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://v2c.cloud/kong/v2c_service"
DEFAULT_TIMEOUT = 15
PAIRINGS_CACHE_TTL = 3600  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
RFID_REFRESH_INTERVAL = 6 * 3600  # seconds
RFID_RETRY_INTERVAL = 30 * 60  # seconds
VERSION_REFRESH_INTERVAL = 12 * 3600  # seconds
VERSION_RETRY_INTERVAL = 60 * 60  # seconds


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


def _normalize_bool(value: Any) -> bool | None:
    """Coerce various payload values to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "online"}:
            return True
        if lowered in {"false", "0", "no", "off", "offline"}:
            return False
    return None


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


def _extract_static_ip(*values: Any) -> str | None:
    """Extract an IPv4 address from nested payloads."""

    def _parse(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("static_ip", "ip", "address"):
                if key in value:
                    ip_value = _parse(value[key])
                    if ip_value:
                        return ip_value
            return None
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    return None
            else:
                return _parse(parsed)
        return None

    for value in values:
        ip_value = _parse(value)
        if ip_value:
            return ip_value
    return None


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
        self._last_rate_limit: dict[str, Any] | None = None

    @property
    def base_url(self) -> str:
        """Return the base URL used by the client."""
        return self._base_url

    @property
    def last_rate_limit(self) -> dict[str, Any] | None:
        """Return the last RateLimit header snapshot."""
        return self._last_rate_limit

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

                        rate_limit: dict[str, Any] | None = None
                        if response.headers:
                            rate_limit = {}
                            limit_header = response.headers.get("RateLimit-Limit")
                            remaining_header = response.headers.get("RateLimit-Remaining")
                            reset_header = response.headers.get("RateLimit-Reset")
                            try:
                                rate_limit["limit"] = int(limit_header) if limit_header is not None else None
                            except (TypeError, ValueError):
                                rate_limit["limit"] = None
                            try:
                                rate_limit["remaining"] = int(remaining_header) if remaining_header is not None else None
                            except (TypeError, ValueError):
                                rate_limit["remaining"] = None
                            try:
                                rate_limit["reset"] = int(reset_header) if reset_header is not None else None
                            except (TypeError, ValueError):
                                rate_limit["reset"] = None
                            if any(value is not None for value in rate_limit.values()):
                                self._last_rate_limit = rate_limit

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
        return await self._device_command(
            "/device/currentstatecharge",
            device_id,
        )

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

    async def async_add_rfid_card(
        self,
        device_id: str,
        code: str,
        tag: str,
    ) -> Any:
        """Register an RFID card by providing its UID and friendly name."""
        params = {"code": code, "tag": tag}
        return await self._device_command(
            "/device/rfid/tag",
            device_id,
            extra_params=params,
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
            method="PUT",
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

    async def async_set_charge_stop_energy(self, device_id: str, kwh: float) -> Any:
        """Configure automatic stop once a given energy (kWh) has been delivered."""
        value = format(float(kwh), "g")
        return await self._device_command(
            "/device/charger_until_energy",
            device_id,
            extra_params={"value": value},
        )

    async def async_set_charge_stop_minutes(self, device_id: str, minutes: int) -> Any:
        """Configure automatic stop after a given number of minutes."""
        return await self._device_command(
            "/device/charger_until_minutes",
            device_id,
            extra_params={"value": str(int(minutes))},
        )

    async def async_start_charge_kwh(self, device_id: str, kwh: float) -> Any:
        """Start a charge programmed to stop after delivering a target kWh."""
        value = format(float(kwh), "g")
        return await self._device_command(
            "/device/startchargekw",
            device_id,
            extra_params={"kw": value},
        )

    async def async_start_charge_minutes(self, device_id: str, minutes: int) -> Any:
        """Start a charge programmed to stop after a target duration."""
        return await self._device_command(
            "/device/startchargeminutes",
            device_id,
            extra_params={"minutes": str(int(minutes))},
        )

    async def async_reboot(self, device_id: str) -> Any:
        """Reboot the charger."""
        return await self._device_command("/device/reboot", device_id)

    async def async_trigger_update(self, device_id: str) -> Any:
        """Trigger firmware update."""
        return await self._device_command("/device/update", device_id)

    async def async_set_dynamic(self, device_id: str, enabled: bool) -> Any:
        """Enable or disable dynamic mode."""
        value = "1" if enabled else "0"
        return await self._device_command(
            "/device/dynamic",
            device_id,
            extra_params={"value": value},
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

    async def async_set_ocpp_enabled(self, device_id: str, enabled: bool) -> Any:
        """Toggle the OCPP functionality."""
        value = "1" if enabled else "0"
        return await self._device_command(
            "/device/ocpp",
            device_id,
            extra_params={"value": value},
            device_param="id",
        )

    async def async_set_ocpp_id(self, device_id: str, ocpp_id: str) -> Any:
        """Configure the charge point identifier used for OCPP."""
        return await self._device_command(
            "/device/ocpp_id",
            device_id,
            extra_params={"value": ocpp_id},
            device_param="id",
        )

    async def async_set_ocpp_address(self, device_id: str, url: str) -> Any:
        """Configure the remote OCPP server URL."""
        return await self._device_command(
            "/device/ocpp_addr",
            device_id,
            extra_params={"value": url},
            device_param="id",
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

    async def async_set_max_power(self, device_id: str, watts: int) -> Any:
        """Set maximum power delivery."""
        return await self._device_command(
            "/device/maxpower",
            device_id,
            extra_params={"value": str(int(watts))},
        )

    async def async_set_inverter_ip(self, device_id: str, address: str) -> Any:
        """Configure the IP address of the linked inverter."""
        return await self._device_command(
            "/device/inverter_ip",
            device_id,
            extra_params={"value": address},
            device_param="id",
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

    async def async_get_wifi_list(self, device_id: str) -> Any:
        """Trigger a Wi-Fi scan and return visible networks."""
        return await self._request(
            "GET",
            "/device/wifilist",
            params={"id": device_id},
        )

    async def async_program_timer(
        self,
        device_id: str,
        timer_id: int,
        *,
        time_start: str,
        time_end: str,
        active: bool,
    ) -> Any:
        """Configure a timer slot on the charger."""
        timer_value = str(timer_id)
        params = {"timerId": timer_value, "timer id": timer_value}
        body = {
            "start_time": time_start,
            "end_time": time_end,
            "timeStart": time_start,
            "timeEnd": time_end,
            "active": active,
        }
        return await self._device_command(
            "/device/timer",
            device_id,
            extra_params=params,
            json_body=body,
        )

    async def async_save_personal_power_profile(
        self,
        device_id: str,
        name: str,
        update_at: str,
        profile: dict[str, Any],
    ) -> Any:
        """Create a personalised power profile (v2)."""
        params = {"name": name, "updateAt": update_at}
        return await self._device_command(
            "/device/savepersonalicepower/v2",
            device_id,
            extra_params=params,
            json_body=profile,
        )

    async def async_update_personal_power_profile(
        self,
        device_id: str,
        name: str,
        update_at: str,
        profile: dict[str, Any],
    ) -> Any:
        """Update a personalised power profile (v2)."""
        params = {"name": name, "updateAt": update_at}
        return await self._device_command(
            "/device/personalicepower/v2",
            device_id,
            extra_params=params,
            json_body=profile,
            device_param="id",
        )

    async def async_get_personal_power_profile(
        self,
        device_id: str,
        update_at: str,
    ) -> Any:
        """Retrieve a specific personalised power profile."""
        params = {"deviceId": device_id, "updateAt": update_at}
        return await self._request(
            "GET",
            "/device/personalicepower/v2",
            params=params,
        )

    async def async_delete_personal_power_profile(
        self,
        device_id: str,
        name: str,
        update_at: str,
    ) -> Any:
        """Delete a personalised power profile."""
        params = {"deviceId": device_id, "name": name, "updateAt": update_at}
        return await self._request(
            "DELETE",
            "/device/personalicepower/v2",
            params=params,
        )

    async def async_list_personal_power_profiles(self, device_id: str) -> Any:
        """List all personalised power profiles for a device."""
        return await self._request(
            "GET",
            "/device/personalicepower/all",
            params={"deviceId": device_id},
        )

    async def _device_command(
        self,
        path: str,
        device_id: str,
        *,
        extra_params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        method: str = "POST",
        device_param: str = "deviceId",
    ) -> Any:
        """Helper for POST commands that target a specific device."""
        params = {device_param: device_id}
        if extra_params:
            params.update(extra_params)
        return await self._request(
            method,
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
    now = time.time()

    for pairing in pairings:
        device_id = pairing.get("deviceId")
        if not device_id:
            continue

        state = V2CDeviceState(device_id=device_id, pairing=pairing)
        previous_state = previous_devices.get(device_id, {}) if previous_devices else {}
        previous_additional = previous_state.get("additional", {})
        if isinstance(previous_additional, dict):
            state.additional.update({k: v for k, v in previous_additional.items() if k != "reported_lower"})

        try:
            reported = await client.async_get_reported(device_id)
        except V2CRateLimitError:
            raise
        except V2CError as err:
            _LOGGER.warning("Failed to fetch reported state for %s: %s", device_id, err)
            reported = None

        state.reported_raw = reported
        reported_dict: dict[str, Any] | None = None
        if isinstance(reported, dict):
            reported_dict = reported
        elif isinstance(reported, str):
            try:
                parsed = json.loads(reported)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                reported_dict = parsed
            else:
                state.reported_raw = parsed if parsed is not None else reported
        elif reported is not None and isinstance(reported, Iterable):
            # Some payloads may be list-like; keep as raw
            state.reported_raw = reported

        if reported_dict is not None:
            state.reported = reported_dict
            lowered = {str(key).lower(): value for key, value in reported_dict.items()}
            state.additional["reported_lower"] = lowered
            state.additional["reported_timestamp"] = now

            static_ip = _extract_static_ip(
                reported_dict.get("wifi_static"),
                reported_dict.get("wifi_info"),
                reported_dict.get("huawei_ip"),
                reported_dict.get("ip"),
            )
            if not static_ip and isinstance(previous_additional, dict):
                static_ip = previous_additional.get("static_ip")
            if static_ip:
                state.additional["static_ip"] = static_ip
        else:
            state.additional.pop("reported_lower", None)
            if isinstance(previous_state.get("reported"), dict):
                state.reported = previous_state.get("reported")
                lowered_prev = previous_state.get("additional", {}).get("reported_lower")
                if isinstance(lowered_prev, dict):
                    state.additional["reported_lower"] = lowered_prev

        connected_value: Any | None = None
        lowered = state.additional.get("reported_lower")
        if isinstance(lowered, dict):
            for key in ("connected", "isconnected", "online", "is_online", "statusconnection"):
                if key in lowered:
                    connected_value = lowered[key]
                    break
        if connected_value is None:
            connected_value = previous_state.get("connected")
        state.connected = _normalize_bool(connected_value)

        if state.reported is not None:
            state.current_state = state.reported
        elif previous_state.get("current_state") is not None:
            state.current_state = previous_state.get("current_state")

        previous_cards = previous_state.get("rfid_cards")
        next_rfid_refresh = state.additional.get("_rfid_next_refresh", 0.0)
        refresh_rfid = previous_cards is None or now >= float(next_rfid_refresh or 0)
        if refresh_rfid:
            try:
                rfid_cards = await client.async_get_rfid_cards(device_id)
            except V2CRateLimitError:
                raise
            except V2CError as err:
                _LOGGER.debug("Failed to fetch RFID cards for %s: %s", device_id, err)
                rfid_cards = None
            else:
                if isinstance(rfid_cards, list):
                    state.rfid_cards = rfid_cards
                    state.additional["_rfid_last_success"] = now
                    state.additional["_rfid_next_refresh"] = now + RFID_REFRESH_INTERVAL
                elif rfid_cards is not None:
                    state.additional["rfid_cards_raw"] = rfid_cards
                    state.additional["_rfid_next_refresh"] = now + RFID_RETRY_INTERVAL
                else:
                    state.additional["_rfid_next_refresh"] = now + RFID_RETRY_INTERVAL
                    state.rfid_cards = None
            if state.rfid_cards is None and previous_cards is not None:
                state.rfid_cards = previous_cards
                state.additional["_rfid_next_refresh"] = now + RFID_RETRY_INTERVAL
        else:
            state.rfid_cards = previous_cards

        previous_version = previous_state.get("version")
        version_info_prev = previous_state.get("additional", {}).get("version_info")
        next_version_refresh = state.additional.get("_version_next_refresh", 0.0)
        refresh_version = previous_version is None or now >= float(next_version_refresh or 0)
        if refresh_version:
            try:
                version_response = await client.async_get_version(device_id)
            except V2CRateLimitError:
                raise
            except V2CError as err:
                _LOGGER.debug("Failed to fetch version for %s: %s", device_id, err)
                version_response = None
            version_info: dict[str, Any] | None = None
            if isinstance(version_response, dict):
                version_info = version_response
            elif isinstance(version_response, str):
                try:
                    parsed_version = json.loads(version_response)
                except json.JSONDecodeError:
                    parsed_version = None
                if isinstance(parsed_version, dict):
                    version_info = parsed_version
                elif version_response:
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
            elif previous_version is not None:
                state.version = previous_version
                if isinstance(version_info_prev, dict):
                    state.additional["version_info"] = version_info_prev

            state.additional["_version_next_refresh"] = now + (
                VERSION_REFRESH_INTERVAL if state.version is not None else VERSION_RETRY_INTERVAL
            )
        else:
            state.version = previous_version
            if isinstance(version_info_prev, dict):
                state.additional["version_info"] = version_info_prev
            state.additional["_version_next_refresh"] = next_version_refresh

        results[device_id] = state.as_dict()

    return results
