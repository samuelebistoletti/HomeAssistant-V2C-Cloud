# Changelog

## [Unreleased]

### Changed
- Polling interval rescaled automatically to honour the 1000 calls/day limit, with pairing cache raised to 60 minutes and low-frequency refresh for RFID cards (6 h) and firmware version (12 h).
- Coordinated state gathering now relies on `/device/reported` to minimise traffic; charging state and connectivity are derived from the reported payload.
- README, technical notes and localisation files updated to describe adaptive refresh, rate-limit metadata and the removal of deprecated entities.
- Local switches, selects and numbers now subscribe to the realtime coordinator so their UI state updates right after each LAN poll, fixing the temporary "flap" that used to happen while waiting for cloud confirmation.
- Cloud-backed numbers and selects keep their optimistic state for a short period, preventing UI reverts between command execution and the next API refresh.
- The connection status binary sensor exposes human friendly `Connected` / `Disconnected` labels in every locale.

### Added
- Exposure of the latest `RateLimit-*` headers in coordinator data for diagnostics.
- Number entity for `VoltageInstallation`, letting the installation voltage be tuned through the local API.
- Pause Dynamic control switch exposed alongside the existing Dynamic mode toggle.

### Removed
- MAC address sensor and the unused `/device/mac` helper, as the endpoint is not part of the public OpenAPI specification.
- Realtime sensors duplicating configurable values (lock state, charging pause, intensities, installation voltage, dynamic state, pause dynamic, dynamic power mode) to avoid reporting the same data twice.

## [1.1.0] - 2025-11-15

### Added
- Supporto completo alla nuova documentazione V2C (https://api.v2charge.com/) con metodi dedicati per arresto/carica programmata, modalità terze parti, configurazioni OCPP e indirizzo inverter.
- Nuovi switch Home Assistant per modalità API di terze parti e attivazione OCPP.
- Servizi aggiuntivi per inserimento manuale tessere RFID, gestione profili di potenza v2, richieste statistiche ed eventi diagnostici (`v2c_cloud_wifi_scan`, `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`, `v2c_cloud_power_profiles`).

### Changed
- Servizio `program_timer` riallineato al payload `TimerDTO` (campi `start_time`, `end_time`, `active`).
- Aggiornate le mappature degli stati di carica e i dizionari di installazione/slave/lingua secondo la nuova specifica.
- README, note tecniche, servizi e traduzioni aggiornati per riflettere i nuovi endpoint e le nuove automazioni disponibili.

## [1.0.1] - 2025-10-27

### Added
- Full asynchronous REST client covering every documented V2C Cloud endpoint (device commands, RFID management, timers, statistics, version lookup).
- Brand new Home Assistant config flow that authenticates with a V2C Cloud API key and validates available pairings.
- Dedicated Home Assistant entities: connection state, charging state, intensities, maximum power, RFID inventory, installation/slave/language/FV selectors, toggleable options, and command buttons.
- Home Assistant services for Wi-Fi provisioning, timer programming, RFID registration/update/removal, and firmware update requests.
- Local copy of the V2C Cloud Swagger specification in `docs/v2c_service.yaml` to ease future maintenance.

### Documentation
- Repository documentation (README, technical notes, translations, services) tailored to V2C Cloud onboarding and maintenance.
