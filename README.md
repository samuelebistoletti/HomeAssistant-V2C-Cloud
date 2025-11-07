# V2C Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=%24.v2c_cloud.total)

This custom integration links Home Assistant with the **V2C Cloud** platform. It combines the public cloud API with the wallbox local HTTP interface so that real-time data and frequent controls use the LAN endpoint while configuration tasks still rely on the official cloud endpoints. It is purpose-built for the official V2C Cloud APIs and the local APIs exposed by **V2C Trydan** chargers; find more about Trydan and V2C at https://v2charge.com/it/trydan/.

> Info: The integration is built specifically for V2C Cloud following Home Assistant best practices (config flow, coordinators, translations, services, diagnostics).

## Key Features

- **Guided onboarding** – the config flow only asks for your API key, validates it against `/pairings/me` and stores a deterministic unique ID for re-auth flows.
- **Cloud + LAN hybrid** – the integration polls `http://<device_ip>/RealTimeData` every 30 seconds for telemetry and rapid feedback, while the cloud API handles pairing discovery, advanced settings and statistics.
- **Local-first entities** – switches, selects and numbers that have a LAN keyword reuse the per-device realtime coordinator, so the UI reflects changes right after each LAN poll without waiting for the slower cloud refresh.
- **Optimistic smoothing** – cloud-only selects and numbers hold their requested value for ~20 s, eliminating UI “flapping” between command execution and the next poll.
- **Adaptive cloud budget** – the cloud coordinator automatically scales its interval with `ceil(devices * 86400 / 850)` seconds (never below 90 s) to respect the 1000 calls/day quota while leaving headroom for manual services.
- **Comprehensive services** – Wi-Fi provisioning, timers, RFID lifecycle, photovoltaic profiles v2, scheduled charging helpers, OCPP/inverter settings and statistics exports, all implemented as Home Assistant services.
- **Automation-ready events** – data retrieval services (`scan_wifi_networks`, statistics, power profiles) emit events that contain the raw payload so automations can capture and store results.
- **Diagnostics aware** – the latest `RateLimit-*` headers are persisted in coordinator data, logs specify whether the LAN or cloud path was used, and every entity exposes the raw value in its extra state attributes for troubleshooting.

## Requirements

