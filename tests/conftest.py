"""Shared fixtures and module stubs for the V2C Cloud test suite."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Homeassistant module stubs
# Must be installed before importing any integration module.
# ---------------------------------------------------------------------------

def _install_compat_stubs() -> None:
    """Install compatibility stubs for packages removed in newer Python/aiohttp."""
    import asyncio

    # async_timeout was deprecated and removed; map it to asyncio.timeout (Python 3.11+)
    if "async_timeout" not in sys.modules:
        at = types.ModuleType("async_timeout")
        at.timeout = asyncio.timeout
        sys.modules["async_timeout"] = at


def _install_ha_stubs() -> None:
    """Inject minimal homeassistant stubs into sys.modules."""

    def _mod(name: str) -> types.ModuleType:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
        return sys.modules[name]

    _mod("homeassistant")

    # homeassistant.core
    ha_core = _mod("homeassistant.core")
    if not hasattr(ha_core, "HomeAssistant"):
        class HomeAssistant:
            def __init__(self) -> None:
                self.async_create_task = MagicMock()
        ha_core.HomeAssistant = HomeAssistant
    if not hasattr(ha_core, "ServiceCall"):
        ha_core.ServiceCall = MagicMock
    if not hasattr(ha_core, "callback"):
        ha_core.callback = lambda f: f

    # homeassistant.const
    ha_const = _mod("homeassistant.const")
    if not hasattr(ha_const, "Platform"):
        class Platform:
            SENSOR = "sensor"
            SWITCH = "switch"
            NUMBER = "number"
            SELECT = "select"
            BINARY_SENSOR = "binary_sensor"
            BUTTON = "button"
        ha_const.Platform = Platform
    ha_const.UnitOfPower = MagicMock()
    ha_const.UnitOfEnergy = MagicMock()
    ha_const.UnitOfElectricCurrent = MagicMock()
    ha_const.UnitOfElectricPotential = MagicMock()
    ha_const.UnitOfTemperature = MagicMock()
    ha_const.CONF_HOST = "host"
    ha_const.CONF_NAME = "name"

    # homeassistant.exceptions
    ha_exc = _mod("homeassistant.exceptions")
    for exc_name in (
        "ConfigEntryNotReady",
        "ConfigEntryAuthFailed",
        "HomeAssistantError",
        "ServiceNotFound",
    ):
        if not hasattr(ha_exc, exc_name):
            setattr(ha_exc, exc_name, type(exc_name, (Exception,), {}))

    # homeassistant.config_entries
    ha_ce = _mod("homeassistant.config_entries")
    if not hasattr(ha_ce, "ConfigEntry"):
        ha_ce.ConfigEntry = MagicMock
    if not hasattr(ha_ce, "ConfigFlow"):
        ha_ce.ConfigFlow = object
    ha_ce.config_entries = MagicMock()

    # homeassistant.data_entry_flow
    ha_def = _mod("homeassistant.data_entry_flow")
    ha_def.FlowResult = dict

    # homeassistant.helpers (parent package)
    _mod("homeassistant.helpers")

    # homeassistant.helpers.update_coordinator
    ha_coord = _mod("homeassistant.helpers.update_coordinator")
    if not hasattr(ha_coord, "UpdateFailed"):
        class UpdateFailed(Exception):
            pass
        ha_coord.UpdateFailed = UpdateFailed

    if not hasattr(ha_coord, "DataUpdateCoordinator"):
        class DataUpdateCoordinator:
            def __init__(self, hass, logger, *, name, update_method, update_interval):
                self.data: Any = None
                self.last_update_success: bool = True
                self.update_interval = update_interval
                self._update_method = update_method

            async def async_config_entry_first_refresh(self) -> None:
                from homeassistant.exceptions import ConfigEntryNotReady
                try:
                    self.data = await self._update_method()
                except ha_coord.UpdateFailed as err:
                    raise ConfigEntryNotReady(str(err)) from err

            async def async_refresh(self) -> None:
                self.data = await self._update_method()

            async def async_request_refresh(self) -> None:
                self.data = await self._update_method()

        ha_coord.DataUpdateCoordinator = DataUpdateCoordinator

    if not hasattr(ha_coord, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init_subclass__(cls, **kwargs: Any) -> None:
                super().__init_subclass__(**kwargs)

            def __class_getitem__(cls, item: Any) -> Any:
                return cls

        ha_coord.CoordinatorEntity = CoordinatorEntity

    # homeassistant.helpers.aiohttp_client
    ha_aiohttp = _mod("homeassistant.helpers.aiohttp_client")
    if not hasattr(ha_aiohttp, "async_get_clientsession"):
        ha_aiohttp.async_get_clientsession = MagicMock()

    # homeassistant.helpers.event
    ha_event = _mod("homeassistant.helpers.event")
    if not hasattr(ha_event, "async_call_later"):
        ha_event.async_call_later = MagicMock()

    # homeassistant.helpers.device_registry
    ha_dr = _mod("homeassistant.helpers.device_registry")
    if not hasattr(ha_dr, "DeviceEntryType"):
        class DeviceEntryType:
            SERVICE = "service"
        ha_dr.DeviceEntryType = DeviceEntryType
    if not hasattr(ha_dr, "DeviceInfo"):
        class DeviceInfo(dict):
            pass
        ha_dr.DeviceInfo = DeviceInfo

    # homeassistant.helpers.config_validation (cv)
    ha_cv = _mod("homeassistant.helpers.config_validation")
    ha_cv.string = str
    ha_cv.boolean = bool
    ha_cv.positive_int = int
    ha_cv.ensure_list = list
    ha_cv.matches_regex = lambda pattern: str
    ha_cv.config_entry_only_config_schema = lambda domain: {}
    ha_cv.ALLOW_EXTRA = object()

    # homeassistant.helpers.typing
    ha_typing = _mod("homeassistant.helpers.typing")
    ha_typing.ConfigType = dict

    # homeassistant.helpers.entity_platform
    ha_ep = _mod("homeassistant.helpers.entity_platform")
    ha_ep.AddEntitiesCallback = MagicMock

    # homeassistant.components.* stubs needed by entity platforms
    for comp in ("sensor", "switch", "number", "select", "binary_sensor", "button"):
        comp_mod = _mod(f"homeassistant.components.{comp}")
        comp_mod.SensorEntity = object
        comp_mod.SwitchEntity = object
        comp_mod.NumberEntity = object
        comp_mod.SelectEntity = object
        comp_mod.BinarySensorEntity = object
        comp_mod.ButtonEntity = object
        comp_mod.SensorDeviceClass = MagicMock()
        comp_mod.SensorStateClass = MagicMock()
        comp_mod.SwitchDeviceClass = MagicMock()
        comp_mod.BinarySensorDeviceClass = MagicMock()
        comp_mod.NumberMode = MagicMock()
        comp_mod.RestoreEntity = object


_install_compat_stubs()
_install_ha_stubs()


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

DEVICE_ID = "test-device-001"
API_KEY = "test-api-key-abc123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def device_id() -> str:
    return DEVICE_ID


@pytest.fixture
def mock_coordinator_data() -> dict[str, Any]:
    """A minimal coordinator data dict with one device."""
    return {
        "pairings": [{"deviceId": DEVICE_ID, "name": "Test Charger"}],
        "devices": {
            DEVICE_ID: {
                "device_id": DEVICE_ID,
                "pairing": {"deviceId": DEVICE_ID, "name": "Test Charger"},
                "connected": True,
                "current_state": {"ChargeState": 2, "ChargeEnergy": 12.5},
                "reported_raw": {"ChargeState": 2, "ChargeEnergy": 12.5},
                "reported": {"ChargeState": 2, "ChargeEnergy": 12.5},
                "rfid_cards": [],
                "version": "1.2.3",
                "additional": {
                    "static_ip": "192.168.1.100",
                    "reported_lower": {
                        "chargestate": 2,
                        "chargeenergy": 12.5,
                        "connected": True,
                    },
                },
            }
        },
    }


@pytest.fixture
def mock_coordinator(mock_coordinator_data: dict[str, Any]) -> MagicMock:
    """A mock coordinator with pre-populated device data."""
    coordinator = MagicMock()
    coordinator.data = mock_coordinator_data
    return coordinator


@pytest.fixture
def mock_runtime_data(mock_coordinator: MagicMock) -> MagicMock:
    """A mock runtime_data object."""
    runtime_data = MagicMock()
    runtime_data.coordinator = mock_coordinator
    runtime_data.local_coordinators = {}
    return runtime_data
