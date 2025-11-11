# V2C Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=%24.v2c_cloud.total)

>  🎁 Thinking about a new wallbox? Grab a **10% discount** on Trydan or Trydan Pro at the official V2C store (https://v2charge.com/store/it/) with the promo code `INTEGRATIONTRYDAN10`

This custom integration links Home Assistant with the **V2C Cloud** platform. It combines the public cloud API with the wallbox local HTTP interface so that real-time data and frequent controls use the LAN endpoint while configuration tasks still rely on the official cloud endpoints. It is purpose-built for the official V2C Cloud APIs and the local APIs exposed by **V2C Trydan** chargers.

### Companion Octopus Energy integration

If you manage smart-charging slots through Intelligent Octopus, pair this project with my [Octopus Energy Italy integration](https://github.com/samuelebistoletti/HomeAssistant-OctopusEnergyIT). It exposes the Octopus APIs inside Home Assistant so that Intelligent Octopus can coordinate with V2C for advanced charging automations.

## Key Features

- **Guided onboarding** – the config flow only asks for your API key, validates it against `/pairings/me` and stores a deterministic unique ID for re-auth flows.
- **Cloud + LAN hybrid** – the integration polls `http://<device_ip>/RealTimeData` every 30 seconds for telemetry and rapid feedback, while the cloud API handles pairing discovery, advanced settings and statistics.
- **Local-first entities** – switches, selects and numbers that have a LAN keyword reuse the per-device realtime coordinator, so the UI reflects changes right after each LAN poll without waiting for the slower cloud refresh.
- **Optimistic smoothing** – cloud-only selects and numbers hold their requested value for ~20 s, eliminating UI “flapping” between command execution and the next poll.
- **Adaptive cloud budget** – the cloud coordinator automatically scales its interval with `ceil(devices * 86400 / 850)` seconds (never below 90 s) to respect the 1000 calls/day quota while leaving headroom for manual services.
- **Resilient polling** – cloud fetches revert to the default cadence immediately after connectivity issues, while LAN realtime requests retry with backoff and schedule follow-up refreshes after failed writes so entities recover automatically when Wi-Fi returns.
- **Comprehensive services** – Wi-Fi provisioning, timers, RFID lifecycle, photovoltaic profiles v2, scheduled charging helpers, OCPP/inverter settings and statistics exports, all implemented as Home Assistant services.
- **Automation-ready events** – data retrieval services (`scan_wifi_networks`, statistics, power profiles) emit events that contain the raw payload so automations can capture and store results.
- **Diagnostics aware** – the latest `RateLimit-*` headers are persisted in coordinator data and logs specify whether the LAN or cloud path was used, simplifying troubleshooting.

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

### Get your API key
1. Sign in to [https://v2c.cloud/home/user](https://v2c.cloud/home/user) with the account that owns the chargers.
2. Open the **User → API** panel (left navigation shown in the screenshot above).
3. Click **Get token** to generate the developer token, then copy the value shown in the field.
4. Store the token somewhere safe: it is the only secret you need for Home Assistant and it grants full access to your account.

### Complete the setup
1. In Home Assistant go to **Settings → Devices & Services → Add Integration** and pick **V2C Cloud**.
2. Paste the API token when prompted; the integration always talks to the official V2C endpoint (`https://v2c.cloud/kong/v2c_service`), so no other options are required.
3. Every pairing returned by `/pairings/me` is turned into a Home Assistant device with sensors, numbers, switches and services ready to use. Polling intervals, LAN/Cloud fallbacks and cached data are handled automatically after onboarding.

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
- OCPP (cloud `/device/ocpp`)

### Select Entities
- Installation type (cloud `/device/inst_type`)
- Slave device (cloud `/device/slave_type`)
- Language (cloud `/device/language`)
- Dynamic power mode (local `/write/DynamicPowerMode`, instant sync from realtime telemetry)

### Number Entities
- Current intensity (local `/write/Intensity`)
- Minimum intensity (local `/write/MinIntensity`)
- Maximum intensity (local `/write/MaxIntensity`)
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
| `v2c_cloud.set_installation_voltage` | Local `/write/VoltageInstallation` | Set the installation voltage through the local API. |
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
