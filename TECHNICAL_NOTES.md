# V2C Cloud Integration – Technical Notes

## 1. Architecture Overview

### Components
- **Cloud REST client** (`custom_components/v2c_cloud/v2c_cloud.py`) wraps the documented endpoints at `https://v2c.cloud/kong/v2c_service`, normalises responses, enforces retry/backoff and caches pairings, RFID lists and firmware version.
- **Local API helper** (`custom_components/v2c_cloud/local_api.py`) resolves the device IP, polls `http://<ip>/RealTimeData`, fetches keywords absent from that payload (`LogoLED`, `LightLED`) via `GET /read/<keyword>`, sends write commands via `http://<ip>/write/KeyWord=Value` and raises `V2CLocalApiError` on LAN issues. Write keywords are checked against `WRITEABLE_KEYWORDS`, a whitelist mirroring the Trydan Datamanager spec — unknown keywords are rejected before the request is built.
- **Shared networking helper** (`custom_components/v2c_cloud/_net.py::validate_private_ip`) centralises the SSRF guard used by the config flow, the local fetch and the local write paths. The guard rejects unparseable addresses and any IP that is not `is_private`, or that is loopback / link-local / unspecified (Python 3.11+ classifies `169.254.x.x` as `is_private=True`, so an explicit `is_link_local` check is required).
- **Config flow** collects the API key, validates it and stores a deterministic unique ID while always targeting the fixed V2C Cloud endpoint.
- **Cloud coordinator** (`DataUpdateCoordinator`) handles pairing/device polling with an adaptive interval (`ceil(devices * 86400 / 850)` seconds, min 90 s) to keep calls under the V2C 1000/day limit while leaving headroom for manual commands.
- **Local coordinators** are created on demand per device, polling `/RealTimeData` at the user-configured interval (default 30 s, range 5-300 s via the `local_update_interval` option) for LAN devices, or every 120 s for cloud-only (4G) chargers. All entities consuming local telemetry share the same coordinator instance to avoid duplicate requests. The `_async_options_updated` listener applies live interval changes without requiring a reload.
- **LAN-vs-cloud router** (`_async_route_local_or_cloud` in `__init__.py`, added in 1.3.0) is shared by the new control services (start/pause charge, intensity, locked, dynamic). It prefers the LAN write keyword when a `fallback_ip` is configured, falls back transparently to the corresponding cloud endpoint when the LAN call raises `V2CLocalApiError`, and skips the LAN attempt entirely when the entry is flagged as cloud-only. Path selection is logged at DEBUG.
- **Platforms** (binary_sensor, sensor, switch, number, select, button) inherit from `V2CEntity`, which exposes helpers for coordinator data, pairing metadata and case-insensitive lookups. Entities prefer local data whenever available, falling back to the cloud payload, and local-only entities register as listeners on their per-device local coordinator so the UI gets refreshed immediately after each LAN poll.
- **Services** are registered once. Cloud mutating services use the REST client and refresh the cloud coordinator; LAN operations leverage `async_write_keyword` and refresh the relevant local coordinator if needed. 1.3.0 adds 10 new services covering the previously missing cloud surface and the new ChargeMode/LightLED writes.

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
- `/device/set_rfid`, `/device/ocpp`, `/device/inst_type`, `/device/slave_type`, `/device/language`, `/device/ocpp_id`, `/device/ocpp_addr`, `/device/wifi`, `/device/inverter_ip`
- `/device/rfid` (GET/POST/DELETE), `/device/rfid/tag` (POST/PUT)
- `/device/savepersonalicepower/v2`, `/device/personalicepower/v2` (POST/GET/DELETE), `/device/personalicepower/all`
- `/stadistic/device`, `/stadistic/global/me`
- **Added in 1.3.0**: `/device/startcharge`, `/device/pausecharge`, `/device/intensity`, `/device/locked`, `/device/dynamic`, `/device/chargefvmode`, `/device/max_car_int`, `/device/min_car_int`, `/device/denka/max_power`, `GET /device/connected`

