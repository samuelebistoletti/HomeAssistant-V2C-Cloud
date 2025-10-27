# V2C Cloud Integration – Technical Notes

## 1. Architecture Overview

### Components
- **REST client** (`custom_components/v2c_cloud/v2c_cloud.py`) wraps every documented endpoint exposed at `https://v2c.cloud/kong/v2c_service`. It normalises text responses, converts booleans and numbers, and exposes helpers for timers, RFID, Wi-Fi, and device commands.
- **Config flow** collects the API key (and optional base URL for staging), validates credentials by calling `/pairings/me`, and stores a deterministic unique ID derived from the key.
- **Coordinator** (`DataUpdateCoordinator`) refreshes pairings, device state, and global statistics on a configurable interval (30 seconds by default). It keeps all platforms in sync and handles authentication failures by triggering Home Assistant re-auth.
- **Platforms** (binary sensor, sensor, switch, number, select, button) are thin wrappers around coordinator data. Each entity inherits from a shared base class (`entity.py`) that builds device info, exposes pairing metadata, and provides helpers for the `reported` payload.
- **Services** are registered once per Home Assistant instance and route to client helpers; after each call, the coordinator refreshes to keep entities updated.

### Data Flow
```
Config Flow ──► V2CClient ──► Pairings Validation
                      │
                      └─► DataUpdateCoordinator (pairings + device state + stats)
                                      │
                   ┌──────────────────┼──────────────────┐
                   │                  │                  │
           Entity Platforms     Home Assistant Services  Diagnostics/Logs
```

## 2. Coordinator Data Model

The coordinator stores a dictionary:

```python
coordinator.data = {
    "pairings": [ ... ],               # Raw response from /pairings/me
    "devices": {
        "<device_id>": {
            "pairing": {...},          # Original pairing entry
            "connected": bool | None,
            "current_state": Any,
            "reported": {...} | None,
            "reported_raw": Any,
            "rfid_cards": [...],
            "version": str | None,
            "mac_address": str | None,
            "additional": {
                "reported_lower": {...},  # cached lowercase key map
                "rfid_cards_raw": Any,
            },
        },
        ...
    },
    "global_statistics": [...],        # /stadistic/global/me response
}
```

Entities read this structure exclusively; no platform instantiates its own client or keeps separate caches.

## 3. API Coverage

The client wraps the following operations:
- **Device status**: `/device/connected`, `/device/currentstatecharge`, `/device/reported`, `/device/mac`, `/version`
- **Device control**: `/device/startcharge`, `/device/pausecharge`, `/device/reboot`, `/device/update`
- **Configuration toggles**: `/device/dynamic`, `/device/locked`, `/device/logo_led`, `/device/set_rfid`
- **Parameter updates**: `/device/intensity`, `/device/min_car_int`, `/device/max_car_int`, `/device/maxpower`, `/device/chargefvmode`, `/device/inst_type`, `/device/slave_type`, `/device/language`
- **Wi-Fi and timers**: `/device/wifi`, `/device/timer`
- **RFID management**: `/device/rfid` (GET/POST/DELETE), `/device/rfid/tag`
- **Statistics**: `/stadistic/device`, `/stadistic/global/me`
- **Pairings**: `/pairings/me`

All numeric query parameters are submitted as strings to match the public documentation. Responses are coerced into sensible Python types (bool/float/int/dict) even when the API returns plain text.

## 4. Entity Design Guidelines

- **V2CEntity base class** offers `device_state`, `pairing`, `reported`, and `get_reported_value(*keys)` helpers.
- **Sensors** favour text output when the upstream payload is a dictionary (e.g. charging state). Numeric sensors explicitly convert to float and fall back to cached optimistic values when conversions fail.
- **Switches/Selectors/Numbers** use optimistic updates: the user command is executed, the coordinator is refreshed, and the entity state is eventually confirmed by the API response.
- **Buttons** immediately invoke the underlying API helper and refresh the coordinator afterwards.

## 5. Services

| Service ID | Endpoint | Notes |
|------------|----------|-------|
| `v2c_cloud.set_wifi_credentials` | `/device/wifi` | Requires `ssid` and `password` query params. |
| `v2c_cloud.program_timer` | `/device/timer` | Accepts `timer_id`, `days_of_week`, `time_start`, `time_end`; body is sent as JSON. |
| `v2c_cloud.register_rfid` | `/device/rfid` (POST) | Activates registration mode with provided `tag`. |
| `v2c_cloud.update_rfid_tag` | `/device/rfid/tag` | Updates the display name for an RFID code. |
| `v2c_cloud.delete_rfid` | `/device/rfid` (DELETE) | Removes an RFID card by `code`. |
| `v2c_cloud.trigger_update` | `/device/update` | Initiates firmware update checks. |

Each service locates the owning config entry by device ID, executes the client call, and triggers a coordinator refresh.

## 6. Error Handling

- `V2CAuthError` triggers Home Assistant re-auth flows during coordinator refreshes or service invocations.
- `V2CRequestError` wraps HTTP/network issues with context (status code, message).
- Coordinator updates log warnings for per-device failures but keep processing other devices, returning the last known good data when an API fetch fails.

## 7. Development Checklist

- Keep `.ruff.toml` aligned with the repo style (imports, exceptions, and helper complexity are relaxed intentionally).
- Update translations (`strings.json`, `translations/en.json`, `translations/it.json`) for any new entity or service.
- Document new behaviour in `README.md`, `CHANGELOG.md`, and the service descriptions.
- When the public API spec changes, refresh `docs/v2c_service.yaml` and verify all affected endpoints.

## 8. Testing Recommendations

1. **API key validation** – confirm invalid keys trigger reauth.
2. **Device discovery** – ensure multiple pairings are handled.
3. **Command execution** – start/stop charge, toggles, timers, Wi-Fi credentials, and RFID management.
4. **Statistics retrieval** – validate both per-device and global endpoints across date ranges.
5. **Resilience** – simulate temporary network failures to confirm cached data usage and logging.
