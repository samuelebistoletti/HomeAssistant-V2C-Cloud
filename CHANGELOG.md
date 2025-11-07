# Changelog

All notable changes to this project will be documented in this file.

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
