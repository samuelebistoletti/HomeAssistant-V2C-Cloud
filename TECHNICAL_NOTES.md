# V2C Cloud Integration – Technical Notes

## 1. Architecture Overview

### Components
- **Cloud REST client** (`custom_components/v2c_cloud/v2c_cloud.py`) wraps the documented endpoints at `https://v2c.cloud/kong/v2c_service`, normalises responses, enforces retry/backoff and caches pairings, RFID lists and firmware version.
- **Local API helper** (`custom_components/v2c_cloud/local_api.py`) resolves the device IP, polls `http://<ip>/RealTimeData`, sends write commands via `http://<ip>/write/KeyWord=Value` and raises `V2CLocalApiError` on LAN issues.
- **Config flow** collects the API key (and optional base URL), validates it via `/pairings/me`, and stores a deterministic unique ID.
- **Cloud coordinator** (`DataUpdateCoordinator`) handles pairing/device polling with an adaptive interval (`ceil(devices * 86400 / 850)` seconds, min 90 s) to keep calls under the V2C 1000/day limit while leaving headroom for manual commands.
- **Local coordinators** are created on demand per device, polling `/RealTimeData` every 30 s. All entities consuming local telemetry share the same coordinator instance to avoid duplicate requests.
- **Platforms** (binary_sensor, sensor, switch, number, select, button) inherit from `V2CEntity`, which exposes helpers for coordinator data, pairing metadata and case-insensitive lookups. Entities prefer local data whenever available, falling back to the cloud payload, and local-only entities register as listeners on their per-device local coordinator so the UI gets refreshed immediately after each LAN poll.
- **Services** are registered once. Cloud mutating services use the REST client and refresh the cloud coordinator; LAN operations leverage `async_write_keyword` and refresh the relevant local coordinator if needed.

### Data Flow
```
Config Flow ──► V2CClient (cloud) ──► Cloud Coordinator ──► Entities / Services
                                        │
                                        └──► Local Coordinators (per device)
```

## 2. Coordinator Data Model

```python
coordinator.data = {
    "pairings": [...],
    "devices": {
        device_id: {
            "pairing": {...},
            "connected": bool | None,
            "current_state": Any,
            "reported": dict | None,
            "reported_raw": Any,
            "rfid_cards": list | None,
            "version": str | None,
            "additional": {
                "reported_lower": dict,
                "reported_timestamp": float,
                "rfid_cards_raw": Any,
                "_rfid_last_success": float,
                "_rfid_next_refresh": float,
                "_version_next_refresh": float,
                "version_info": dict | None,
                "static_ip": str | None,
            },
        },
    },
    "rate_limit": {"limit": int | None, "remaining": int | None, "reset": int | None},
}
```

Local coordinators store the raw `RealTimeData` payload along with `_static_ip` so other components can reuse it.

## 3. API Coverage

### Cloud
- `/pairings/me`, `/device/reported`, `/device/wifilist`, `/version`
- `/device/charger_until_*`, `/device/startchargekw`, `/device/startchargeminutes`, `/device/reboot`, `/device/update`
- `/device/logo_led`, `/device/set_rfid`, `/device/ocpp`, `/device/inst_type`, `/device/slave_type`, `/device/language`, `/device/ocpp_id`, `/device/ocpp_addr`, `/device/wifi`, `/device/inverter_ip`
- `/device/rfid` (GET/POST/DELETE), `/device/rfid/tag` (POST/PUT)
- `/device/savepersonalicepower/v2`, `/device/personalicepower/v2` (POST/GET/DELETE), `/device/personalicepower/all`
- `/stadistic/device`, `/stadistic/global/me`

Numeric query parameters are posted as strings (as per the public documentation). Responses are coerced to native Python types whenever possible.

### Local
- `GET /RealTimeData` for telemetry (telemetry keys: ChargeState, ChargePower, VoltageInstallation, etc.)
- `GET /write/KeyWord=Value` for supported commands (`Dynamic`, `Locked`, `Intensity`, `MinIntensity`, `MaxIntensity`, `Paused`, `DynamicPowerMode`, `ContractedPower`, ...). Unsupported commands remain on the cloud client.

`V2CLocalApiError` is raised on timeouts/HTTP errors and converted into `HomeAssistantError` at the entity/service layer.

## 4. Entity Guidelines

- `V2CEntity.get_reported_value(*keys)` performs case-insensitive lookup on the cloud payload; helpers in `local_api.py` retrieve cached LAN data.
- Switches, selects and numbers keep a ~20-second optimistic lock after issuing a command to mask discrepancies until the next LAN or cloud refresh completes.
- Local selects/numbers/switches register listeners on the per-device local coordinator, so they repopulate instantly after reloads instead of waiting for the next cloud poll.
- Cloud commands always go through `_async_call_and_refresh(..., refresh=True)`; LAN commands skip the cloud refresh to avoid extra API calls.
- Entity unique IDs follow the pattern `f"{device_id}_{keyword}"` using the keyword exposed by the API whenever possible (e.g. `charge_power`, `locked_state`, `intensity`).

## 5. Services & Events

- Mutating cloud services call `_execute_and_refresh`, which wraps the coroutine in error handling (`V2CAuthError`, `V2CRequestError`) and triggers a coordinator refresh on success.
- Data retrieval services publish the raw response via Home Assistant events: `v2c_cloud_wifi_scan`, `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`, `v2c_cloud_power_profiles`.

## 6. Error Handling

- `V2CAuthError` causes re-auth flows when raised during coordinator refresh or service execution.
- `V2CRequestError`/`V2CRateLimitError` keep previous data when refresh fails; the coordinator logs warnings but does not break the update loop.
- `V2CLocalApiError` is mapped to `HomeAssistantError` so the UI reports issues without killing the event loop.
- Rate limiting applies exponential backoff (up to 3 retries). When capacity is exceeded the coordinator retains the cached payload and updates resume on the next scheduled interval.

## 7. Development Checklist

1. Update `strings.json`, translations (`translations/en.json`, `translations/it.json`) and documentation (`README.md`, `TECHNICAL_NOTES.md`, `CHANGELOG.md`).
2. Review coordinator intervals when adding new cloud polling to keep the daily budget intact.
3. Validate new local keywords against the official spreadsheet before exposing them in the UI.
4. Ensure logging remains at `debug` level for HTTP details; avoid excessive logging in the happy path.
5. Run `python -m compileall custom_components/v2c_cloud` before committing to catch syntax errors.

## 8. Testing Recommendations

1. **API key flow** – invalid key should raise `ConfigEntryAuthFailed` and prompt the re-auth UI.
2. **Multiple devices** – verify the adaptive interval (check `coordinator.update_interval`).
3. **Local commands** – test start/pause charge, dynamic mode toggle, and intensity changes with the wallbox reachable on LAN.
4. **Cloud commands** – test logo LED, RFID enable/disable, OCPP configuration, firmware update, timers, RFID services.
5. **Failure scenarios** – simulate LAN unavailability and cloud 429/timeout responses to ensure fallbacks behave correctly.
6. **Statistics & events** – call `get_device_statistics` and confirm the `v2c_cloud_device_statistics` event carries the raw payload.
