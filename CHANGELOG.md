# Changelog

All notable changes to this project will be documented in this file.

## [1.3.5] - 2026-06-26

### Fixed

- **`ChargePower` / `HousePower` (and `FVPower`, `BatteryPower`, `GridPower`) showed `W` while the value was actually `kW` in cloud-only (4G) mode** (#42). The cloud→LAN synthesis scaled these power fields by 1000 only when a `voltage`/`voltageinstallation` field happened to be present in the payload and below 10 — an unrelated heuristic that silently skipped the conversion on accounts where that field was absent or out of range. The cloud always reports power measurements in kW, so the kW→W conversion is now applied unconditionally, the same way `ContractedPower` already is.

### Removed

- **SBOM assets (SPDX-JSON / CycloneDX-JSON) no longer attached to releases.** Since they were introduced in `1.3.0`, every release shipped 3 assets instead of 1 (`v2c_cloud.zip` plus the two SBOM files). HACS' download counter reads `download_count` from the release's asset list and is known to pick the wrong entry when more than one asset is present (see [hacs/integration#4438](https://github.com/hacs/integration/issues/4438)), which tracked with the integration's HACS download count going blank. Releases now publish only `v2c_cloud.zip`.

## [1.3.3] - 2026-06-17

Maintenance release. No functional change to the integration — runtime code,
entities and the config-entry schema are identical to `1.3.1`. Dependency,
test-tooling and CI-action updates only. Full suite (474 tests), the ruff
lint + format gates and the pip-audit dependency audit re-verified green
against every bumped pin.

> Supersedes the unreleased `1.3.2` commit: its release pipeline failed on the
> `security` gate (a fresh batch of aiohttp test-only advisories landed) before
> any tag or artifact was published. This release folds in that audit fix.

### Changed

- **`ruff` 0.15.16 → 0.15.17** (`requirements.txt`, Dependabot #30) — lint + format gates re-verified clean.
- **`pip` >=26.1.1 → >=26.1.2** (`requirements.txt`, Dependabot #35).
- **`pytest` >=9.0.3 → >=9.1.0** (`requirements_test.txt`, Dependabot #33, upper bound `<10` retained).
- **`pytest-asyncio` >=1.3.0 → >=1.4.0** (`requirements_test.txt`, Dependabot #32, upper bound `<2` retained).
- **`codecov/codecov-action` v6.0.1 → v7.0.0** (Dependabot #37) — removes an internal license-compliance workflow; no input/output changes for callers.
- **`gitleaks/gitleaks-action` v2 → v3.0.0** (Dependabot #34) — runtime Node 20 → Node 24, no input/output/behaviour changes; clears the Node 20 deprecation ahead of GitHub's 2026-09-16 runner removal.
- **`home-assistant/actions/hassfest`** pinned SHA refreshed to upstream `master` (Dependabot #36).

### Security

- **11 aiohttp advisories now affect the pinned test dependency** `aiohttp<3.14` (`requirements_test.txt`): the original CVE-2026-34993 / CVE-2026-47265 plus a fresh batch (CVE-2026-50269 and CVE-2026-54273…54280), every one fixed only in aiohttp 3.14.0/3.14.1. The upgrade to aiohttp 3.14 (Dependabot #31) was verified to break the entire test suite — `aioresponses` 0.7.8 (its latest release) does not pass the `stream_writer` kwarg that aiohttp 3.14 made mandatory. **End users are unaffected:** the integration ships `"requirements": []`; the patched aiohttp is provided by Home Assistant core at runtime. The advisories are scoped to the test harness — the `security.yaml` test-deps audit now ignores all 11 (runtime audit stays `--strict` with zero ignores), and the matching Dependabot alerts are dismissed as `tolerable_risk` — until `aioresponses` ships a 3.14-compatible release. The durable fix (migrating off `aioresponses`) is tracked in the backlog.

## [1.3.1] - 2026-06-09

Maintenance release. No functional change to the integration — runtime code,
entities and the config-entry schema are identical to `1.3.0`. Dependency and
CI-tooling updates only.

### Changed

- **`ruff` 0.15.13 → 0.15.16** (`requirements.txt`, Dependabot #26) — lint + format gates re-verified clean against the bumped pin.
- **`softprops/action-gh-release` v2.5.0 → v3.0.0** in `tag-and-release.yaml` (Dependabot #29). v3.0.0 moves the action runtime from Node 20 to Node 24 (no input/API changes); this clears the Node 20 deprecation ahead of the 2026-06-16 GitHub Actions enforcement, matching the `actions/stale` v10 bump shipped in `1.3.0`.

## [1.3.0] - 2026-06-09

Stable release. Promotes the `1.3.0` line to general availability after the
public beta window (`beta.1` 2026-05-19 → `beta.3` 2026-06-01) closed with no
regressions reported. **No code changes relative to `1.3.0-beta.3`.**

This is the cumulative `1.2.x` → `1.3.0` change set, developed and validated
across the three pre-releases listed below. The integration gains full V2C
Cloud endpoint coverage, automatic multi-charger discovery, a LAN-vs-cloud
control router, and substantially better cloud-only (4G) behaviour.

> **Breaking (auto-migrated):** the config entry schema is upgraded from v1 to
> v2 on first load — no user action required. Rolling **back** to `1.2.x` is
> not supported; see _Upgrade / downgrade notes_ below.

### Added

- **Full V2C Cloud endpoint coverage** – 10 new client methods cover every previously missing public endpoint: `start_charge`, `pause_charge`, `intensity`, `locked`, `dynamic`, `chargefvmode`, `max_car_int`, `min_car_int`, `denka/max_power`, and `GET /device/connected`. Each is exercised by dedicated tests in `tests/test_cloud_endpoints_1_3.py`.
- **10 new Home Assistant services**: `start_charge`, `pause_charge`, `set_charge_intensity`, `set_locked`, `set_dynamic`, `set_fv_mode`, `set_max_car_intensity`, `set_min_car_intensity`, `set_denka_max_power`, `get_connected_status`. The first five use the LAN-vs-cloud router; the photovoltaic and Denka calls are cloud-only.
- **Automatic multi-charger discovery** – an account with N chargers is fully supported. Every charger's LAN IP is sourced from the cloud `/pairings/me` response at runtime and a normalised snapshot is persisted on every successful refresh (`entry.data["cached_pairings"]`). During a cloud outage every previously-seen charger stays addressable via its last-known IP; when the cloud returns, the cache is reconciled (added devices appear, removed devices disappear). Replaces the single user-typed fallback IP.
- **Smart LAN-vs-cloud router** (`local_api.async_route_local_or_cloud`) – control commands shared between LAN (`/write/`) and cloud (`/device/*`) prefer the LAN path and transparently fall back to the cloud endpoint when LAN is unreachable or the device is cloud-only. Covers start/pause charge, intensity, locked, dynamic. Controls with no cloud endpoint (`LightLED`, `ContractedPower`, `Timer`, `PauseDynamic`, `ChargeMode`, `DynamicPowerMode`) raise a clear, user-facing `HomeAssistantError` in cloud-only mode instead of silently dropping the write.
- **Editable connection type** – an options-flow `Local (Wi-Fi)` / `Cloud only (4G)` toggle switches modes post-setup and triggers an automatic integration reload.
- **`ChargeMode` select** (monophasic / threephasic / mixed) and **`LightLED` number** (0-100 %) entities.
- **User-configurable local refresh interval** (5-300 s, default 30 s) via the Reconfigure dialog (`CONF_LOCAL_UPDATE_INTERVAL`). Cloud-only (4G) devices keep their fixed cadence and ignore the option. Applied live via an entry update listener — no reload required.
- **Expanded cloud-only entity coverage** – `_build_realtime_from_reported` synthesises a LAN-shaped payload from the cloud `/reported` document, including seven additional numeric keys plus device metadata (ID, firmware, MAC, SSID, IP via the `wifi_info` blob). The set of entities showing real data in cloud-only mode grows from ~12 to ~20+. Structurally LAN-only entities (`ReadyState`, `SignalStatus`, `Timer`, `ChargeMode`, `DynamicPowerMode`, `PauseDynamic`) now correctly advertise as **Unavailable** in cloud-only mode instead of the misleading "Unknown".
- **Discovered `/device/logo_led` cloud endpoint** (undocumented, live on firmware 2.4.6) – the LogoLED switch is now controllable from cloud-only mode via `async_cloud_set_logo_led`.
- **Spanish UI translation** – the previously incomplete Spanish support is now a full `translations/es.json` (235 keys), at parity with `en.json` and `it.json`.
- **Live smoke-test script** (`scripts/live_smoke_test.py`) – exercises every read endpoint and issues safe no-op writes against a real Trydan plus the V2C Cloud, then verifies snapshot/restore. Requires the explicit `--confirm-restore` flag and is never run in CI.
- **CI / supply-chain hardening** – Python 3.12/3.13/3.14 matrix, ruff lint + format gates, Codecov coverage reporting (`.coveragerc`), `concurrency:` blocks on every workflow, pip caching, `.github/dependabot.yml` (weekly grouped Actions + pip updates), SBOM (SPDX-JSON + CycloneDX-JSON via `anchore/sbom-action`) attached to every release, and a reusable `security.yaml` (`workflow_call`) so the release pipeline gates on the exact same SAST / dependency-audit / secret-scan jobs as PRs.

### Changed

- **Config entry schema v1 → v2 (auto-migrated).** `async_migrate_entry` is version-aware via a `_MIGRATIONS` registry; `SCHEMA_VERSION = 2` in `const.py` is the single source of truth for both `config_flow.VERSION` and the migration target. Legacy entries are translated: the cloud-only sentinel (`fallback_ip == ""` / `"0.0.0.0"`) becomes `cloud_only: True`; a non-empty `fallback_ip` paired with `fallback_device_id` becomes a one-record `cached_pairings`; an `initial_pairings` snapshot wins over the single-device pair. Legacy keys are dropped from `entry.data`.
- **Cloud-only mode is encoded as `entry.data["cloud_only"]: bool`** instead of the empty-string `fallback_ip` sentinel. The first-setup fallback-IP step is gone — initial setup now requires the cloud to be reachable to capture the pairings list, consistent with the integration's name and removing a single point of failure.
- **SSRF guard deduplicated** into `custom_components/v2c_cloud/_net.py::validate_private_ip` (private + not loopback + not link-local + not unspecified), replacing four scattered copies with a single tested helper.
- **`async_write_keyword` validates the keyword** against a documented `WRITEABLE_KEYWORDS` whitelist to reduce the LAN write/SSRF surface and prevent accidental misuse from automations.
- **Local API constants consolidated in `const.py`**: `LOCAL_HTTP_TIMEOUT`, `LOCAL_MAX_RETRIES`, `LOCAL_RETRY_BACKOFF`, `LOCAL_WRITE_RETRY_DELAY`, `CLOUD_ONLY_UPDATE_INTERVAL`, and the new `DEFAULT/MIN/MAX_LOCAL_INTERVAL` bounds.
- **HA minimum version** stays in `hacs.json` (`"homeassistant": "2025.4.0"`) — hassfest rejects `min_ha_version` in `manifest.json` as an unknown field.

### Fixed

- **`ChargeMode` Select showed "Unknown" in LAN mode** – it is write-enabled but absent from `/RealTimeData`; the integration's read-only-keyword augmentation covered `LogoLED` + `LightLED` but missed `ChargeMode`. The local coordinator now also fetches `/read/ChargeMode` in parallel and the Select displays the live value.
- **`Local refresh interval` option was not persisted** – the options flow returned `async_create_entry(title="", data={})`, and HA uses that `data` argument to overwrite `entry.options`, so the field always snapped back to 30 s. Fix: pass the populated options dict to `async_create_entry(data=new_options)`.
- **Connection-type radio labels were not translated** – the schema used a hard-coded `vol.In({label: ...})` dict. Migrated to `SelectSelector(translation_key="connection_type")` with a top-level `selector` block in `strings.json` and all translation files. Italian "Intensità Light LED" renamed to "Intensità LED".
- **Cloud-only data accuracy** (validated end-to-end against a live firmware-2.4.6 `/device/reported` + `/device/currentstatecharge` capture):
  - `VoltageInstallation` reported a spurious ~77 V – the cloud `voltage` field is a small internal signal; the real mains/installation voltage is carried by `cp_level` (e.g. `248` on a 230 V EU install). Remapped `cp_level → VoltageInstallation` and dropped the misleading `voltage` mapping.
  - `ContractedPower` was off by 100× – the cloud encodes `contract_power` as W/100 (`"7"` = 700 W = 0.7 kW), but the Number entity divides by 1000 to render kW. Added a `_CLOUD_TO_LAN_MULTIPLIERS` table that multiplies `ContractedPower` by 100 during synthesis.
  - `LightLED` showed `1` for a LED set to 100 % – the cloud serialises `light_led` as a 0.0-1.0 fraction; the LAN keyword and entity use 0-100 % integers. Added a × 100 multiplier.
  - Number / Switch / Select **writes were silently dropped in cloud-only (4G)** – every setter called `async_write_keyword` directly, so the LAN write raised `V2CLocalApiError` and no cloud fallback fired. Every setter now routes through `async_route_local_or_cloud`.
  - `device_identifier` / `firmware_version` / `wifi_ssid` / `wifi_ip` sensors were "Unknown" – the synthesis loop coerced every value via `float(str(raw))` and silently dropped non-numeric ones. Added a string-passthrough path plus inline parsing of the cloud's `wifi_info` JSON blob.
- **UI strings referencing the removed `fallback_ip` step / field** were cleaned up across `strings.json` and the en/it/es translations; the `connection_type` and `init` descriptions now mention auto-discovered per-device IPs and automatic LAN→cloud routing.
- **`requirements.txt`**: `pyyaml` is now version-pinned (`>=6.0,<7`). **`requirements_test.txt`**: all packages have upper bounds for reproducible CI builds.
- **`.ruff.toml`**: `target-version` aligned with CI (`py312`); test/script directories get a targeted `per-file-ignores` so the strict `select = ALL` rule set no longer drowns the lint output. The whole tree is `ruff format`-clean and both `ruff check` and `ruff format --check` gate every PR and release.
- **CI hardening**: `persist-credentials: false` on every read-only checkout; `pip-audit --strict`; bandit artifact retention pinned to 30 days; `hacs.yaml` + `hassfest.yaml` push triggers scoped to `branches: [main]` (daily cron retained).

### Hardening (post-beta review pass)

- **`_normalise_pairings` deduplicated** into a single `_pairings.py` module imported by both `config_flow.py` and `__init__.py`, eliminating drift between the two persistence paths. Persisted lists are capped at 64 records during normalisation, and `async_setup_entry` now passes the raw entry data through `_normalise_pairings` so a malformed snapshot (`[{}]`, `[{"deviceId": None}]`, a non-list value) no longer prevents the integration from loading.
- **LAN-vs-cloud router takes a `cloud_call` factory** (`Callable[[], Awaitable]`) instead of a pre-constructed coroutine. On the LAN-success happy path the cloud awaitable is no longer created, eliminating the `RuntimeWarning: coroutine was never awaited` pollution.
- **Parallel local-coordinator first-refresh** in the `sensor` platform – setup time on multi-charger accounts is bounded by the slowest device's LAN response rather than the sum of all devices'.
- **`config_flow.py` no longer surfaces exception args** in the unknown-error branch (`_LOGGER.exception(...)` → `_LOGGER.error("…: %s", type(err).__name__)`) so a future exception-class change cannot leak the API key into a traceback.
- **Legacy `fallback_ip` without a `fallback_device_id` is logged** during migration so a dropped IP that could not be turned into a `(deviceId, ip)` record is diagnosable.

### Security

- **Tighter local-write surface** – writes are rejected unless the keyword is in the documented Trydan write-list and the resolved IP parses cleanly *and* satisfies the private / non-loopback / non-link-local / non-unspecified policy.
- Audit of credential masking, SSRF guards and `eval`/`exec`/`pickle`/`yaml.unsafe_load` use confirmed clean — no new findings.

### Upgrade / downgrade notes

- **Rolling back from `1.3.x` to `1.2.x` via HACS is not supported.** The v2 schema drops `fallback_device_id` / `initial_pairings` and persists multi-device IPs only in `cached_pairings` (a key `1.2.x` does not understand). v2 entries leave a vestigial `fallback_ip: ""` sentinel so the older code path loads instead of crashing on `KeyError`, but a rollback degrades a multi-device account to cloud-only mode and silently loses LAN data. Re-setup the integration after a downgrade.

## [1.3.0-beta.3] - 2026-06-01

Pre-release on the HACS beta channel. Post-`beta.2` hardening pass from a full security + performance + architecture review — schema-migration safety, pairings-persistence robustness, internal API shape, and log hygiene — with no user-observable behaviour change in the happy path. Folded into [1.3.0].

## [1.3.0-beta.2] - 2026-05-24

Pre-release on the HACS beta channel. Added the breaking multi-device auto-discovery schema (config entry v1 → v2), the editable connection-type toggle, the expanded cloud-only entity coverage, and the cloud-only data-accuracy fixes (VoltageInstallation / ContractedPower / LightLED / routed writes). Folded into [1.3.0].

## [1.3.0-beta.1] - 2026-05-19

First pre-release of the `1.3.0` line on the HACS beta channel — full V2C Cloud endpoint coverage, the LAN-vs-cloud router, and the CI / supply-chain hardening. Published with `prerelease: true` so HACS only proposed it to users who opted into "Show beta versions". Folded into [1.3.0].

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
- `v2c_cloud.set_installation_voltage` service that writes to the local `/write/VoltageInstallation` endpoint so automations can adjust the parameter explicitly, now validated between 100 V and 450 V.

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
