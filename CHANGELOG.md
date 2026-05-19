# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **Connection type editable post-setup** — the options flow now exposes a `Local (Wi-Fi)` / `Cloud only (4G)` toggle. Switching modes triggers an automatic integration reload. In cloud-only mode the optional local fallback IP field is ignored (forced to the empty sentinel); switching to local mode clears the cloud-only sentinel and the stored fallback device id, then accepts a new local IP via the same form. Resolves the inability to change connection type after the initial setup.
- **Cloud-only entity coverage expanded** — `_build_realtime_from_reported` (the cloud → synthetic LAN payload translator) now handles seven additional numeric `/reported` keys (`min_car_int`, `min_car_int_fb`, `max_car_int`, `max_car_int_fb`, `light_led`, `logo_led`, `contract_power` and its `contractedpower`/`contracted_power` aliases) and gains a string-field passthrough for device metadata (`device_id`/`deviceId` → `ID`, `version` → `FirmwareVersion`, `mac` → `MAC`). The cloud's `wifi_info` JSON blob is parsed inline so the SSID and active IP populate the corresponding sensors. Verified end-to-end against a real `/device/reported` + `/device/currentstatecharge` capture (firmware 2.4.6). The set of entities that show real data in cloud-only mode grows from ~12 to ~20+.
- **LAN-only entities now correctly advertise as Unavailable** in cloud-only mode instead of showing the misleading "Unknown" state. The six structurally LAN-only keys (`ReadyState`, `SignalStatus`, `Timer`, `ChargeMode`, `DynamicPowerMode`, `PauseDynamic`) — none of which are present in the cloud `/reported` or `/currentstatecharge` payloads — are gated via `available=False` when the config entry is cloud-only. Applies to the sensor, switch, and select platforms.

### Fixed

- **Connection-type radio labels were not translated** — the initial config-flow step rendered "Local (Wi-Fi)" / "Cloud only (4G)" in English regardless of the active UI locale because the schema used a hard-coded `vol.In({label: ...})` dict. Migrated the schema to `SelectSelector(translation_key="connection_type")` and added a top-level `selector` block to `strings.json` and all translation files (en/it/es).
- **Italian "Intensità Light LED"** entity name was mixed Italian/English. Renamed to "Intensità LED".
- **Connection-type description** now explicitly states that, if an optional local fallback IP is configured and becomes unreachable, control commands automatically fall back to the V2C Cloud API.
- **Number entities `MinIntensity` / `MaxIntensity` / `LightLED` / `ContractedPower` were Unknown in cloud-only mode** — they read via `local_key` but the cloud `/reported` keys (`min_car_int`, `max_car_int`, `light_led`, `contract_power`) were not in `_REPORTED_TO_REALTIME`. Each entity now resolves correctly in cloud-only mode.
- **Sensors `device_identifier` / `firmware_version` / `wifi_ssid` / `wifi_ip` were Unknown in cloud-only mode** — the synthesis loop did `float(str(raw))` on every value and silently dropped non-numeric ones. Added a string-passthrough path plus inline parsing of the cloud's `wifi_info` JSON blob to populate `SSID` / `IP`.

## [1.3.0-beta.1] - 2026-05-19

Pre-release for early-adopter testing — same code as the unreleased 1.3.0
candidate (see entry below), but published with `prerelease: true` so HACS
only proposes the update to users who opted into "Show beta versions".

This is a HACS-side gate; install via **Settings → Devices & Services →
HACS → V2C Cloud → ⋮ → Redownload**, then pick `1.3.0-beta.1` from the
version dropdown. Promotion to `1.3.0` stable will follow after a quiet
period if no regressions are reported.

See the full set of changes in the `[1.3.0]` section below.

## [1.3.0] - 2026-05-18

### Added

