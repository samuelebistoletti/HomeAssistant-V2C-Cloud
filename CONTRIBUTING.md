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
2. If you use VS Code, the provided dev container spins up a standalone Home Assistant instance with the sample configuration (`config/configuration.yaml`).
3. Install development tools inside the container or your local environment:
   ```bash
   pip install -r requirements.txt
   ```

## Pull Request Checklist

Before opening a PR, please ensure you have:

1. **Updated documentation** for any user-facing change. Keep the root `README.md` and `custom_components/v2c_cloud/README.md` identical.
2. **Reviewed translations** (`strings.json`, `translations/en.json`, `translations/it.json`) and added new keys if the UI changes.
3. **Updated version metadata** (e.g. `manifest.json`, changelog, release notes) when releasing or adding notable features.
4. **Formatted and linted** the code:
   ```bash
   ./scripts/lint
   python -m compileall custom_components/v2c_cloud
   ```
5. **Tested the behaviour**. Prefer exercising changes in the dev container or against a real charger when possible. If tests cannot be automated, mention the manual steps taken in the PR.

## Filing Issues

Use [GitHub issues](../../issues) to report bugs or request features. Helpful reports typically include:

- Context (core version, integration version, deployment type)
- Clear reproduction steps and expected vs. actual behaviour
- Relevant logs (mask API keys and personal data)
- Screenshots or diagnostics when available

## Coding Style

- Python code is formatted and linted with [Ruff](https://docs.astral.sh/ruff/). The `scripts/lint` helper runs both format and lint passes.
- Keep functions small and prefer explicit typing (`from __future__ import annotations` is already enabled).
- Add concise comments only when the behaviour is not obvious from the code.

## License

By submitting a contribution you agree that it will be licensed under the project’s [MIT License](LICENSE).
