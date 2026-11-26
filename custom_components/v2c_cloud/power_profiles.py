"""Cloud profile snapshots, lossless editing and confirmed lifecycle operations."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from contextlib import suppress
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .entity import build_device_info
from .v2c_cloud import V2CAuthError, V2CRequestError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import V2CEntryRuntimeData


class InvalidPowerProfilesError(ValueError):
    """The public response cannot be safely associated with a charger."""


def read_profile_list(payload: Any, device_id: str) -> list[dict[str, Any]]:
    """Keep complete records, without interpreting timestamps or schedule units."""
    if not isinstance(payload, list):
        raise InvalidPowerProfilesError("Expected a profile list")
    for profile in payload:
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("name"), str)
            or not profile["name"].strip()
            or profile.get("deviceId") != device_id
        ):
            raise InvalidPowerProfilesError("Invalid profile identity")
    return deepcopy(payload)


class PowerProfileConflictError(InvalidPowerProfilesError):
    """The remote profile changed while the user was editing it."""


class PowerProfileSaveUnconfirmedError(InvalidPowerProfilesError):
    """A write may have occurred, but its complete outcome is not confirmed."""


def _schedules(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse both observed schedule envelopes without dropping extension fields."""
    schedules = []
    try:
        for group, field in enumerate(("powerweekday", "powerweekend")):
            if not isinstance(profile[field], str):
                raise InvalidPowerProfilesError("Expected a schedule JSON string")
            schedule = json.loads(profile[field])
            if (
                not isinstance(schedule, dict)
                or type(schedule.get("type")) is not int
                or schedule["type"] != group
                or not isinstance(schedule.get("tram"), list)
                or any(not isinstance(item, dict) for item in schedule["tram"])
            ):
                raise InvalidPowerProfilesError("Unsupported schedule")
            # Reject non-finite JSON numbers instead of silently rewriting them.
            json.dumps(schedule, allow_nan=False)
            schedules.append(schedule)
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidPowerProfilesError("Unsupported schedules") from error
    return schedules


def _find_profile(
    profiles: list[dict[str, Any]], baseline: dict[str, Any]
) -> dict[str, Any]:
    """Identify a unique record by device and name, never a shared timestamp."""
    matches = [
        profile
        for profile in profiles
        if profile["deviceId"] == baseline["deviceId"]
        and profile["name"] == baseline["name"]
    ]
    if len(matches) != 1:
        raise PowerProfileConflictError("Profile missing or ambiguous")
    return matches[0]


