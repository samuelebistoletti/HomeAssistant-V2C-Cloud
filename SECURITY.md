# Security Policy

## Supported Versions

Security fixes target the latest code on the `main` branch and the most recent published release. Historical tags are not maintained, so always update through HACS or pull the latest commit before reporting vulnerabilities.

---

## Reporting a Vulnerability

If you identify a potential vulnerability, **do not create a public issue or discussion**. Use the private **GitHub Security Advisory** workflow instead:

1. Navigate to **Security → Advisories → Report a vulnerability**.
2. Provide as much detail as possible:
   - Description and impact
   - Reproduction steps or proof-of-concept
   - Expected vs. actual behaviour
   - Relevant logs (mask sensitive data)

Reports are acknowledged within **72 hours**. A remediation plan or mitigation guidance is shared within **7 business days**, depending on severity and reproduction effort. All fixes are published in the next patch release and summarised in the changelog.

---

## Scope

This policy covers:
- Code in this repository under `custom_components/v2c_cloud`
- Configuration handled directly by the integration

Out of scope:
- Issues in the official **V2C Cloud** backend or APIs
- **Home Assistant Core** defects
- Vulnerabilities in third-party dependencies bundled with Home Assistant

Please report out-of-scope issues to the appropriate vendor or project.

---

## Automated Security Scanning

The repository runs the following security checks automatically on every push and pull request to `main`, and on a weekly schedule:

| Tool | Purpose |
| --- | --- |
| **Bandit** | SAST — static analysis of the Python source for common security issues (medium severity and confidence, or higher) |
| **pip-audit** | Dependency audit — scans `requirements.txt` and `requirements_test.txt` for known CVEs |
| **gitleaks** | Secret scanning — detects accidentally committed credentials or tokens across the full git history |
| **GitHub CodeQL** | Deep static analysis for Python and Actions workflows (security-extended query suite) |
| **ruff** *(1.3.0)* | Lint gate covering the integration source on every push/PR. Configured for `target-version = "py312"` and the strict `select = ALL` rule set. |

Results are available under the **Security** and **Actions** tabs of the repository. The Tag and Release workflow will not create a release if any of these checks fail.

---

## Logging Policy

The integration follows defensive logging conventions to avoid leaking credentials or sensitive data:

- **Credential masking**: any HTTP header or query parameter whose key matches `apikey`, `authorization`, or `password` (case-insensitive) is logged as `***`. The masking happens at request-build time in `V2CClient._request` (see `custom_components/v2c_cloud/v2c_cloud.py`).
- **No body logging on errors**: HTTP error responses raise structured exceptions (`V2CAuthError`, `V2CRequestError`, `V2CRateLimitError`); the raw body is **not** persisted in logs. Debug-level traces of successful requests are confined to URL + masked params.
- **Exception type, not instance**: warning lines reference `type(err).__name__` instead of the full exception, preventing accidental credential leakage through traceback details.
- **SSRF guard**: outbound HTTP calls to user-supplied addresses are validated via `_net.validate_private_ip`, which requires `is_private AND NOT is_loopback AND NOT is_link_local AND NOT is_unspecified`. Python 3.11+ classifies `169.254.x.x` as `is_private=True`, so the explicit `is_link_local` check is load-bearing.
- **Write keyword whitelist** *(1.3.0)*: `async_write_keyword` rejects keywords outside `WRITEABLE_KEYWORDS` before the request is built, limiting the LAN write surface to the documented Trydan registers even if an automation attempts arbitrary input.

---

## Live Smoke Test Disclosure

The repository ships `scripts/live_smoke_test.py` (added in 1.3.0). It is **not** run in CI and is gated behind the explicit `--confirm-restore` flag. The script:

- Captures a JSON snapshot of the device + cloud state to `/tmp/v2c_snapshot_<timestamp>.json` *before* any mutation.
- Issues round-trip writes that re-apply the value already on the device (no-op semantics).
- Never touches keys that would isolate the device (`WiFi`, `OCPP*`, `InverterIP`, `Reboot`).
- Restores every modified field at the end and verifies the post-state matches the snapshot; otherwise exits with code 3.

Operators running it against a production charger should still take an out-of-band configuration backup beforehand.

---

## Responsible Disclosure

Follow responsible disclosure practices: avoid sharing details publicly until a fix is available, and do not exploit issues beyond the minimum steps required for validation. See GitHub’s [Coordinated Disclosure guidelines](https://docs.github.com/en/code-security/getting-started/github-security-features#coordinated-disclosure) for best practices.

Thank you for helping keep the V2C Cloud integration secure!