- **Full V2C Cloud endpoint coverage** – 10 new client methods cover every previously missing public endpoint: `start_charge`, `pause_charge`, `intensity`, `locked`, `dynamic`, `chargefvmode`, `max_car_int`, `min_car_int`, `denka/max_power`, and `GET /device/connected`. Each endpoint is exercised by dedicated tests in `tests/test_cloud_endpoints_1_3.py`.
- **10 new Home Assistant services**: `start_charge`, `pause_charge`, `set_charge_intensity`, `set_locked`, `set_dynamic`, `set_fv_mode`, `set_max_car_intensity`, `set_min_car_intensity`, `set_denka_max_power`, `get_connected_status`. The first five use the new LAN-vs-cloud router (see below); the photovoltaic and Denka calls are cloud-only.
- **Smart LAN-vs-cloud router** (`_async_route_local_or_cloud` in `__init__.py`). For control commands shared between LAN (`/write/`) and cloud, the integration prefers the LAN path when a `fallback_ip` is configured, and transparently falls back to the cloud endpoint when LAN is unreachable or the device is cloud-only (4G).
- **`ChargeMode` select entity** (LAN write to the `ChargeMode` keyword: monophasic / threephasic / mixed).
- **`LightLED` number entity** (LAN write to the `LightLED` keyword, 0-100 %).
- **User-configurable local refresh interval** (5-300 s, default 30 s) exposed via the Reconfigure dialog (`CONF_LOCAL_UPDATE_INTERVAL`). Cloud-only (4G) devices keep their fixed cadence and ignore the option. Changes apply live via an entry update listener — no integration reload required.
- **Spanish UI translation** – the previously incomplete Spanish support is now a full `translations/es.json` (235 keys), at parity with `en.json` and `it.json`.
- **Live smoke-test script** (`scripts/live_smoke_test.py`) – exercises every read endpoint and issues safe no-op writes against a real Trydan plus the V2C Cloud, then verifies snapshot/restore. Requires the explicit `--confirm-restore` flag and is never run in CI.
- **CI matrix on Python 3.12, 3.13 and 3.14**, ruff lint gate, coverage reporting via Codecov, and a new `.coveragerc`.
- **`.github/dependabot.yml`** — weekly grouped updates for both GitHub Actions and pip dependencies, with timezone-aware schedules.
- **`concurrency:` blocks** added to every push/PR workflow (`tests`, `security`, `hacs`, `hassfest`, `codeql`, `tag-and-release`). Saves CI minutes and avoids the "outdated result wins" race when developers push twice in a row.
- **Pip caching** (`actions/setup-python@v5` with `cache: pip`) on every Python step.
- **`tag-and-release.yaml` hardened** — the release pipeline now gates on the full Python matrix (3.12/3.13/3.14), ruff lint, hassfest and HACS validation in addition to the existing test + security checks. A manifest with a broken schema, a lint regression, or a HACS misconfiguration can no longer reach a published release.
- **52 new unit tests** total across 4 new test files (`test_cloud_endpoints_1_3`, `test_router_1_3`, `test_options_flow_interval`, `test_manifest_hygiene`) plus the two previously skipped pre-existing failures (`test_gather` and `test_init::test_rate_limit_doubles_coordinator_interval`) are now fixed and re-enabled.

### Changed

- **SSRF guard deduplicated** into `custom_components/v2c_cloud/_net.py::validate_private_ip`. Replaces four scattered copies with a single, tested helper covering both IP parse errors and policy violations (private + not loopback + not link-local + not unspecified).
- **Local API constants consolidated in `const.py`**: `LOCAL_HTTP_TIMEOUT`, `LOCAL_MAX_RETRIES`, `LOCAL_RETRY_BACKOFF`, `LOCAL_WRITE_RETRY_DELAY`, `CLOUD_ONLY_UPDATE_INTERVAL`, and the new `DEFAULT/MIN/MAX_LOCAL_INTERVAL` bounds.
- **`async_write_keyword` now validates the keyword** against a documented whitelist (`WRITEABLE_KEYWORDS`) to reduce the SSRF surface and prevent accidental misuse from automations.
- **HA minimum version**: kept in `hacs.json` (`"homeassistant": "2025.4.0"`). Initially also added to `manifest.json` as `min_ha_version`, but hassfest rejects that field as unknown — the HACS-side floor remains the source of truth.

### Fixed

