# Changelog

## [1.0.0] - 2025-10-27

### Added
- Full asynchronous REST client covering every documented V2C Cloud endpoint (device commands, RFID management, timers, statistics, version lookup).
- Brand new Home Assistant config flow that authenticates with a V2C Cloud API key and validates available pairings.
- Dedicated Home Assistant entities: connection state, charging state, intensities, maximum power, RFID inventory, installation/slave/language/FV selectors, toggleable options, and command buttons.
- Home Assistant services for Wi-Fi provisioning, timer programming, RFID registration/update/removal, and firmware update requests.
- Local copy of the V2C Cloud Swagger specification in `docs/v2c_service.yaml` to ease future maintenance.

### Documentation
- Repository documentation (README, technical notes, translations, services) tailored to V2C Cloud onboarding and maintenance.
