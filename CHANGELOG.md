# Changelog

All notable changes to this project will be documented in this file.

## [1.1.4] - 2026-03-19

### Security

- **Clear-text logging of sensitive data eliminated** – three CodeQL alerts (`py/clear-text-logging-sensitive-data`) resolved: `headers` and `body` removed from the HTTP debug log in `_request` (the `apikey` header was already masked but the dict comprehension still constituted a taint path); `params` masking made case-insensitive; `fallback_device_id` (derived from `entry.data`, which contains the API key) removed from startup warning messages in `__init__.py`; exception objects replaced with `type(err).__name__` to prevent accidental credential leakage via exception messages.

## [1.1.3] - 2026-03-19

### Security

- **SSRF guard now blocks link-local addresses** – on Python 3.11+ link-local IPs (`169.254.x.x`) have `is_private=True`, so the previous guard (`is_private AND NOT is_loopback`) incorrectly allowed them through. All three guard sites (`config_flow._probe_local_api`, `local_api.async_write_keyword`, `local_api._async_fetch_local_data`) now also reject `is_link_local` addresses.
- **API key / authorization headers masked in debug logs** – the `apikey` and `authorization` headers are now logged as `***` in all request debug output, preventing credential leakage in log files.

### Fixed

- **Startup failure when cloud is rate-limited in Cloud+LAN mode** – if the V2C Cloud returned HTTP 429 during initial coordinator startup, the integration raised `ConfigEntryNotReady` and retried indefinitely at a very short interval. It now treats the rate-limit error as a transient failure and backs off to the normal poll cadence (#6).
- **OCPP server URL, date fields and RFID tag data tightened** – malformed values are now rejected early with clear validation errors before reaching the API.
- **`_normalize_bool` synced with `coerce_bool`** – the API client's bool parser now recognises `"enabled"`/`"disabled"` tokens, matching the entity-layer helper and preventing silent mismatches on firmware variants that report boolean fields as strings.

### Changed

- **Parallel cloud fetch per device** – `_fetch_single_device_state` now fires the `reported`, `rfid` and `version` API calls concurrently via `asyncio.gather` instead of sequentially, reducing per-device cloud poll latency by up to 2 × on fast connections.
- **Rate-limit retry jitter** – backoff after a `429` response now includes a small random component to avoid simultaneous retries across multiple devices.
- **Type annotations cleaned up** – entity modules use `V2CClient` instead of `Any` for the client parameter; `device_info` now declares a `DeviceInfo` return type; `DataUpdateCoordinator` imports follow the `TYPE_CHECKING`-only pattern where the type is annotation-only.

### Testing

- **Test suite expanded to 350 tests** – ten new test modules cover all entity types (binary sensor, sensor, switch, number, select, button), config flow SSRF guard, local API and device-state gathering. The full suite runs without a live Home Assistant instance or charger.

## [1.1.2] - 2026-03-12

### CI

- **`actions/checkout` upgraded to v6** – bumped from v2 (in `hacs.yaml`, `hassfest.yaml`) and v4 (in `tests.yaml`, `security.yaml`, `codeql.yaml`, `tag-and-release.yaml`) to v6, resolving the Node.js 20 deprecation warning ahead of the June 2026 enforcement deadline.
- **`hacs/action` pinned to v22.5.0** – replaced the mutable `@main` floating tag with a commit-pinned reference (`d556e736...`) for supply-chain security.

## [1.1.1] - 2026-03-12

### Fixed
- **Re-auth / Reconfigure no longer blocked when cloud is unavailable** – if `/pairings/me` returns 403 or the V2C Cloud is unreachable during the reauth or reconfigure flow, the new API key is now accepted and saved immediately. The coordinator will validate connectivity on the next refresh cycle. Only a definitive HTTP 401 (invalid credentials) still blocks the flow.
- **Slave device select shows "MQTT" for type 11** – devices configured with MQTT-based energy monitoring (`slave_type = 11`) were previously stuck in unknown state because the value was missing from the options map.

## [1.1.0] - 2026-03-11

### Added
- **Timer switch** – new local switch entity that enables or disables the charger's built-in timer directly via the local HTTP API (`/write/Timer`), with instant state feedback from RealTimeData polling.
- **Fallback local IP during setup** – if the V2C Cloud API is unreachable when adding the integration, the config flow now offers a second step where you can enter the charger's local IP address. The integration operates entirely over the local LAN until the cloud comes back; once it does, the real cloud device list is used automatically without any manual intervention.
- **Local fallback IP option** – the fallback IP can also be set or updated at any time via the integration options panel (**Settings → Devices & Services → V2C Cloud → Configure**).
- **API key reconfiguration** – a new "Reconfigure" button is available in the integration panel (**Settings → Devices & Services → V2C Cloud → Reconfigure**). It lets you update the API key at any time without removing and re-adding the integration. The new key is validated before saving, and the integration reloads automatically on success.

### Changed
- **Logo LED** switch is now fully local: state is polled via `GET /read/LogoLED` (since `LogoLED` is absent from `/RealTimeData`) and writes use `/write/LogoLED=1` (on) or `/write/LogoLED=0` (off). The cloud `/device/logo_led` endpoint is no longer called, removing one daily API call and making the toggle work when the cloud is offline.
- **Cloud-offline resilience** – local entities (switches, numbers, `DynamicPowerMode` select) now derive their `available` state from the local coordinator instead of the cloud coordinator. When the cloud is unreachable, locally-controlled entities stay available and controllable as long as the charger is reachable on the LAN.
- **403 on `/pairings/me` no longer blocks the coordinator** – tokens that have permission for `/device/reported` but not `/pairings/me` no longer cause an endless startup failure. When `/pairings/me` returns an error, the coordinator builds a synthetic pairing from the configured `fallback_device_id` and proceeds to fetch device state normally.
- **Case-insensitive local key lookup** – all local entities now use a `get_local_value` helper that tries an exact match first and falls back to a case-insensitive scan, preventing entities from appearing unavailable if firmware reports keys in unexpected casing.
- The reauthentication flow now uses `_get_reauth_entry()` and `async_update_reload_and_abort()`, matching the modernized pattern used by the reconfigure flow.

### Fixed
- LogoLED switch state now reflects changes made from the V2C app without waiting for a manual refresh.
- LogoLED write value corrected: the device only accepts `1`/`0`, not `100`/`0` as older documentation implied.
- Removed unreachable `else: break` dead-code branch in the local RealTimeData retry loop.
- Removed unused `DeviceMetadata` dataclass and five unused constants (`DEFAULT_BASE_URL`, `RATE_LIMIT_DAILY`, `ATTR_KW`, `ATTR_VALUE`, `ATTR_PROFILE_MODE`).

### Removed
- **LightLED support** – experimental switch and all related API calls removed; the feature was not functional on production firmware.
- **`V2CClient.async_set_logo_led()`** – cloud Logo LED method removed; Logo LED is now fully managed via the local write API.

## [1.0.10] - 2026-02-04

### Fixed
- Moved the V2C Cloud portal URL in the config flow copy into translation placeholders to comply with hassfest validation.

### Documentation
- Added a link to the main projects site in both README files.

## [1.0.9] - 2025-11-15

### Fixed
- Trap `ConfigEntryNotReady` errors raised during the local RealTimeData coordinator bootstrap so forwarded platforms no longer log setup failures when a charger IP is temporarily unavailable; entities now stay loaded while the LAN poller retries in the background.

## [1.0.8] - 2025-11-11

### Documentation
- Highlighted the companion Octopus Energy Italy integration so users can pair Intelligent Octopus with V2C for smart-charging workflows.

## [1.0.7] - 2025-11-10

### Documentation
- Minor follow-up to the setup instructions to match the English wording now used by the V2C Cloud portal (menu and button labels).

## [1.0.6] - 2025-11-10

### Changed
- Locked the integration to the official V2C Cloud endpoint: the config flow, re-auth flow and stored entries no longer accept a custom base URL, so the onboarding form now only asks for the API key.
- Updated translations/strings to remove the unused Base URL field across the UI.

### Documentation
- Clarified the configuration instructions in both READMEs with step-by-step guidance (English UI labels included) on how to obtain the API token from the V2C Cloud portal.

## [1.0.5] - 2025-11-10

### Added
- `v2c_cloud.set_installation_voltage` service that writes to the local `/write/VoltageInstallation` endpoint so automations can adjust the parameter explicitly, now validated between 100 V and 450 V.

### Removed
- The "Installation voltage" number entity; use the new service action instead, consistent with other write-only operations such as RFID management.

## [1.0.4] - 2025-11-08

### Fixed
- Restore the cloud polling interval to the default cadence whenever authentication or network failures occur so entities resume refreshing quickly after long outages without needing a manual reload.
- Harden the LAN realtime telemetry by retrying `/RealTimeData` up to three times with progressive backoff before giving up, logging recoveries once the wallbox comes back online.
- Schedule an automatic LAN refresh a few seconds after write timeouts/HTTP errors so commands eventually reconcile with the UI as soon as Wi-Fi connectivity is restored.

## [1.0.3] - 2025-11-07

### Fixed
- Sync the OCPP, logo LED and RFID reader toggles immediately after commands by caching the new value, skipping the instant refresh and scheduling a delayed poll so the UI no longer flips back while the cloud API propagates the change.

### Removed
- Dropped the per-entity extra state attributes to reduce clutter now that diagnostics can rely on logs and events.

## [1.0.2] - 2025-11-07

### Fixed
- Constrained the “Contracted power” number entity to 1–22 kW with 0.5 kW increments for a more realistic slider range.

### Removed
- Dropped the redundant “Contracted power” sensor; continue to use the corresponding number entity which already exposes the same data with write support.

## [1.0.1] - 2025-11-07

### Added
- Dedicated Material Design icons for all config numbers, select entities and the V2C Cloud connection sensor to improve clarity in the Home Assistant UI.

## [1.0.0] - 2025-11-06

First public release of the V2C Cloud integration for Home Assistant.

### Added
- **Config flow with API-key validation** – authenticates against `/pairings/me`, caches the initial pairings and stores a deterministic unique ID for future re-auth flows.
- **Hybrid cloud/LAN architecture** – asynchronous client for every documented V2C Cloud endpoint plus LAN helpers for `/RealTimeData` and `/write/<Keyword>=<Value>`, including retry/backoff and rate-limit handling.
- **Adaptive polling** – cloud coordinator that automatically scales to the number of chargers with a minimum interval of 90 s, caching pairings for 60 minutes, refreshing RFID cards every 6 h and firmware versions every 12 h.
- **Realtime local telemetry** – per-device coordinators that poll `/RealTimeData` every 30 s and expose sensors for identifier, firmware version, charge status, timer state, power/energy metrics, grid voltage, Wi-Fi diagnostics and device error codes (with localized labels).
- **Home Assistant entities** – connection binary sensor, local-first switches (Dynamic, PauseDynamic, Locked, Pause charge, Logo LED, RFID reader, OCPP), selects (installation type, slave type, language, dynamic power mode), numbers (intensity, min/max intensity, contracted power, installation voltage) and buttons (reboot, trigger update) with optimistic UI smoothing.
- **Service surface** – Wi-Fi credentials, timer programming, RFID lifecycle (register, add, update, delete), scheduled charging helpers (stop/start via kWh or minutes), OCPP and inverter configuration, firmware update trigger, photovoltaic power profile management (create, update, get, list, delete) and statistics retrieval for devices and the global account.
- **Automation events** – data retrieval services fire `v2c_cloud_wifi_scan`, `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics` and `v2c_cloud_power_profiles` events containing the raw payload to power custom automations.
- **Diagnostics & tooling** – rate-limit headers stored in coordinator data, comprehensive documentation (README, release notes, technical notes) and translation files for UI strings.
