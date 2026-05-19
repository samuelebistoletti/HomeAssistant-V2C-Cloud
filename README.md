# V2C Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=%24.v2c_cloud.total)
[![Tests](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/tests.yaml/badge.svg)](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/tests.yaml)
[![Security](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/security.yaml/badge.svg)](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/security.yaml)
[![CodeQL](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/codeql.yaml/badge.svg)](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud/actions/workflows/codeql.yaml)

>  🎁 Thinking about a new wallbox? Grab a **10% discount** on Trydan or Trydan Pro at the official V2C store (https://v2charge.com/store/it/) with the promo code `INTEGRATIONTRYDAN10`

This custom integration links Home Assistant with the **V2C Cloud** platform. It combines the public cloud API with the wallbox local HTTP interface so that real-time data and frequent controls use the LAN endpoint while configuration tasks still rely on the official cloud endpoints. It is purpose-built for the official V2C Cloud APIs and the local APIs exposed by **V2C Trydan** chargers.

### Companion Octopus Energy integration

If you manage smart-charging slots through Intelligent Octopus, pair this project with my [Octopus Energy Italy integration](https://github.com/samuelebistoletti/HomeAssistant-OctopusEnergyIT). It exposes the Octopus APIs inside Home Assistant so that Intelligent Octopus can coordinate with V2C for advanced charging automations.

More of my Home Assistant projects live at https://samuele.bistoletti.me/.

## Key Features

- **Guided onboarding** – the config flow only asks for your API key, validates it against `/pairings/me` and stores a deterministic unique ID for re-auth flows.
- **API key management** – the API key can be updated at any time via the **Reconfigure** button in the integration panel, without removing and re-adding the integration.
- **Cloud + LAN hybrid** – the integration polls `http://<device_ip>/RealTimeData` every 30 seconds by default (configurable 5-300 s per integration via Reconfigure) for telemetry and rapid feedback, while the cloud API handles pairing discovery, advanced settings and statistics.
- **Configurable LAN refresh** *(new in 1.3.0)* – the LAN poll interval can be tuned per integration through the Reconfigure dialog (`Local refresh interval (seconds)`, range 5-300 s, default 30 s). Cloud-only (4G) chargers keep the adaptive cloud cadence and ignore this setting; LAN devices apply changes live without an integration reload.
- **Local-first entities** – switches, selects and numbers that have a LAN keyword reuse the per-device realtime coordinator, so the UI reflects changes right after each LAN poll without waiting for the slower cloud refresh.
- **Smart LAN-vs-cloud router** *(new in 1.3.0)* – control commands shared between LAN (`/write/`) and cloud (`/device/*`) automatically pick the LAN path when available and transparently fall back to the cloud endpoint when LAN is unreachable or the device is cloud-only. This covers start/pause charge, intensity, locked, dynamic.
- **Optimistic smoothing** – cloud-only selects and numbers hold their requested value for ~20 s, eliminating UI "flapping" between command execution and the next poll.
- **Adaptive cloud budget** – the cloud coordinator automatically scales its interval with `ceil(devices * 86400 / 850)` seconds (never below 90 s) to respect the 1000 calls/day quota while leaving headroom for manual services.
- **Resilient polling** – cloud fetches revert to the default cadence immediately after connectivity issues, while LAN realtime requests retry with backoff and schedule follow-up refreshes after failed writes so entities recover automatically when Wi-Fi returns.
- **Full endpoint coverage** *(complete in 1.3.0)* – every endpoint in the [official V2C Cloud OpenAPI spec](https://api.v2charge.com) and every writable register from the [Trydan Datamanager Modbus document](https://v2charge.com/) is exposed as a Home Assistant entity or service.
- **Comprehensive services** – Wi-Fi provisioning, timers, RFID lifecycle, photovoltaic profiles v2, scheduled charging helpers, OCPP/inverter settings, charge control, intensity tuning, photovoltaic modes, Denka power limits, and statistics exports, all as Home Assistant services.
- **Automation-ready events** – data retrieval services (`scan_wifi_networks`, statistics, power profiles, connected status) emit events that contain the raw payload so automations can capture and store results.
- **Diagnostics aware** – the latest `RateLimit-*` headers are persisted in coordinator data and logs specify whether the LAN or cloud path was used, simplifying troubleshooting.

## Requirements

- A V2C Cloud account with at least one wallbox paired and an API key generated from [https://v2c.cloud/home/user](https://v2c.cloud/home/user).
- The wallbox must be reachable on the local network (open the HTTP port used by `/RealTimeData` and `/write/...`). Ideally reserve a static IP or DHCP lease so the integration can keep using LAN features; the integration will fall back to the last reported IP or the pairing metadata when static data is missing.
- Home Assistant **2025.4.0** or newer.
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

### Change your API key
If you need to rotate or replace the API key after the initial setup, go to **Settings → Devices & Services → V2C Cloud** and click **Reconfigure**. Enter the new key, and the integration will validate it and reload automatically. No entities or device history are lost.

### Tune the local polling interval *(new in 1.3.0)*
LAN-connected chargers ship with a 30-second poll cadence. Open **Settings → Devices & Services → V2C Cloud → Configure** to change it:

- **Range:** 5–300 s (the field validates the bounds).
- **Default:** 30 s.
- **Recommended floor:** 15 s. Below that, slow Wi-Fi or unstable LANs may saturate and you will see retry warnings in the log.
- **Cloud-only (4G) chargers** ignore this setting; they use the adaptive cloud cadence (≥ 90 s).

Changes are applied to all per-device local coordinators immediately; no integration reload is required.

## Entity Overview

### Sensors (polled locally — interval configurable, default 30 s)
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
- Timer (local `/write/Timer`)
- Logo LED on/off (local `/write/LogoLED`)
- RFID reader (cloud `/device/set_rfid`)
- OCPP (cloud `/device/ocpp`)

### Select Entities
- Installation type (cloud `/device/inst_type`)
- Slave device (cloud `/device/slave_type`)
- Language (cloud `/device/language`)
- Dynamic power mode (local `/write/DynamicPowerMode`, instant sync from realtime telemetry)
- **Charge mode** *(new in 1.3.0)* — monophasic / threephasic / mixed (local `/write/ChargeMode`)

### Number Entities
- Current intensity (local `/write/Intensity`)
- Minimum intensity (local `/write/MinIntensity`)
- Maximum intensity (local `/write/MaxIntensity`)
- Contracted power (local `/write/ContractedPower`, auto-converted between watts and kW)
- **Light LED intensity** *(new in 1.3.0)* — 0-100 % (local `/write/LightLED`)

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
| `v2c_cloud.get_connected_status` *(1.3.0)* | `/device/connected` | Check the cloud-side online status; result emitted via `v2c_cloud_connected_status`. |

### Charge Control & Intensity *(new in 1.3.0)*
| Service | Routing | Description |
| --- | --- | --- |
| `v2c_cloud.start_charge` | LAN-first → cloud | Start or resume the charging session. LAN uses `Paused=0`; cloud uses `/device/startcharge`. |
| `v2c_cloud.pause_charge` | LAN-first → cloud | Pause the active session. LAN uses `Paused=1`; cloud uses `/device/pausecharge`. |
| `v2c_cloud.set_charge_intensity` | LAN-first → cloud | Set the max charging current (A). LAN writes `Intensity`; cloud uses `/device/intensity`. |
| `v2c_cloud.set_locked` | LAN-first → cloud | Lock or unlock the charger. LAN writes `Locked`; cloud uses `/device/locked`. |
| `v2c_cloud.set_dynamic` | LAN-first → cloud | Toggle dynamic power control. LAN writes `Dynamic`; cloud uses `/device/dynamic`. |
| `v2c_cloud.set_fv_mode` | Cloud only | Configure photovoltaic mode (0=PV+min, 1=PV exclusive, 2=Max). `/device/chargefvmode`. |
| `v2c_cloud.set_max_car_intensity` | Cloud only | Vehicle max intensity. `/device/max_car_int`. |
| `v2c_cloud.set_min_car_intensity` | Cloud only | Vehicle min intensity. `/device/min_car_int`. |
| `v2c_cloud.set_denka_max_power` | Cloud only | Denka inverter max power (W). `/device/denka/max_power`. |

Each data-oriented service also fires an event (`v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`, `v2c_cloud_power_profiles`, `v2c_cloud_connected_status`) containing the raw payload so automations can store or relay the information.

## Home Assistant Events

- `v2c_cloud_wifi_scan` – triggered by `scan_wifi_networks`; payload contains `device_id` and the list of `networks`.
- `v2c_cloud_power_profiles` – used by `list_power_profiles` and `get_power_profile`; payload carries the `device_id` plus either a `profiles` list or a single `profile` and its `timestamp`.
- `v2c_cloud_device_statistics` – emitted by `get_device_statistics`; includes `device_id`, optional `date_start` / `date_end` and the `statistics` list.
- `v2c_cloud_global_statistics` – emitted by `get_global_statistics`; includes the global `statistics` list plus the requested date range.
- `v2c_cloud_connected_status` *(1.3.0)* – emitted by `get_connected_status`; payload contains `device_id` and the boolean `connected` value.

## API Coverage *(complete in 1.3.0)*

| Surface | Coverage |
| --- | --- |
| **V2C Cloud OpenAPI** | 32 documented endpoints implemented as cloud client methods. `start_charge`, `pause_charge`, `intensity`, `locked`, `dynamic`, `chargefvmode`, `max_car_int`, `min_car_int`, `denka/max_power`, `GET /device/connected` were added in 1.3.0. |
| **Trydan local API** (`/RealTimeData`, `/read/`, `/write/`) | Every documented writeable register is exposed: `Paused`, `Locked`, `Timer`, `Intensity`, `Dynamic`, `MinIntensity`, `MaxIntensity`, `PauseDynamic`, `LightLED` (1.3.0), `LogoLED`, `DynamicPowerMode`, `ContractedPower`, `VoltageInstallation`, `ChargeMode` (1.3.0). |
| **Webhooks** (`startCharge`, `endCharge`) | **Out of scope** in 1.3.0. The cloud documentation does not yet define a signature/auth mechanism for inbound webhook verification — deferred to a future minor release once we can authenticate the incoming requests safely. |

## Development & Testing

### Running the test suite

```bash
pip install -r requirements_test.txt
python -m pytest tests/ -v
```

The suite (~386 tests as of 1.3.0) runs entirely without a live Home Assistant instance or a real charger. It covers:

- **HTTP client** – cloud API calls, authentication, retry and rate-limit handling, pairings cache
- **Device state gathering** – `async_gather_devices_state`, per-device fetch parallelism, fallback to previous data on transient errors
- **Entity helpers** – `coerce_bool`, device state resolution, `_OptimisticHoldMixin` (hold window, expiry, match-clears-hold)
- **Binary sensor** – `V2CConnectedBinarySensor.is_on` for all truthy/falsy types plus `reported` fallback
- **Sensors** – conversion helpers (`_as_float`, `_as_int`, `_as_str`, `_as_flag`), `_localize_state` (all keys, multi-language), `V2CLocalRealtimeSensor.native_value`
- **Switches** – `V2CBooleanSwitch` state resolution (local / reported / optimistic), availability, icon sync
- **Numbers** – `V2CNumberEntity` native value (local vs reported), optimistic hold, `_values_match` tolerance, availability
- **Selects** – `V2CEnumSelect` value resolution, `current_option`, optimistic hold, localised options
- **Buttons** – `V2CButton.async_press` success, no-refresh mode, `V2CError` / `V2CLocalApiError` → `HomeAssistantError`
- **Config flow** – `_probe_local_api` SSRF guard, valid/invalid IPs, HTTP error and malformed JSON handling
- **Local API** – SSRF guard in `async_write_keyword` and `_async_fetch_local_data`, boundary address parametrisation
- **Cloud endpoints 1.3.0** – every new client method asserts URL/method/query parameters (`tests/test_cloud_endpoints_1_3.py`)
- **LAN-vs-cloud router** – fallback path, cloud-only skip, LAN failure paths (`tests/test_router_1_3.py`)
- **Options flow** – `local_update_interval` validation, default resolution, cloud-only override (`tests/test_options_flow_interval.py`)
- **Manifest & translation hygiene** – `min_ha_version`, version semver, `en/it/es` key parity (`tests/test_manifest_hygiene.py`)

### Live smoke test (not run in CI)

A separate `scripts/live_smoke_test.py` exercises every read endpoint and issues safe round-trip writes against a real Trydan plus the V2C Cloud, then verifies snapshot/restore. **Never** runs in CI.

```bash
V2C_CLOUD_API_KEY=<your_test_key> V2C_LOCAL_IP=<your_device_ip> \
  python scripts/live_smoke_test.py --confirm-restore
```

The `--confirm-restore` flag is mandatory — without it the script aborts before any HTTP request. Exit codes: 0 (all good), 1 (assertion failed, see `/tmp/v2c_snapshot_*.json`), 2 (invocation guard), 3 (restore failed, manual inspection required).

### CI / CD

Every push and pull request to `main` runs:

| Workflow | What it checks |
| --- | --- |
| **Tests** | `pytest` suite |
| **Security** | Bandit SAST · pip-audit dependency audit · gitleaks secret scan |
| **CodeQL** | GitHub CodeQL static analysis for Python and Actions |
| **HACS** | HACS integration validation |
| **hassfest** | Home Assistant manifest validation |

The **Tag and Release** workflow only creates a tag and GitHub release after both the Tests and Security jobs pass.

## Logging & Diagnostics

To enable detailed logs:

```yaml
logger:
  logs:
    custom_components.v2c_cloud: debug
```

## License

Distributed under the MIT License. See the [LICENSE](LICENSE) file for details.