def _content(profile: dict[str, Any]) -> str:
    """Compare complete content, tolerating only shared timestamp changes."""
    schedules = _schedules(profile)
    content = {
        **{key: value for key, value in profile.items() if key != "updateAt"},
        "powerweekday": schedules[0],
        "powerweekend": schedules[1],
    }
    try:
        return json.dumps(content, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise InvalidPowerProfilesError("Unsupported profile content") from error


def profile_revision(profile: dict[str, Any]) -> str:
    """Fingerprint the complete baseline shown to an editor."""
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


def battery_permission_intervals(profile: dict[str, Any]) -> list[tuple[int, int]]:
    """Recognise native permission fields in the portal's modes 0 and 2."""
    if not editable_profile(profile):
        return []
    return [
        (group, index)
        for group, schedule in enumerate(_schedules(profile))
        for index, interval in enumerate(schedule["tram"])
        if type(interval.get("charge_fv_mode")) is int
        and interval["charge_fv_mode"] in (0, 2)
        and type(interval.get("bat_mode")) is int
        and interval["bat_mode"] in (0, 1)
    ]


def profile_battery_slots(profile: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """Address recognised fields by profile/day/bounds, never a shifting index."""
    slots: dict[str, list[tuple[int, int]]] = {}
    for group, index in battery_permission_intervals(profile):
        interval = _schedules(profile)[group]["tram"][index]
        bounds = [interval.get(key) for key in ("hourStart", "hourEnd")]
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in bounds
        ):
            continue
        start, end = bounds
        if not 0 <= start < end <= 24:  # noqa: PLR2004
            continue
        key = json.dumps(
            [
                profile["name"],
                group,
                str(Decimal(str(start)).normalize()),
                str(Decimal(str(end)).normalize()),
            ]
        )
        slots.setdefault(key, []).append((group, index))
    return {key: matches[0] for key, matches in slots.items() if len(matches) == 1}


class PowerProfileCoordinator(DataUpdateCoordinator):
    """Shared confirmed Cloud snapshots for the panel and profile entities."""

    def __init__(
        self, hass: HomeAssistant, runtime: V2CEntryRuntimeData, device_id: str
    ) -> None:
        """Read profiles independently of frequent charging telemetry."""
        self.runtime = runtime
        self.device_id = device_id
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=f"V2C profiles {device_id}",
            update_method=self._async_read,
            update_interval=timedelta(minutes=15),
        )

    async def _async_read(self) -> list[dict[str, Any]]:
        """Read full profiles, keeping Cloud failures out of telemetry setup."""
        if not self.runtime.cloud_commands_available:
            raise UpdateFailed("V2C Cloud is unavailable")
        try:
            async with self.runtime.profile_lock:
                return read_profile_list(
                    await self.runtime.client.async_list_personal_power_profiles(
                        self.device_id
                    ),
                    self.device_id,
                )
        except (
            V2CAuthError,
            V2CRequestError,
            ClientError,
            TimeoutError,
            InvalidPowerProfilesError,
        ) as error:
            raise UpdateFailed("Could not read V2C Cloud profiles") from error

    def profile(self, name: str) -> dict[str, Any]:
        """Resolve exactly one profile from a successful snapshot."""
        if not self.last_update_success or not isinstance(self.data, list):
            raise InvalidPowerProfilesError("No confirmed profile snapshot")
        matches = [profile for profile in self.data if profile["name"] == name]
        if len(matches) != 1:
            raise InvalidPowerProfilesError("Profile missing or ambiguous")
        return deepcopy(matches[0])

    async def async_save(
        self, name: str, revision: str, interval: tuple[int, int], *, allowed: bool
    ) -> None:
        """Save an explicit, unchanged baseline using the verified operation."""
        if not self.runtime.cloud_commands_available:
            raise InvalidPowerProfilesError("V2C Cloud is unavailable")
        baseline = self.profile(name)
        if profile_revision(baseline) != revision:
            raise PowerProfileConflictError("The displayed profile has changed")
        if type(allowed) is not bool or interval not in battery_permission_intervals(
            baseline
        ):
            raise InvalidPowerProfilesError("Unsupported battery interval")
        entries = [
            {
                "group": group,
                "source": index,
                "values": {"allow_battery": allowed}
                if (group, index) == interval
                else {},
            }
            for group, schedule in enumerate(_schedules(baseline))
            for index in range(len(schedule["tram"]))
        ]
        await async_manage_profile(
            self, "edit", name, revision, entries=entries, confirm_active=True
        )

    async def async_update_payload(self, name: str, payload: dict[str, Any]) -> None:
        """Save an existing service payload with the panel's shared safeguards."""
        await self.async_refresh()
        baseline = self.profile(name)
        await async_manage_profile(
            self,
            "edit",
            name,
            profile_revision(baseline),
            payload=payload,
            confirm_active=True,
        )


def editable_profile(profile: dict[str, Any]) -> bool:
    """Accept only known record metadata and losslessly parseable schedules."""
    if (
        type(profile.get("active")) is not bool
        or not isinstance(profile.get("updateAt"), str)
        or set(profile)
        - {"deviceId", "name", "active", "updateAt", "powerweekday", "powerweekend"}
    ):
        return False
    try:
        _schedules(profile)
    except InvalidPowerProfilesError:
        return False
    return True