Numeric query parameters are posted as strings (as per the public documentation). Responses are coerced to native Python types whenever possible.

### Local
- `GET /RealTimeData` for telemetry (telemetry keys: ChargeState, ChargePower, VoltageInstallation, etc.)
- `GET /read/<keyword>` for values absent from `/RealTimeData` (`LogoLED`, `LightLED`). These are listed in `_READ_ONLY_KEYWORDS` and fetched concurrently after each `/RealTimeData` poll.
- `GET /write/KeyWord=Value` — every keyword from the Trydan Datamanager Modbus spec is now exposed: `Paused`, `Locked`, `Timer`, `Intensity`, `Dynamic`, `MinIntensity`, `MaxIntensity`, `PauseDynamic`, `LightLED` (1.3.0), `LogoLED`, `DynamicPowerMode`, `ContractedPower`, `VoltageInstallation`, `ChargeMode` (1.3.0). Writes are gated by the `WRITEABLE_KEYWORDS` whitelist in `local_api.py`.

`V2CLocalApiError` is raised on timeouts/HTTP errors and converted into `HomeAssistantError` at the entity/service layer.

**Notes on specific keywords:**
- `LogoLED` – LED intensity 0-100 %. Not present in `/RealTimeData`; read via `GET /read/LogoLED` and written via `/write/LogoLED=<v>`.
- `LightLED` *(1.3.0)* – LED intensity 0-100 %. Not present in `/RealTimeData`; read via `GET /read/LightLED` and written via `/write/LightLED=<v>`.
- `ChargeMode` *(1.3.0)* – `0` = monophasic, `1` = threephasic, `2` = mixed. Exposed as a select entity.

### Local refresh interval (1.3.0)
- Stored as an integer (seconds) in `entry.options[CONF_LOCAL_UPDATE_INTERVAL]`. Range 5-300 s, default 30 s.
- Resolved by `local_api._build_local_interval(entry.data, entry.options)`. Cloud-only entries (`fallback_ip` empty or `"0.0.0.0"`) always return `CLOUD_ONLY_UPDATE_INTERVAL` (120 s) and silently ignore the option.
- The `_async_options_updated` listener registered in `async_setup_entry` propagates the new value to every per-device local coordinator, so changes apply on the next refresh tick — no reload required.

### LAN-vs-cloud router (1.3.0)
`_async_route_local_or_cloud(hass, runtime_data, config_data, device_id, *, keyword, value, cloud_call)` is the building block for the new control services:

1. If `config_data` flags the device as cloud-only, the LAN attempt is skipped and `cloud_call` is awaited directly.
2. Otherwise it calls `async_write_keyword(...)` first. On success, the routine returns; the cloud coroutine is closed without being awaited.
3. If `async_write_keyword` raises `V2CLocalApiError` (SSRF guard, missing IP, HTTP error, timeout, etc.), the router falls back to awaiting `cloud_call`.
4. `V2CAuthError` / `V2CRequestError` raised during the cloud step are propagated as `ConfigEntryAuthFailed` / `HomeAssistantError`, respectively.
5. The chosen path is logged at DEBUG, which helps diagnose mis-configured devices in the field.

## 4. Entity Guidelines

- `V2CEntity.get_reported_value(*keys)` performs case-insensitive lookup on the cloud payload; helpers in `local_api.py` retrieve cached LAN data.
- `get_local_value(local_data, key)` in `local_api.py` performs a case-insensitive lookup on the local `RealTimeData` payload (exact match first, then `.lower()` scan). Use this whenever reading a key from local data instead of direct dict access.
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
- **Pairings failure resilience** – `_async_update_data` fetches pairings and device state in two independent steps. If `/pairings/me` fails (e.g. 403) and a `fallback_device_id` is configured, a synthetic pairing `{"deviceId": fallback_device_id, "ip": fallback_ip}` is used so `async_gather_devices_state` can still retrieve the device state via `/device/reported`.
- **Reauth / Reconfigure resilience** – the config flow only rejects a new API key on HTTP 401 (definitively invalid credentials). Any other cloud error (403, timeout, network down) causes the key to be saved immediately with a warning; the coordinator reconciles on the next refresh. This allows users to update an expired key even when the V2C Cloud is experiencing issues.
- `V2CLocalApiError` is mapped to `HomeAssistantError` so the UI reports issues without killing the event loop.
- Rate limiting applies exponential backoff (up to 3 retries). When capacity is exceeded the coordinator retains the cached payload and updates resume on the next scheduled interval.