- **`requirements.txt`**: `pyyaml` is now version-pinned (`>=6.0,<7`).
- **`requirements_test.txt`**: all packages now have upper bounds for reproducible CI builds.
- **`.ruff.toml`**: `target-version` aligned with the CI Python version (`py312`). Test/script directories have a targeted `per-file-ignores` so the strict `select = ALL` no longer drowns the lint output in test-only noise.
- **Devcontainer**: image bumped to `mcr.microsoft.com/devcontainers/python:3.14` (matches the latest CI matrix entry). `scripts/setup` now installs `requirements_test.txt` and `pytest-cov` as well, so pytest discovery works in VSCode out-of-the-box. VSCode pytest settings (`python.testing.pytestEnabled`, `pytestArgs`) added to `.devcontainer.json`.
- **`hacs.yaml` + `hassfest.yaml` triggers**: now scoped to `branches: [main]` on push so feature branches no longer spawn redundant runs. Daily cron retained.
- **CI hardening**: `persist-credentials: false` on every checkout that does not push back to the repo. Bandit artifact retention pinned to 30 days. `pip-audit` calls now use `--strict` so unknown vulnerabilities also fail the job.
- **Ruff format gate in CI**: the entire codebase has been mass-formatted with `ruff format` and both `ruff check` and `ruff format --check` now gate every PR and release. Future contributions must keep the tree formatted.
- **SBOM generated on every release**: `tag-and-release.yaml` now produces both SPDX-JSON and CycloneDX-JSON Software Bill of Materials via `anchore/sbom-action@v0` and attaches them to the GitHub Release as `v2c_cloud-<version>.spdx.json` / `.cyclonedx.json`. Downstream consumers and security scanners can pick whichever standard they prefer.
- **Reusable security pipeline**: `security.yaml` now exposes a `workflow_call` trigger so `tag-and-release.yaml` reuses the exact same SAST/audit/secret-scan jobs via `uses: ./.github/workflows/security.yaml`. Single source of truth — adding a scanner to `security.yaml` automatically gates releases too.

### Security

- **Tighter local-write surface**: writes are now rejected unless the keyword is in the documented Trydan write-list, the resolved IP parses cleanly *and* satisfies the private/non-loopback/non-link-local/non-unspecified policy.
- Audit of credential masking, SSRF guards and `eval/exec/pickle/yaml.unsafe_load` use confirmed clean — no new findings.

## [1.1.6] - 2026-03-24

### Fixed

- **Reauth completion shows wrong message** – the reauth config flow called `async_update_reload_and_abort` without an explicit `reason=` argument, which defaults to `"reconfigure_successful"`. As a result, after a successful re-authentication the UI displayed "Reconfiguration was successful" instead of "Re-authentication was successful". The `reason="reauth_successful"` argument is now passed explicitly.
- **Raw `reconfigure_successful` key shown in UI** – the `config.abort.reconfigure_successful` key was missing from `strings.json` and both translation files (`en.json`, `it.json`). Home Assistant rendered the raw key string instead of the localised message after a successful reconfigure flow. The key has been added to all three files.
- **Gitleaks CI false positive on test fixture** – the placeholder API key `test-api-key-abc123` used in `tests/conftest.py` triggered the `generic-api-key` Gitleaks rule on the full git history scan, causing the security CI job to fail. Added `.gitleaks.toml` with a `stopwords` entry for `test-api-key` and a path allowlist for the `tests/` directory; the fixture is intentionally non-functional and has never been a real credential.

### Changed

- **Removed unused `cannot_connect` error key** – the `config.error.cannot_connect` key was declared in `strings.json` and both translation files but was never emitted by `config_flow.py`. When the V2C Cloud is unreachable during initial setup the flow redirects to the `fallback_ip` step rather than showing a connection error. The dead key has been removed from all three files.

## [1.1.5] - 2026-03-23

### Fixed

- **Self-reinforcing rate-limit loop eliminated** – when the V2C Cloud API returned HTTP 429, the integration retried the same request up to three times before raising the error. Each retry consumed an additional call from an already-exhausted daily quota (1 000 calls/day), causing the budget to be burned at up to 3× the normal rate. Once the limit was hit, the quota was spent in its entirety on retries alone, making recovery impossible until the next daily reset. HTTP 429 responses are now raised immediately without any retry; the coordinator's exponential back-off (see below) handles pacing instead.
- **Coordinator keeps hammering the API when rate-limited** – after a 429, the cloud polling interval was not adjusted, so the integration kept attempting requests every 120 s regardless of how many times it had been rejected. The poll interval now doubles on each rate-limit cycle (`120 s → 240 s → 480 s → 600 s`), capped at 10 minutes. The interval automatically resets to the normal cadence on the first successful response, so no manual intervention is required once the daily quota window resets.

### Changed

