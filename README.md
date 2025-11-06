# V2C Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

This custom integration links Home Assistant with the **V2C Cloud** platform. It combines the public cloud API with the wallbox local HTTP interface so that real-time data and frequent controls use the LAN endpoint while long-lived configuration keeps relying on the official cloud endpoints.

> ℹ️ The integration is built specifically for V2C Cloud following Home Assistant best practices (config flow, coordinators, translations, services, diagnostics).

## Key Features

- **API key authentication** – the setup flow only requires the API key generated from your V2C Cloud account.
- **Hybrid architecture** – telemetry is polled every 30 seconds from `http://<device_ip>/RealTimeData`, while the cloud API is used for pairing discovery, status verification and configuration operations that are not exposed locally.
- **Adaptive cloud polling** – the cloud coordinator (mainly `/device/reported`) adjusts its interval automatically so the account stays below the 1000 requests/day limit. With one device the refresh is 120 s; the minimum allowed interval is 90 s.
- **Fast local controls** – dynamic mode, charger lock, intensity sliders and start/pause commands write directly to `http://<device_ip>/write/KeyWord=Value`, avoiding round-trips through the cloud.
- **Comprehensive Home Assistant services** – Wi-Fi management, timers, RFID provisioning, photovoltaic profiles v2, OCPP/inverter configuration and statistics retrieval, each publishing an automation-friendly event.
- **Diagnostics-friendly** – rate limit headers are stored in coordinator data and every command logs the originating endpoint (cloud or LAN) to help troubleshooting.

## Requirements

- A V2C Cloud account with at least one wallbox paired and an API key generated from [https://v2c.cloud/home/user](https://v2c.cloud/home/user).
- The wallbox must be reachable on the local network (open the HTTP port used by `/RealTimeData` and `/write/...`).
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

- The API key is mandatory; an alternate base URL can be provided for staging environments.
- Each pairing returned by `/pairings/me` becomes a Home Assistant device with entities grouped by use case.
- Cloud polling adapts to the number of wallboxes using `ceil(count * 86400 / 850)` seconds (never below 90 s). RFID data is refreshed every 6 hours, firmware version every 12 hours, pairing information every 60 minutes.
- Entities driven by the local API refresh themselves independently from the cloud cycle, preventing state oscillations after manual actions.

## Entity Overview

### Sensors (polled locally every 30 s)
- Device identifier, firmware version
- Charge state, ready state, timer status, lock status, pause state, dynamic mode state
- Charge power, charge energy, charge time, house power, FV power, battery power, contracted power
- Intensity, minimum intensity, maximum intensity, pause dynamic, dynamic power mode
- Installation voltage, Wi-Fi SSID, Wi-Fi IP address, Wi-Fi signal strength
- Slave error code

### Binary Sensors
- Connection status (cloud `/device/reported`)

### Switches
- Dynamic mode (local `/write/Dynamic`)
- Charger lock (local `/write/Locked`)
- Charging pause (local `/write/Paused`)
- Logo LED (cloud `/device/logo_led`)
- RFID reader (cloud `/device/set_rfid`)
- OCPP enabled (cloud `/device/ocpp`)

### Select Entities
- Installation type (cloud `/device/inst_type`)
- Slave device (cloud `/device/slave_type`)
- Language (cloud `/device/language`)
- Dynamic power mode (local `/write/DynamicPowerMode`)

### Number Entities
- Current intensity (local `/write/Intensity`)
- Minimum intensity (local `/write/MinIntensity`)
- Maximum intensity (local `/write/MaxIntensity`)
- Contracted power (local `/write/ContractedPower`)
- Maximum power (cloud `/device/maxpower`)

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

## Logging & Diagnostics

To enable detailed logs:

```yaml
logger:
  logs:
    custom_components.v2c_cloud: debug
```

## License

Distributed under the MIT License. See the [LICENSE](LICENSE) file for details.