def _number(value: Any) -> Decimal:
    """Validate finite decimal form values without coercing booleans or null."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InvalidPowerProfilesError("A finite number is required")
    try:
        number = Decimal(str(value))
    except ArithmeticError as error:
        raise InvalidPowerProfilesError("Invalid decimal value") from error
    if not number.is_finite():
        raise InvalidPowerProfilesError("A finite number is required")
    return number


def supports_isolated_profiles(coordinator: PowerProfileCoordinator) -> bool:
    """Offer isolated edits on documented models or an already observed mode 4."""
    model = build_device_info(
        coordinator.runtime.coordinator, coordinator.device_id
    ).get("model")
    if isinstance(model, str) and model.strip().casefold() in {"trydan", "trydan pro"}:
        return True
    if (
        isinstance(model, str)
        and not model.casefold().startswith("model ")
        and model != "V2C"
    ):
        return False
    for profile in coordinator.data or []:
        with suppress(InvalidPowerProfilesError):
            if any(
                interval.get("charge_fv_mode") == 4  # noqa: PLR2004
                for schedule in _schedules(profile)
                for interval in schedule["tram"]
            ):
                return True
    return False


def _edited_power(mode: int, values: dict[str, Any]) -> Decimal | None:
    """Validate separate power/deviation and isolated discharge form fields."""
    if "battery_discharge_w" in values:
        number = _number(values["battery_discharge_w"])
        # Public portal checkDataIsCorrect and assignPersonalizedPower (mode 4).
        # These are form constraints, not verified firmware/electrical limits.
        if mode != 4 or "power_value" in values or not 0 <= number <= 10000:  # noqa: PLR2004
            raise InvalidPowerProfilesError(
                "Battery discharge requires isolated mode and the portal's 0-10000 W range"
            )
        return number / 100
    if "power_value" not in values:
        return None
    number = _number(values["power_value"])
    if mode in (0, 2) and 0 <= number <= 5000:  # noqa: PLR2004
        return number * 10
    if mode == 1 and -10000 <= number <= 10000:  # noqa: PLR2004
        return number / 100
    raise InvalidPowerProfilesError("Unsupported power or deviation")


def profile_edit_body(
    profile: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build schedules from original interval templates and explicit form edits."""
    if not editable_profile(profile) or not isinstance(entries, list):
        raise InvalidPowerProfilesError("Unsupported profile")
    original = _schedules(profile)
    schedules = deepcopy(original)
    for schedule in schedules:
        schedule["tram"] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"group", "source", "values"}:
            raise InvalidPowerProfilesError("Invalid interval edit")
        group, source, values = entry["group"], entry["source"], entry["values"]
        if (
            type(group) is not int
            or group not in (0, 1)
            or type(source) is not int
            or not 0 <= source < len(original[group]["tram"])
        ):
            raise InvalidPowerProfilesError("Invalid original interval reference")
        if not isinstance(values, dict) or set(values) - {
            "hourStart",
            "hourEnd",
            "mode",
            "power_value",
            "battery_discharge_w",
            "allow_battery",
            "priority",
        }:
            raise InvalidPowerProfilesError("Unsupported interval field")
        interval = deepcopy(original[group]["tram"][source])
        mode = values.get("mode", interval.get("charge_fv_mode"))
        if type(mode) is not int or mode not in (0, 1, 2, 3, 4):
            raise InvalidPowerProfilesError("Unknown photovoltaic mode")
        if (
            mode != interval.get("charge_fv_mode")
            and mode in (0, 1, 2)
            and "power_value" not in values
        ):
            raise InvalidPowerProfilesError(
                "Choose power explicitly when changing mode"
            )
        if (
            mode == 4  # noqa: PLR2004
            and mode != interval.get("charge_fv_mode")
            and "battery_discharge_w" not in values
        ):
            raise InvalidPowerProfilesError(
                "Choose battery discharge explicitly when changing mode"
            )
        interval["charge_fv_mode"] = mode
        for key in ("hourStart", "hourEnd"):
            if key in values:
                number = _number(values[key])
                if not 0 <= number <= 24:  # noqa: PLR2004
                    raise InvalidPowerProfilesError(
                        "Hours must be within the observed 0-24 day"
                    )
                interval[key] = (
                    int(number)
                    if number == number.to_integral_value()
                    else float(number)
                )
        stored = _edited_power(mode, values)
        if stored is not None and stored != interval.get("power"):
            interval["power"] = float(stored)
        if "allow_battery" in values:
            if (
                mode not in (0, 2)
                or type(values["allow_battery"]) is not bool
                or type(interval.get("bat_mode")) is not int
                or interval["bat_mode"] not in (0, 1)
            ):
                raise InvalidPowerProfilesError("Battery permission is not available")
            interval["bat_mode"] = 0 if values["allow_battery"] else 1
        if "priority" in values:
            if (
                mode != 1
                or values["priority"] not in ("home", "vehicle")
                or type(interval.get("bat_prio")) is not int
                or interval["bat_prio"] not in (0, 1)
            ):
                raise InvalidPowerProfilesError("Battery priority is not available")
            interval["bat_prio"] = 0 if values["priority"] == "home" else 1
        schedules[group]["tram"].append(interval)
    for group, schedule in enumerate(schedules):
        if original[group]["tram"] and not schedule["tram"]:
            raise InvalidPowerProfilesError(
                "An empty day schedule has unverified semantics"
            )
        previous_end = Decimal(0)
        for interval in sorted(
            schedule["tram"], key=lambda item: _number(item.get("hourStart"))
        ):
            start, end = (
                _number(interval.get("hourStart")),
                _number(interval.get("hourEnd")),
            )
            if not 0 <= start < end <= 24 or start < previous_end:  # noqa: PLR2004
                raise InvalidPowerProfilesError("Invalid or overlapping time intervals")
            previous_end = end
    return {"powers": schedules}