- **Proactive pacing via `RateLimit-Remaining` header** – successful responses from the V2C Cloud include a `RateLimit-Remaining` header indicating how many calls are left in the current daily window. When this value drops below 150, the integration stretches the polling interval proportionally (reserving 50 calls for user-initiated commands), so the remaining budget lasts a full 24 hours in the worst case. This prevents the quota from being exhausted mid-day on days with heavy polling or frequent HA restarts.

## [1.1.4] - 2026-03-19

### Security

- **Clear-text logging of sensitive data eliminated** – three CodeQL alerts (`py/clear-text-logging-sensitive-data`) resolved: `headers` and `body` removed from the HTTP debug log in `_request` (the `apikey` header was already masked but the dict comprehension still constituted a taint path); `params` masking made case-insensitive; `fallback_device_id` (derived from `entry.data`, which contains the API key) removed from startup warning messages in `__init__.py`; exception objects replaced with `type(err).__name__` to prevent accidental credential leakage via exception messages.

## [1.1.3] - 2026-03-19

### Security

- **SSRF guard now blocks link-local addresses** – on Python 3.11+ link-local IPs (`169.254.x.x`) have `is_private=True`, so the previous guard (`is_private AND NOT is_loopback`) incorrectly allowed them through. All three guard sites (`config_flow._probe_local_api`, `local_api.async_write_keyword`, `local_api._async_fetch_local_data`) now also reject `is_link_local` addresses.
- **API key / authorization headers masked in debug logs** – the `apikey` and `authorization` headers are now logged as `***` in all request debug output, preventing credential leakage in log files.

### Fixed

- **Startup failure when cloud is rate-limited in Cloud+LAN mode** – if the V2C Cloud returned HTTP 429 during initial coordinator startup, the integration raised `ConfigEntryNotReady` and retried indefinitely at a very short interval. It now treats the rate-limit error as a transient failure and backs off to the normal poll cadence (#6).
- **OCPP server URL, date fields and RFID tag data tightened** – malformed values are now rejected early with clear validation errors before reaching the API.
- **`_normalize_bool` synced with `coerce_bool`** – the API client's bool parser now recognises `"enabled"`/`"disabled"` tokens, matching the entity-layer helper and preventing silent mismatches on firmware variants that report boolean fields as strings.

### Changed

- **Parallel cloud fetch per device** – `_fetch_single_device_state` now fires the `reported`, `rfid` and `version` API calls concurrently via `asyncio.gather` instead of sequentially, reducing per-device cloud poll latency by up to 2 × on fast connections.
- **Rate-limit retry jitter** – backoff after a `429` response now includes a small random component to avoid simultaneous retries across multiple devices.
- **Type annotations cleaned up** – entity modules use `V2CClient` instead of `Any` for the client parameter; `device_info` now declares a `DeviceInfo` return type; `DataUpdateCoordinator` imports follow the `TYPE_CHECKING`-only pattern where the type is annotation-only.

### Testing

- **Test suite expanded to 350 tests** – ten new test modules cover all entity types (binary sensor, sensor, switch, number, select, button), config flow SSRF guard, local API and device-state gathering. The full suite runs without a live Home Assistant instance or charger.

## [1.1.2] - 2026-03-12

### CI

- **`actions/checkout` upgraded to v6** – bumped from v2 (in `hacs.yaml`, `hassfest.yaml`) and v4 (in `tests.yaml`, `security.yaml`, `codeql.yaml`, `tag-and-release.yaml`) to v6, resolving the Node.js 20 deprecation warning ahead of the June 2026 enforcement deadline.
- **`hacs/action` pinned to v22.5.0** – replaced the mutable `@main` floating tag with a commit-pinned reference (`d556e736...`) for supply-chain security.

## [1.1.1] - 2026-03-12

### Fixed
- **Re-auth / Reconfigure no longer blocked when cloud is unavailable** – if `/pairings/me` returns 403 or the V2C Cloud is unreachable during the reauth or reconfigure flow, the new API key is now accepted and saved immediately. The coordinator will validate connectivity on the next refresh cycle. Only a definitive HTTP 401 (invalid credentials) still blocks the flow.
- **Slave device select shows "MQTT" for type 11** – devices configured with MQTT-based energy monitoring (`slave_type = 11`) were previously stuck in unknown state because the value was missing from the options map.

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
