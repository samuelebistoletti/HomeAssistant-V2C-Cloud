# Changelog

All notable changes to this project will be documented in this file.

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