- A V2C Cloud account with at least one wallbox paired and an API key generated from [https://v2c.cloud/home/user](https://v2c.cloud/home/user).
- The wallbox must be reachable on the local network (open the HTTP port used by `/RealTimeData` and `/write/...`). Ideally reserve a static IP or DHCP lease so the integration can keep using LAN features; the integration will fall back to the last reported IP or the pairing metadata when static data is missing.
- Home Assistant 2023.12 or newer.
- Internet access towards `https://v2c.cloud/kong/v2c_service` for cloud calls.

## Installation

### HACS (recommended)
1. Add this repository to HACS as a *Custom repository* (category **Integration**).
2. Search for **V2C Cloud** and install the integration.
3. Restart Home Assistant when prompted.
4. Go to **Settings → Devices & Services → Add Integration**, choose **V2C Cloud** and enter your API key.

### Manual installation
1. Copy the `custom_components/v2c_cloud` folder into the `custom_components` directory of your Home Assistant instance.
2. Restart Home Assistant.
3. Add the **V2C Cloud** integration from **Settings → Devices & Services**.

## Configuration

- The API key is mandatory; an alternate base URL can be provided when advanced options are enabled.
- Each pairing returned by `/pairings/me` becomes a Home Assistant device with entities grouped by use case.
- Cloud polling adapts to the active device count using `ceil(devices * 86400 / 850)` seconds (never below 90 s). RFID cards refresh every 6 hours, firmware version every 12 hours and the pairing cache lives for 60 minutes.
- Entities that rely on the LAN API subscribe to their per-device realtime coordinator, so they initialise with the latest LAN payload after startup and remain optimistic only until the next LAN refresh.
- The integration automatically re-uses stored pairing data if the cloud API temporarily rate-limits requests and supports Home Assistant’s re-auth flow when the API key expires.

## Entity Overview

### Sensors (polled locally every 30 s)
- Device identifier and firmware version
- Charge state (localized), ready state and timer flag
- Charge power (W), energy delivered (kWh) and elapsed charge time (s)
- House, photovoltaic and battery power (W)
- Grid voltage (`VoltageInstallation`, V)
- Wi-Fi SSID, IP address and signal quality indicator
- Slave error code (localized)

### Binary Sensors
- Connection status (cloud `/device/reported`, exposes "Connected" / "Disconnected")

### Switches
- Dynamic mode (local `/write/Dynamic`)
- Pause dynamic control (local `/write/PauseDynamic`)
- Charger lock (local `/write/Locked`)
- Charging pause (local `/write/Paused`)
- Logo LED (cloud `/device/logo_led`)
- RFID reader (cloud `/device/set_rfid`)
- OCPP enabled (cloud `/device/ocpp`)

### Select Entities
- Installation type (cloud `/device/inst_type`)
- Slave device (cloud `/device/slave_type`)
- Language (cloud `/device/language`)
- Dynamic power mode (local `/write/DynamicPowerMode`, instant sync from realtime telemetry)

### Number Entities
- Current intensity (local `/write/Intensity`)
- Minimum intensity (local `/write/MinIntensity`)
- Maximum intensity (local `/write/MaxIntensity`)
- Installation voltage (local `/write/VoltageInstallation`)
- Contracted power (local `/write/ContractedPower`, auto-converted between watts and kW)

### Buttons
- Reboot charger (cloud `/device/reboot`)
- Trigger firmware update (cloud `/device/update`)

## Available Services

### Configuration & Networking
| Service | Endpoint | Description |
| --- | --- | --- |
| `v2c_cloud.set_wifi_credentials` | `/device/wifi` | Update SSID and password. |
| `v2c_cloud.program_timer` | `/device/timer` | Configure start/end time and active flag for a timer slot. |
| `v2c_cloud.set_ocpp_enabled` | `/device/ocpp` | Enable or disable OCPP connectivity. |
| `v2c_cloud.set_ocpp_id` | `/device/ocpp_id` | Set the OCPP charge point identifier. |
| `v2c_cloud.set_ocpp_address` | `/device/ocpp_addr` | Configure the central OCPP server URL. |
| `v2c_cloud.set_inverter_ip` | `/device/inverter_ip` | Configure the connected inverter IP address. |
| `v2c_cloud.trigger_update` | `/device/update` | Request a firmware update. |

### RFID Management
| Service | Endpoint | Description |
| --- | --- | --- |
| `v2c_cloud.register_rfid` | `/device/rfid` (POST) | Put the charger in learning mode to register the next card. |
| `v2c_cloud.add_rfid_card` | `/device/rfid/tag` (POST) | Register a card providing UID and label. |
| `v2c_cloud.update_rfid_tag` | `/device/rfid/tag` (PUT) | Rename an existing card. |
| `v2c_cloud.delete_rfid` | `/device/rfid` (DELETE) | Remove a card by UID. |

### Scheduled Charging
| Service | Endpoint | Description |
| --- | --- | --- |
| `v2c_cloud.set_charge_stop_energy` | `/device/charger_until_energy` | Stop automatically after delivering the target kWh. |
| `v2c_cloud.set_charge_stop_minutes` | `/device/charger_until_minutes` | Stop after the specified duration. |
| `v2c_cloud.start_charge_for_energy` | `/device/startchargekw` | Start a charge that stops at the energy target. |
| `v2c_cloud.start_charge_for_minutes` | `/device/startchargeminutes` | Start a charge that stops after the desired time. |

### Photovoltaic Power Profiles v2
| Service | Endpoint | Description |
| --- | --- | --- |
| `v2c_cloud.create_power_profile` | `/device/savepersonalicepower/v2` | Create a personalised power profile (JSON payload). |
| `v2c_cloud.update_power_profile` | `/device/personalicepower/v2` (POST) | Update an existing profile. |
| `v2c_cloud.get_power_profile` | `/device/personalicepower/v2` (GET) | Retrieve a profile by `updateAt`. |
| `v2c_cloud.delete_power_profile` | `/device/personalicepower/v2` (DELETE) | Delete a profile by name and timestamp. |
| `v2c_cloud.list_power_profiles` | `/device/personalicepower/all` | List all personalised profiles. |

### Statistics & Diagnostics
| Service | Endpoint | Description |
| --- | --- | --- |
| `v2c_cloud.get_device_statistics` | `/stadistic/device` | Fetch device statistics (optional date filters). |
| `v2c_cloud.get_global_statistics` | `/stadistic/global/me` | Fetch aggregated account statistics. |
| `v2c_cloud.scan_wifi_networks` | `/device/wifilist` | Request a Wi-Fi scan; results are emitted via `v2c_cloud_wifi_scan`. |

Each data-oriented service also fires an event (`v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`, `v2c_cloud_power_profiles`) containing the raw payload so automations can store or relay the information.

## Home Assistant Events

- `v2c_cloud_wifi_scan` – triggered by `scan_wifi_networks`; payload contains `device_id` and the list of `networks`.
- `v2c_cloud_power_profiles` – used by `list_power_profiles` and `get_power_profile`; payload carries the `device_id` plus either a `profiles` list or a single `profile` and its `timestamp`.
- `v2c_cloud_device_statistics` – emitted by `get_device_statistics`; includes `device_id`, optional `date_start` / `date_end` and the `statistics` list.
- `v2c_cloud_global_statistics` – emitted by `get_global_statistics`; includes the global `statistics` list plus the requested date range.

## Logging & Diagnostics

To enable detailed logs:

```yaml
logger:
  logs:
    custom_components.v2c_cloud: debug
```

## License

Distributed under the MIT License. See the [LICENSE](LICENSE) file for details.
