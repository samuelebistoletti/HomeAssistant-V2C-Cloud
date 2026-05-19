"""Tests guarding manifest, requirements and translation hygiene."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATION_DIR = _PROJECT_ROOT / "custom_components" / "v2c_cloud"


class TestManifest:
    """Static assertions on manifest.json."""

    @pytest.fixture(scope="class")
    def manifest(self) -> dict:
        return json.loads((_INTEGRATION_DIR / "manifest.json").read_text())

    def test_domain_matches_directory(self, manifest) -> None:
        assert manifest["domain"] == "v2c_cloud"

    def test_version_format_semver(self, manifest) -> None:
        assert re.match(r"^\d+\.\d+\.\d+$", manifest["version"])

    def test_no_min_ha_version_in_manifest(self, manifest) -> None:
        # min_ha_version is a HACS-only extension; hassfest rejects it as an
        # unknown field. The HA minimum version lives in hacs.json instead.
        assert "min_ha_version" not in manifest

    def test_min_ha_version_in_hacs_json(self) -> None:
        hacs_path = _PROJECT_ROOT / "hacs.json"
        hacs = json.loads(hacs_path.read_text())
        assert "homeassistant" in hacs
        assert re.match(r"^\d{4}\.\d{1,2}\.\d+$", hacs["homeassistant"])

    def test_documentation_is_https(self, manifest) -> None:
        assert manifest["documentation"].startswith("https://")

    def test_codeowners_present(self, manifest) -> None:
        assert manifest["codeowners"]
        assert all(o.startswith("@") for o in manifest["codeowners"])

    def test_no_runtime_requirements(self, manifest) -> None:
        # HA core bundles aiohttp/voluptuous; the integration should not declare them.
        assert manifest["requirements"] == []


class TestRequirementsFiles:
    """Both requirements*.txt files are well-formed."""

    @pytest.fixture(scope="class")
    def main_reqs(self) -> list[str]:
        return [
            line.strip()
            for line in (_PROJECT_ROOT / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    @pytest.fixture(scope="class")
    def test_reqs(self) -> list[str]:
        return [
            line.strip()
            for line in (_PROJECT_ROOT / "requirements_test.txt")
            .read_text()
            .splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def test_main_requirements_have_specifier(self, main_reqs) -> None:
        for req in main_reqs:
            assert re.search(r"[<>=!~]", req), f"Unpinned: {req!r}"

    def test_test_requirements_have_specifier(self, test_reqs) -> None:
        for req in test_reqs:
            assert re.search(r"[<>=!~]", req), f"Unpinned: {req!r}"

    def test_test_requirements_known_packages(self, test_reqs) -> None:
        # Smoke check the line we previously feared was mangled.
        names = {re.split(r"[<>=!~]", req, maxsplit=1)[0] for req in test_reqs}
        assert "pytest" in names
        assert "aiohttp" in names
        assert "aioresponses" in names
        # Forbid the bogus combined name that the discovery agent flagged.
        assert "pyyamlpytest" not in names


class TestTranslationsParity:
    """en/it/es and strings.json must have identical key trees."""

    @pytest.fixture(scope="class")
    def translation_keys(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for name in ("en", "it", "es"):
            data = json.loads(
                (_INTEGRATION_DIR / "translations" / f"{name}.json").read_text()
            )
            out[name] = self._flat_keys(data)
        out["strings"] = self._flat_keys(
            json.loads((_INTEGRATION_DIR / "strings.json").read_text())
        )
        return out

    @staticmethod
    def _flat_keys(node: object, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        if isinstance(node, dict):
            for k, v in node.items():
                path = f"{prefix}.{k}".lstrip(".")
                keys.add(path)
                keys |= TestTranslationsParity._flat_keys(v, path)
        return keys

    def test_en_matches_it(self, translation_keys) -> None:
        assert translation_keys["en"] == translation_keys["it"]

    def test_en_matches_es(self, translation_keys) -> None:
        assert translation_keys["en"] == translation_keys["es"]

    def test_strings_matches_en(self, translation_keys) -> None:
        assert translation_keys["strings"] == translation_keys["en"]
