# V2C Cloud Integration – Technical Notes

## 1. Architecture Overview

### Components
- **REST client** (`custom_components/v2c_cloud/v2c_cloud.py`) wraps every documented endpoint exposed at `https://v2c.cloud/kong/v2c_service`. It normalises text responses, converts booleans and numbers, and exposes helpers for timers, RFID, Wi-Fi, and device commands.
- **Config flow** collects the API key (and optional base URL for staging), validates credentials by calling `/pairings/me`, and stores a deterministic unique ID derived from the key.
- **Coordinator** (`DataUpdateCoordinator`) aggiorna pairing e stato dispositivo con un intervallo adattivo (≥90 s) calcolato in base al numero di wallbox, così da rispettare il limite di 1000 richieste/giorno. I pairing vengono messi in cache per 60 minuti; le statistiche globali sono recuperate solo su richiesta servizio.
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
    "pairings": [ ... ],               # Risposta grezza da /pairings/me
    "devices": {
        "<device_id>": {
            "pairing": {...},          # Entry originale del pairing
            "connected": bool | None,
            "current_state": Any,
            "reported": {...} | None,
            "reported_raw": Any,
            "rfid_cards": [...],
            "version": str | None,
            "additional": {
                "reported_lower": {...},     # cache con chiavi in minuscolo
                "reported_timestamp": float, # epoch ottenuto da time.time()
                "rfid_cards_raw": Any,
                "_rfid_last_success": float,
                "_rfid_next_refresh": float,
                "_version_next_refresh": float,
                "version_info": {...},
            },
        },
        ...
    },
    "rate_limit": {                    # Header RateLimit dell'ultima risposta utile
        "limit": int | None,
        "remaining": int | None,
        "reset": int | None,
    },
}
```

Entities read this structure exclusively; no platform instantiates its own client or keeps separate caches.

## 3. API Coverage

The client now wraps every endpoint documented on https://api.v2charge.com/:

- **Device status**: `/device/connected`, `/device/currentstatecharge`, `/device/reported`, `/device/wifilist`, `/version`, `/pairings/me`.
- **Immediate control & scheduling**: `/device/startcharge`, `/device/pausecharge`, `/device/charger_until_energy`, `/device/charger_until_minutes`, `/device/startchargekw`, `/device/startchargeminutes`, `/device/reboot`, `/device/update`.
- **Configuration toggles**: `/device/dynamic`, `/device/locked`, `/device/logo_led`, `/device/set_rfid`, `/device/thirdparty_mode`, `/device/ocpp`.
- **Parameter updates**: `/device/intensity`, `/device/min_car_int`, `/device/max_car_int`, `/device/maxpower`, `/device/denka/max_power`, `/device/chargefvmode`, `/device/inst_type`, `/device/slave_type`, `/device/language`, `/device/wifi`, `/device/inverter_ip`, `/device/ocpp_id`, `/device/ocpp_addr`.
- **RFID management**: `/device/rfid` (GET/POST/DELETE) e `/device/rfid/tag` (POST/PUT) per inserimenti manuali e rinomina.
- **Advanced power profiles (v2)**: `/device/savepersonalicepower/v2`, `/device/personalicepower/v2` (POST/GET/DELETE), `/device/personalicepower/all`.
- **Statistics**: `/stadistic/device`, `/stadistic/global/me`.

All numeric query parameters are still submitted as strings to match the public documentation. Responses are normalised into sensible Python types (bool/float/int/dict) even when the API returns plain text.

## 4. Entity Design Guidelines

- **V2CEntity base class** offers `device_state`, `pairing`, `reported`, and `get_reported_value(*keys)` helpers.
- **Sensors** favour text output when the upstream payload is a dictionary (e.g. charging state). Numeric sensors explicitly convert to float and fall back to cached optimistic values when conversions fail.
- **Switches/Selectors/Numbers** use optimistic updates: the user command is executed, the coordinator is refreshed, and the entity state is eventually confirmed by the API response.
- **Buttons** immediately invoke the underlying API helper and refresh the coordinator afterwards.

## 5. Services

All services are registered once per Home Assistant instance. Those that mutate device state trigger a coordinator refresh; those that simply return data publish the payload as Home Assistant events.

- **Configurazione/Rete**: `set_wifi_credentials`, `program_timer` (ora accetta `start_time`, `end_time`, `active`), `set_thirdparty_mode`, `set_ocpp_enabled`, `set_ocpp_id`, `set_ocpp_address`, `set_denka_max_power`, `set_inverter_ip`, `trigger_update`.
- **Gestione RFID**: `register_rfid` (learning mode), `add_rfid_card` (inserimento manuale UID), `update_rfid_tag`, `delete_rfid`.
- **Ricariche programmate**: `set_charge_stop_energy`, `set_charge_stop_minutes`, `start_charge_for_energy`, `start_charge_for_minutes`.
- **Profili di potenza v2**: `create_power_profile`, `update_power_profile`, `get_power_profile`, `delete_power_profile`, `list_power_profiles` (event `v2c_cloud_power_profiles`).
- **Statistiche e diagnostica**: `get_device_statistics` (event `v2c_cloud_device_statistics`), `get_global_statistics` (event `v2c_cloud_global_statistics`), `scan_wifi_networks` (event `v2c_cloud_wifi_scan`).

Events payloads always include the `device_id` (when available) and the raw response so that automations can persist or notify the data.

## 6. Error Handling

- `V2CAuthError` triggers Home Assistant re-auth flows during coordinator refreshes or service invocations.
- `V2CRequestError` wraps HTTP/network issues with context (status code, message).
- Coordinator updates log warnings for per-device failures but keep processing other devices, returning the last known good data when an API fetch fails.
- Risposte `429 Too Many Requests` generano un backoff esponenziale (fino a tre tentativi) e, in caso di fallimento, fanno riutilizzare i dati cached mantenendo l'intervallo corrente; i metadati `rate_limit` aiutano a diagnosticare eventuali soglie raggiunte.

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
