Unreleased

- Adaptive polling strategy tuned to the 1000 calls/day quota (pairing cache 60 minutes, RFID refresh every 6 h, firmware version every 12 h) with rate limit metadata exposed in diagnostics.
- Simplified state gathering around `/device/reported`, deriving charging state and connectivity without extra calls.
- Removed the legacy MAC address sensor because `/device/mac` is not part of the published OpenAPI specification.

2025-11-15 - Version 1.1.0

- Alignment with the November 2025 V2C Third-party API refresh (https://api.v2charge.com/).
- Added on-demand commands for scheduled charging (energy/minutes) and advanced configuration (third-party mode, OCPP, Denka max power, inverter IP).
- Exposed full v2 personalised power profile management and published diagnostic results via Home Assistant events.
- Extended Home Assistant services, translations, and documentation accordingly.

2025-10-27 - Initial release

Launch version of the V2C Cloud Home Assistant integration with API-key onboarding, coordinator-based polling, entities for status/configuration, and services for Wi-Fi, timers, RFID, and firmware commands.
