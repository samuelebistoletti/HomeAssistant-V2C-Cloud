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

Results are available under the **Security** and **Actions** tabs of the repository. The Tag and Release workflow will not create a release if any of these checks fail.

---

## Responsible Disclosure

Follow responsible disclosure practices: avoid sharing details publicly until a fix is available, and do not exploit issues beyond the minimum steps required for validation. See GitHub’s [Coordinated Disclosure guidelines](https://docs.github.com/en/code-security/getting-started/github-security-features#coordinated-disclosure) for best practices.

Thank you for helping keep the V2C Cloud integration secure!