def _validate_isolated_edits(
    coordinator: PowerProfileCoordinator, entries: Any
) -> None:
    """Check mode availability independently from the profile format builder."""
    if not isinstance(entries, list):
        return
    uses_isolated = any(
        isinstance(item, dict)
        and isinstance(item.get("values"), dict)
        and (item["values"].get("mode") == 4 or "battery_discharge_w" in item["values"])  # noqa: PLR2004
        for item in entries
    )
    if uses_isolated and not supports_isolated_profiles(coordinator):
        raise InvalidPowerProfilesError(
            "Isolated profiles require a verified Trydan/Trydan Pro or an existing isolated schedule"
        )


def _merge_fields(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Preserve omitted extension fields, including nested phase settings."""
    merged = deepcopy(original)
    for key, value in changes.items():
        merged[key] = (
            _merge_fields(merged[key], value)
            if isinstance(merged.get(key), dict) and isinstance(value, dict)
            else deepcopy(value)
        )
    return merged


def _service_profile_body(
    baseline: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Accept native API units, without guessing conversions for other formats."""
    if not isinstance(payload, dict) or not isinstance(payload.get("powers"), list):
        raise InvalidPowerProfilesError("Profile must contain a powers schedule list")
    powers = payload["powers"]
    if len(powers) != 2:  # noqa: PLR2004
        raise InvalidPowerProfilesError(
            "Both weekday and weekend schedules are required"
        )
    candidate = deepcopy(baseline)
    try:
        for group, field in enumerate(("powerweekday", "powerweekend")):
            candidate[field] = json.dumps(powers[group], allow_nan=False)
    except (TypeError, ValueError) as error:
        raise InvalidPowerProfilesError(
            "Profile must contain finite JSON values"
        ) from error
    schedules = _schedules(candidate)
    for original, schedule in zip(_schedules(baseline), schedules, strict=True):
        if original["tram"] and not schedule["tram"]:
            raise InvalidPowerProfilesError(
                "An empty day schedule has unverified semantics"
            )
        intervals = []
        for index, interval in enumerate(schedule["tram"]):
            matches = [
                item
                for item in original["tram"]
                if all(
                    item.get(key) == interval.get(key)
                    for key in ("hourStart", "hourEnd")
                )
            ]
            source = matches[0] if len(matches) == 1 else {}
            if not matches and len(original["tram"]) == len(schedule["tram"]):
                source = original["tram"][index]
            intervals.append(_merge_fields(source, interval))
        schedule.update(_merge_fields(original, schedule))
        schedule["tram"] = intervals
    candidate["powerweekday"] = json.dumps(schedules[0])
    candidate["powerweekend"] = json.dumps(schedules[1])
    entries = [
        {"group": group, "source": index, "values": {}}
        for group, schedule in enumerate(schedules)
        for index in range(len(schedule["tram"]))
    ]
    # Reuse schedule validation without applying the editor's human-unit conversion.
    validated = profile_edit_body(candidate, entries)
    return {**deepcopy(payload), "powers": validated["powers"]}


def _profile_write_body(
    coordinator: PowerProfileCoordinator,
    baseline: dict[str, Any],
    *,
    action: str,
    entries: list[dict[str, Any]] | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate either an editor draft or the existing service's native payload."""
    _validate_isolated_edits(coordinator, entries)
    if payload is None:
        return (
            profile_edit_body(baseline, entries)
            if entries is not None
            else {"powers": _schedules(baseline)}
        )
    if action != "edit" or entries is not None:
        raise InvalidPowerProfilesError("A service payload is only valid for an edit")
    body = _service_profile_body(baseline, payload)
    _validate_isolated_edits(
        coordinator,
        [
            {"values": {"mode": interval.get("charge_fv_mode")}}
            for schedule in body["powers"]
            for interval in schedule["tram"]
        ],
    )
    return body


async def async_manage_profile(  # noqa: PLR0913
    coordinator: PowerProfileCoordinator,
    action: str,
    name: str,
    revision: str,
    *,
    new_name: str | None = None,
    entries: list[dict[str, Any]] | None = None,
    confirm_active: bool = False,
    payload: dict[str, Any] | None = None,
) -> None:
    """Create, edit, select or delete a profile with explicit optimistic locking."""
    if (
        action not in ("create", "edit", "activate", "delete")
        or not coordinator.runtime.cloud_commands_available
    ):
        raise InvalidPowerProfilesError("Unsupported or unavailable operation")
    baseline = coordinator.profile(name)
    if profile_revision(baseline) != revision or not editable_profile(baseline):
        raise PowerProfileConflictError("Reload the profile before continuing")
    body = _profile_write_body(
        coordinator, baseline, action=action, entries=entries, payload=payload
    )
    if action in ("activate", "delete") and entries is not None:
        raise InvalidPowerProfilesError("Selection and deletion cannot contain edits")
    if action == "edit" and entries is None and payload is None:
        raise InvalidPowerProfilesError("An explicit profile draft is required")
    if action == "edit" and baseline["active"] and confirm_active is not True:
        raise InvalidPowerProfilesError(
            "Explicit confirmation is required for an active profile"
        )
    if action == "delete" and baseline["active"]:
        raise InvalidPowerProfilesError(
            "Activate another profile before deleting this one"
        )
    if action == "create" and (not isinstance(new_name, str) or not new_name.strip()):
        raise InvalidPowerProfilesError("A nonempty new profile name is required")
    client = coordinator.runtime.client
    try:
        async with coordinator.runtime.profile_lock:
            before = read_profile_list(
                await client.async_list_personal_power_profiles(coordinator.device_id),
                coordinator.device_id,
            )
            if _find_profile(before, baseline) != baseline:
                raise PowerProfileConflictError("Profile changed during editing")
            expected = deepcopy(before)
            if len({p["name"] for p in before}) != len(before) or any(
                type(p.get("active")) is not bool for p in before
            ):
                raise PowerProfileConflictError(
                    "Ambiguous profile identities or activation states"
                )
            for profile in before:
                _content(profile)
            target = _find_profile(expected, baseline)
            if action == "edit" and {"powers": _schedules(baseline)} == body:
                coordinator.async_set_updated_data(before)
                return
            if action == "activate" and baseline["active"]:
                coordinator.async_set_updated_data(before)
                return
            if action == "create":
                if any(
                    p["name"].strip().casefold() == new_name.strip().casefold()
                    for p in before
                ):
                    raise PowerProfileConflictError("The new name is already present")
                target = deepcopy(baseline)
                target.update(name=new_name, active=False)
                expected.append(target)
            if action in ("edit", "create"):
                target["powerweekday"] = json.dumps(body["powers"][0])
                target["powerweekend"] = json.dumps(body["powers"][1])
            elif action == "delete":
                expected.remove(target)
            else:
                for profile in expected:
                    profile["active"] = profile["name"] == name
            stamp = str(time.time_ns() // 1_000_000)
            with suppress(V2CRequestError, ClientError, TimeoutError):
                if action in ("edit", "create"):
                    await client.async_save_personal_power_profile(
                        coordinator.device_id, target["name"], stamp, body
                    )
                elif action == "activate":
                    await client.async_activate_personal_power_profile(
                        coordinator.device_id, name, stamp, body
                    )
                else:
                    # DELETE's documentation identifies this as the profile's
                    # timestamp. Do not substitute the POST send-time format.
                    await client.async_delete_personal_power_profile(
                        coordinator.device_id, name, baseline["updateAt"]
                    )
            try:
                after = read_profile_list(
                    await client.async_list_personal_power_profiles(
                        coordinator.device_id
                    ),
                    coordinator.device_id,
                )
                if len(after) != len(expected):
                    raise PowerProfileSaveUnconfirmedError("Unexpected profile count")
                for profile in expected:
                    if _content(_find_profile(after, profile)) != _content(profile):
                        raise PowerProfileSaveUnconfirmedError(
                            "Unexpected profile content or activation"
                        )
            except (
                InvalidPowerProfilesError,
                V2CAuthError,
                V2CRequestError,
                ClientError,
                TimeoutError,
            ) as error:
                raise PowerProfileSaveUnconfirmedError(
                    "Operation not confirmed; refresh before another operation"
                ) from error
            coordinator.async_set_updated_data(after)
    except (
        InvalidPowerProfilesError,
        V2CAuthError,
        V2CRequestError,
        ClientError,
        TimeoutError,
    ):
        coordinator.async_set_update_error(
            UpdateFailed("Refresh profiles before continuing")
        )
        raise