## 7. Development Checklist

1. Update `strings.json`, translations (`translations/en.json`, `translations/it.json`) and documentation (`README.md`, `TECHNICAL_NOTES.md`, `CHANGELOG.md`).
2. Review coordinator intervals when adding new cloud polling to keep the daily budget intact.
3. Validate new local keywords against the official spreadsheet before exposing them in the UI.
4. Ensure logging remains at `debug` level for HTTP details; avoid excessive logging in the happy path.
5. Run `python -m compileall custom_components/v2c_cloud` before committing to catch syntax errors.
6. Run the automated test suite and confirm all tests pass:
   ```bash
   pip install -r requirements_test.txt
   python -m pytest tests/ -v
   ```

## 8. Dev Environment & MCP Tooling

### Devcontainer topology

The `.devcontainer.json` provisions a single-container dev environment based on `mcr.microsoft.com/devcontainers/python:3.14`. It is augmented to coexist with a companion Home Assistant container defined in `docker-compose.yml`:

- **`initializeCommand`** (runs on the host, before the dev container is built):
  ```
  docker network inspect v2c-dev >/dev/null 2>&1 || docker network create v2c-dev
  docker compose up -d homeassistant
  ```
  This guarantees the shared `v2c-dev` user-defined bridge network exists and the Home Assistant service (`hass_core_dev`, image `ghcr.io/home-assistant/home-assistant:stable`) is running before VS Code starts the dev container.
- **`runArgs: ["--network=v2c-dev"]`** attaches the dev container to that same network. Container DNS makes the HA service resolvable from inside as `http://homeassistant:8123` (via the network alias declared in `docker-compose.yml`).
- **`restart: "no"`** on the HA service is intentional: after a host reboot the container stays off until the next dev-container open (which re-runs `initializeCommand`) or an explicit `docker compose up -d homeassistant`. Cloud and LAN smoke testing is always developer-initiated.
- **Bind mounts**: `./config:/config` and `./custom_components:/config/custom_components`, so iterating on the integration is just edit-and-reload from the HA UI.
- **Port 8123** is published on the host so the same instance is reachable at `http://localhost:8123` from the browser.

### Tooling installed by `scripts/setup`

In addition to the Python dependency lockfiles, the post-create script installs:

- **Node.js LTS** (via the `ghcr.io/devcontainers/features/node:1` devcontainer feature) — provides `npx`, used by the `context7` and `memory` MCP servers in `.mcp.json`.
- **`mcp-proxy`** (`uv tool install --force git+https://github.com/sparfenyuk/mcp-proxy`) — the Streamable-HTTP/SSE bridge that fronts Home Assistant's `/api/mcp` endpoint for Claude Code consumption. Installed into the user's `uv` tool prefix (`~/.local/bin`, on `PATH` by default).
- A one-shot block appended to `~/.bashrc` that sources `.env.dev` with `set -a`, so every variable defined in that file is exported into every interactive shell.

### Local secrets — `.env.dev`

All dev secrets live in a single gitignored file at the repo root, `.env.dev`. The committed `.env.dev.example` documents every variable, where to obtain it, and the consumer:

| Variable | Consumer |
| --- | --- |
| `GH_TOKEN` | `gh` CLI inside the dev container. |
| `V2C_CLOUD_API_KEY` | `scripts/live_smoke_test.py`. |
| `V2C_LOCAL_IP` | `scripts/live_smoke_test.py`. |
| `HASS_TOKEN` | `mcp-proxy`, spawned by Claude Code through `.mcp.json` (`${HASS_TOKEN}` interpolation). |

The setup flow is intentionally one-shot:

