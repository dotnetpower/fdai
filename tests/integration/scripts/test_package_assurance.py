"""Focused tests for the minimal signed-package inventory."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts/quality/architecture/check-package-assurance.py"
POLICY_PATH = REPO_ROOT / "config/package-assurance.json"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_package_assurance", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _policy() -> dict[str, object]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_repository_package_assurance_policy_is_valid() -> None:
    checker = _checker()

    assert checker.validate_policy(REPO_ROOT, _policy()) == []


def test_only_explicitly_distributed_packages_are_listed() -> None:
    policy = _policy()

    assert policy["packages"] == [
        {
            "id": "fdai-deployment-cli",
            "path": "packages/deployment-cli",
            "manifest": "packages/deployment-cli/pyproject.toml",
        }
    ]


def test_signature_contract_has_one_supported_shape() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    policy["signature"] = {
        "algorithm": "rsa",
        "format": "nested-trust-ceremony",
    }

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert errors == ["signature must select ed25519 with the detached-sha256sums format"]


def test_package_manifest_name_must_match_the_distribution() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    packages = policy["packages"]
    assert isinstance(packages, list)
    package = packages[0]
    assert isinstance(package, dict)
    package["id"] = "renamed-package"

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("project.name must equal renamed-package" in error for error in errors)


def test_duplicate_packages_and_unknown_policy_fields_fail() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    packages = policy["packages"]
    assert isinstance(packages, list)
    packages.append(copy.deepcopy(packages[0]))
    policy["artifact_profiles"] = {"offline": {}}

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("unsupported fields: artifact_profiles" in error for error in errors)
    assert any(".id is duplicated" in error for error in errors)
    assert any(".path is duplicated" in error for error in errors)
