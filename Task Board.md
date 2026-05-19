# Task Board

## Today
- [ ] Aspettare review utente su PR #12, poi merge → tag-and-release v1.3.0 auto-triggera

## This Week
- [ ] Verificare GitHub Release v1.3.0 post-merge (SBOM SPDX + CycloneDX allegati + ZIP)
- [ ] Smoke test post-release con HACS reinstall in HA dev container (verifica options flow per local_update_interval e router LAN↔cloud)

## Backlog
- [ ] Answer Claudify tailoring questions → update memory + skills (deferred from 031826)
- [ ] Future: implement V2C cloud webhooks (startCharge/endCharge) — quando V2C documenta meccanismo di firma/auth
- [ ] Future: bump codecov-action a v6 (oggi pinnata a v5)
- [ ] Future: refactor del service dispatcher in `__init__.py` (~640 righe ripetitive → ServiceSpec data-driven)
- [ ] Future: split di `_async_update_data` (136 righe) in 3 helper

## Done
- [x] Set up project with Claudify (`/start`) — 031726
- [x] Full /review pass + all fixes (critical/high/medium/low) across 9 files — 031826
- [x] System audit (grade A, 9/9 checks passed) — 031826
- [x] Commit all review changes — 031826
- [x] Write test suite: 350 tests, 10 modules, all green — 031826/031926
- [x] Update both READMEs (Development & Testing section) — 031826/031926
- [x] Fix SSRF link-local guard (169.254.x.x) — 031926
- [x] Release 1.1.3: CHANGELOG, manifest bump, README update, commit+push — 031926
- [x] Fix 3 CodeQL clear-text logging alerts (#5, #6, #7) — 031926
- [x] Release 1.1.4: CHANGELOG, manifest bump, commit+push — 031926
- [x] Diagnose persistent rate-limit loop from user live log — 032326
- [x] Fix 1: Remove retry-on-429 in v2c_cloud.py — 032326
- [x] Fix 2: Coordinator exponential backoff on rate limit — 032326
- [x] Fix 3: Proactive pacing via RateLimit-Remaining — 032326
- [x] Update tests (352 total, all green) — 032326
- [x] Release 1.1.5: CHANGELOG + manifest, commit+push — 032326/032426
- [x] Fix raw reconfigure_successful key shown in UI post-reconfigure — 032426
- [x] Fix Gitleaks CI false positive (.gitleaks.toml) — 032426
- [x] Full translation key audit (config_flow.py vs strings.json) — 032426
- [x] Fix reauth flow: wrong abort message (missing reason= arg) — 032426
- [x] Remove orphaned cannot_connect key from strings + translations — 032426
- [x] Release 1.1.6: CHANGELOG, manifest, commit+push — 032426
- [x] Comprehensive code review + security audit (3 Explore agents + Plan agent) — 051826
- [x] Add 10 new cloud client methods (startcharge, pausecharge, intensity, locked, dynamic, chargefvmode, max_car_int, min_car_int, denka, connected) — 051826
- [x] Add 10 new HA services + smart LAN-vs-cloud router — 051826
- [x] Add ChargeMode select + LightLED number entities — 051826
- [x] Add user-configurable local_update_interval (5-300 s, default 30) — 051826
- [x] Extract SSRF guard into shared _net.py helper — 051826
- [x] Add WRITEABLE_KEYWORDS whitelist for LAN writes — 051826
- [x] Create translations/es.json (235 keys parity with en/it) — 051826
- [x] Create scripts/live_smoke_test.py with snapshot/restore — 051826
- [x] Live smoke test against real Trydan (10.35.0.50) + cloud: 25/25 endpoints OK, restore verified — 051826
- [x] Write 47 new unit tests (cloud endpoints, router, options flow, manifest hygiene) — 051826
- [x] Fix 2 pre-existing test failures (test_gather + test_init rate-limit) — 051826
- [x] CI: Python matrix 3.12/3.13/3.14, ruff lint + format gate, coverage Codecov, concurrency, persist-credentials, Dependabot — 051826
- [x] Devcontainer: bump to python:3.14, scripts/setup installs test deps, VSCode pytest discovery — 051826
- [x] SBOM generation (SPDX + CycloneDX) on tag-and-release — 051826
- [x] security.yaml workflow_call reuse in tag-and-release — 051826
- [x] Bump version 1.1.6 → 1.3.0, CHANGELOG entry — 051826
- [x] Update README/TECHNICAL_NOTES/SECURITY/CONTRIBUTING/bug_report.yml — 051826
- [x] Commit + push feat/1.3.0-omnibus + open PR #12 — 051926
- [x] Diagnose + fix 3 CI gate failures: bandit B104 nosec, pytest CVE-2025-71176, hassfest unknown min_ha_version field — 051926
- [x] Diagnose + fix pytest-asyncio 0.x incompat with pytest 9 — 051926
- [x] Diagnose + fix GitHub Advanced Security review: 3 unpinned 3rd-party actions → SHA-pinned — 051926
- [x] Lock tag-and-release.yaml to branches:[main] (prevent feature-branch auto-release) — 051926
- [x] PR #12 all 5 CI gates green on HEAD 839ae24 — 051926