```bash
cp .env.dev.example .env.dev
$EDITOR .env.dev   # fill in every value
# (re)open the dev container — `scripts/setup` wires the shell hook
```

After editing `.env.dev`, open a new shell or run `source ~/.bashrc` and restart Claude Code so it picks up the updated env (the MCP servers read `${HASS_TOKEN}` at spawn time). The legacy per-token files (`.gh-token`, `.v2c-token`, `.hass-token`) are superseded — `scripts/setup` cleans up the old `HASS_TOKEN`-only block from `~/.bashrc` if it exists, and the files themselves are no longer read by any tooling.

### `.mcp.json` MCP servers

| Server | Command | Notes |
| --- | --- | --- |
| `context7` | `npx -y @upstash/context7-mcp@latest` | Live library documentation; no auth required. |
| `memory` | `npx -y @modelcontextprotocol/server-memory` | Persistent knowledge graph; no auth required. |
| `Home Assistant` | `mcp-proxy --transport=streamablehttp --stateless http://homeassistant:8123/api/mcp` | `API_ACCESS_TOKEN` env interpolated from `${HASS_TOKEN}`. The DNS name `homeassistant` resolves via the `v2c-dev` bridge network. |

`HASS_TOKEN` is a **development-only** long-lived access token bound to the local dev container's HA instance. Like every other value in `.env.dev`, it is gitignored and local to the workstation.

## 9. Testing

### Automated tests

The repository includes a `pytest` suite under `tests/` that runs in CI on every push and pull request. It does **not** require a running Home Assistant instance or a physical charger.

| Module | What is tested |
| --- | --- |
| `test_helpers.py` | `_normalize_bool`, `_coerce_scalar`, `_extract_static_ip`, `V2CDeviceState` |
| `test_v2c_client.py` | `V2CClient` HTTP handling: 401/429/5xx errors, retry logic, rate-limit fallback, pairings cache, device commands |
| `test_local_api.py` | `get_local_value` case-insensitive lookup, `get_local_data` coordinator delegation |
| `test_cloud_endpoints_1_3.py` *(1.3.0)* | 10 new cloud client methods — URL, method, query params, response normalisation |
| `test_router_1_3.py` *(1.3.0)* | LAN-first router, cloud fallback on `V2CLocalApiError`, cloud-only skip |
| `test_options_flow_interval.py` *(1.3.0)* | `_build_local_interval`, bounds, update listener, cloud-only override |
| `test_manifest_hygiene.py` *(1.3.0)* | `manifest.json` schema, requirements parsing, `en/it/es/strings.json` key parity |

Run locally with:
```bash
python -m pytest tests/ -v
```

### Live smoke test (1.3.0)

`scripts/live_smoke_test.py` exercises every documented read endpoint, issues safe round-trip writes against a real Trydan plus the cloud, and verifies snapshot/restore. Required env: `V2C_CLOUD_API_KEY`, `V2C_LOCAL_IP`. Required flag: `--confirm-restore`.

Snapshots are written to `/tmp/v2c_snapshot_<timestamp>.json` before any mutation. Exit codes: `0` (all good), `1` (one or more assertions failed), `2` (invocation guard), `3` (restore phase failed — manual inspection required). This script is **never** run in CI.

### Manual integration testing

1. **API key flow** – invalid key should raise `ConfigEntryAuthFailed` and prompt the re-auth UI.
2. **Multiple devices** – verify the adaptive interval (check `coordinator.update_interval`).
3. **Local commands** – test start/pause charge, dynamic mode toggle, and intensity changes with the wallbox reachable on LAN.
4. **Cloud commands** – test RFID enable/disable, OCPP configuration, firmware update, timers, RFID services.
   **Local LED commands** – test Logo LED on/off with the charger reachable on LAN and with cloud offline; confirm `/read/LogoLED` returns `1`/`0` and the switch state updates accordingly.
5. **Failure scenarios** – simulate LAN unavailability and cloud 429/timeout responses to ensure fallbacks behave correctly.
6. **Statistics & events** – call `get_device_statistics` and confirm the `v2c_cloud_device_statistics` event carries the raw payload.
