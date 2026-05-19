# Contribution Guidelines

Thank you for helping improve the V2C Cloud Home Assistant integration! This document explains how to report issues and submit changes effectively.

## Ways to Contribute

- Report bugs or regressions
- Suggest or discuss new features
- Improve documentation or translations
- Submit code changes

All contributions are managed through GitHub. Issues and pull requests are preferred for everything except security reports (see `SECURITY.md`).

## Getting Started

1. Fork the repository and branch from `main`.
2. If you use VS Code, opening the workspace prompts you to reopen in the dev container. The `initializeCommand` runs on the host first and:
   - creates the `v2c-dev` Docker network if missing,
   - runs `docker compose up -d homeassistant` so the companion Home Assistant container (`hass_core_dev`, image `ghcr.io/home-assistant/home-assistant:stable`, with `config/configuration.yaml` and `custom_components/` bind-mounted) is up before the dev container is built.

   The dev container is attached to the `v2c-dev` network via `runArgs`, so HA is reachable from inside as `http://homeassistant:8123`. From the host, the same instance is published on `http://localhost:8123` (port 8123 is the only exposed port). HA uses `restart: "no"` — after a host reboot the service stays off until the next time you open the dev container or run `docker compose up -d homeassistant` manually.
3. **Set up local secrets in one go.** All dev secrets live in a single gitignored file at the repo root: `.env.dev`. The committed template `.env.dev.example` documents every variable, where to obtain it, and who consumes it. Before (re)opening the dev container:
   ```bash
   cp .env.dev.example .env.dev
   $EDITOR .env.dev   # fill in GH_TOKEN, V2C_CLOUD_API_KEY, V2C_LOCAL_IP, HASS_TOKEN
   ```
   `scripts/setup` appends an idempotent block to `~/.bashrc` that sources `.env.dev` with `set -a`, so every interactive shell gets the values exported automatically.
4. `scripts/setup` (the `postCreateCommand`) is idempotent and runs automatically. It installs:
   - `requirements.txt` + `requirements_test.txt` + `pytest-cov`,
   - `mcp-proxy` via `uv tool install` (consumed by Claude Code's MCP wiring),
   - the `.env.dev` shell hook described in step 3.

   You can re-run it at any time with `./scripts/setup` from inside the dev container.
5. Run the test suite to verify everything works:
   ```bash
   python -m pytest tests/ -v
   ```

### MCP wiring

The dev container includes Node.js LTS (for `npx`) and `mcp-proxy` (`uv tool install git+https://github.com/sparfenyuk/mcp-proxy`). `.mcp.json` (checked in) configures three MCP servers consumed by Claude Code running inside the container: `context7`, `memory`, and `Home Assistant` (the latter via `mcp-proxy → http://homeassistant:8123/api/mcp`).

The Home Assistant MCP server reads its bearer from `${HASS_TOKEN}`, which Claude Code interpolates from its process env at spawn time. The env var comes from `.env.dev` (see step 3 above). After your first edit to `.env.dev`, open a new terminal — or run `source ~/.bashrc` — and restart Claude Code so it picks up the new env.

## Pull Request Checklist

Before opening a PR, please ensure you have:

1. **Updated documentation** for any user-facing change. Keep the root `README.md` and `custom_components/v2c_cloud/README.md` identical (`diff README.md custom_components/v2c_cloud/README.md` must be empty).
2. **Reviewed translations** (`strings.json`, `translations/en.json`, `translations/it.json`, `translations/es.json`) and added new keys if the UI changes. `tests/test_manifest_hygiene.py::TestTranslationsParity` will fail if a key is missing in any of the four files.
3. **Updated version metadata** (e.g. `manifest.json`, `CHANGELOG.md`, release notes) when releasing or adding notable features.
4. **Formatted and linted** the code:
   ```bash
   ./scripts/lint
   ruff check .
   python -m compileall custom_components/v2c_cloud
   ```
5. **Run the automated tests** and confirmed they all pass on Python 3.12 and 3.13 (CI tests both):
   ```bash
   python -m pytest tests/ -v
   ```
6. **Tested the behaviour**. Prefer exercising changes in the dev container or against a real charger when possible. If tests cannot be automated, mention the manual steps taken in the PR.
7. *(Optional)* **Ran the live smoke test** against a real Trydan + cloud account when the change affects HTTP surface:
   ```bash
   V2C_CLOUD_API_KEY=<your_test_key> V2C_LOCAL_IP=<your_device_ip> \
     python scripts/live_smoke_test.py --confirm-restore
   ```
   The `--confirm-restore` flag is required (the script aborts without it). Always take a fresh out-of-band backup of the V2C Cloud configuration before running it against a production wallbox; the script restores every value it touches but a backup is a sensible belt-and-braces measure.

## Filing Issues

Use [GitHub issues](../../issues) to report bugs or request features. Helpful reports typically include:

- Context (core version, integration version, deployment type)
- Clear reproduction steps and expected vs. actual behaviour
- Relevant logs (mask API keys and personal data)
- Screenshots or diagnostics when available

## Coding Style

- Python code is formatted and linted with [Ruff](https://docs.astral.sh/ruff/). The `scripts/lint` helper runs both format and lint passes. CI gates on `ruff check .` (the format check is not yet gated — see the workflow).
- Target Python is **3.12** (CI runs the matrix on 3.12 and 3.13). `.ruff.toml` sets `target-version = "py312"`.
- Keep functions small and prefer explicit typing (`from __future__ import annotations` is already enabled).
- Add concise comments only when the behaviour is not obvious from the code.

## License

By submitting a contribution you agree that it will be licensed under the project’s [MIT License](LICENSE).
