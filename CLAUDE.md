# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_v2c_client.py -v

# Run a single test
python -m pytest tests/test_v2c_client.py::test_function_name -v

# Lint and format (runs ruff format + ruff check --fix)
./scripts/lint

# Check compilation
python -m compileall custom_components/v2c_cloud

# Install dependencies
pip install -r requirements.txt -r requirements_test.txt
```

## Architecture

This is a Home Assistant custom integration for V2C EV chargers using a **cloud + local hybrid** approach:

- **Cloud coordinator** (`__init__.py`): Polls V2C Cloud REST API at `https://v2c.cloud/kong/v2c_service` with adaptive rate (min 90s, calculated as `ceil(devices * 86400 / 850)` to stay within 1000 calls/day). Handles pairings, device state, RFID, settings, and commands.
- **Local coordinators** (`local_api.py`): One per device, polling `/RealTimeData` every 30s for real-time telemetry. Local data takes priority over cloud data for entities.

### Key Files

| File | Purpose |
|------|---------|
| `custom_components/v2c_cloud/__init__.py` | Entry point: coordinator setup, service registration, entity platform loading |
| `custom_components/v2c_cloud/v2c_cloud.py` | `V2CClient` REST client with error handling and pairings cache |
| `custom_components/v2c_cloud/local_api.py` | Local HTTP helpers: `fetch_real_time_data()`, `send_write_command()` |
| `custom_components/v2c_cloud/config_flow.py` | API key validation, IP fallback setup, re-auth / reconfigure flows |
| `custom_components/v2c_cloud/entity.py` | `V2CEntity` base class, device info builder |
| `custom_components/v2c_cloud/const.py` | Domain, service names, limits, localization keys |

### Platform Modules

All platform entities inherit from `V2CEntity` and subscribe to either the cloud coordinator or a per-device local coordinator:

- `sensor.py`: Power readings, voltages, device identifiers, WiFi info
- `switch.py`: Charger lock, pause, dynamic mode, timers, logo LED, RFID, OCPP
- `number.py`: Current intensity (min/max/contracted power)
- `select.py`: Installation type, slave device type, language, dynamic power mode
- `binary_sensor.py`: V2C Cloud connectivity status
- `button.py`: Reboot, firmware update trigger

### Data Flow

```
Config Flow → V2CClient → Cloud Coordinator → Entities (cloud data)
                               ↓
                    per-device Local Coordinators → Entities (local/real-time data)
                               ↓
                         Services (mutations) → coordinator.async_request_refresh()
```

### Coordinator Data Model

```python
coordinator.data = {
    "pairings": [...],           # list of device pairing dicts
    "devices": {
        device_id: {
            "pairing": {...},
            "connected": bool | None,
            "current_state": any,
            "reported": dict,    # cloud /device/reported state
            "rfid_cards": list | None,
            "version": str | None,
            "additional": {
                "reported_lower": dict,   # lowercase keys for lookups
                "static_ip": str | None,
                ...
            }
        }
    },
    "rate_limit": {"limit", "remaining", "reset"}
}
```

### Error Handling Conventions

- `V2CAuthError` (401) → triggers HA re-auth flow
- `V2CRateLimitError` (429) → retains previous data, exponential backoff
- `403` / network timeout on `/pairings/me` → fallback to stored device ID for local-only mode
- Local failures → retry with backoff, schedule follow-up refresh
- Optimistic smoothing (~20s) applied to cloud commands to prevent UI state flapping

### Release Process

1. Update version in `custom_components/v2c_cloud/manifest.json`
2. Push to `main`
3. CI (tests + security) must pass
4. `tag-and-release.yaml` workflow auto-creates GitHub release with ZIP artifact
