2024-06-01 — Version 1.0.0

First public release of the V2C Cloud Home Assistant integration.

### Highlights
- Guided config flow that validates the API key against `/pairings/me` and caches discovered chargers for the first refresh.
- Hybrid data model that merges the cloud API with the LAN realtime endpoint (`/RealTimeData`) so entities react to local changes within 30 seconds while advanced settings still go through the official cloud endpoints.
- Adaptive polling strategy that keeps daily usage under the 1000 calls/day quota (minimum interval 90 s) and preserves the most recent data when the service rate-limits requests.
- Rich Home Assistant service surface for Wi-Fi, timers, RFID lifecycle, scheduled charging helpers, OCPP and inverter settings, photovoltaic profiles v2, firmware update requests and statistics exports.

### Entities
- Local sensors for identifier, firmware version, charge state, timer status, power/energy metrics, grid voltage and Wi-Fi diagnostics, each exposing the raw payload alongside processed values.
- Binary sensor that reflects the charger connectivity derived from the cloud payload.
- Switches, numbers and selects wired to the LAN keywords where possible (Dynamic, PauseDynamic, Locked, Paused, Intensity, ContractedPower, DynamicPowerMode, etc.) with optimistic state smoothing.
- Buttons for charger reboot and firmware update triggers.

### Automations & Diagnostics
- Data-retrieval services emit Home Assistant events (`v2c_cloud_wifi_scan`, `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`, `v2c_cloud_power_profiles`) containing the raw payload for custom automations.
- Latest `RateLimit-*` headers are stored in coordinator data for troubleshooting, and extra state attributes surface the unprocessed values received from the device.
