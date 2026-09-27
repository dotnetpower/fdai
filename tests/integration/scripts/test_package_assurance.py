"""Focused tests for the minimum package assurance policy."""

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


def _package(policy: dict[str, object], package_id: str) -> dict[str, object]:
    packages = policy["packages"]
    assert isinstance(packages, list)
    package = next(
        item for item in packages if isinstance(item, dict) and item.get("id") == package_id
    )
    return package


def test_repository_package_assurance_policy_is_valid() -> None:
    checker = _checker()
    assert checker.validate_policy(REPO_ROOT, _policy()) == []


def test_internal_packages_need_no_global_assurance_entry() -> None:
    checker = _checker()
    policy = _policy()
    packages = policy["packages"]
    assert isinstance(packages, list)
    package_ids = {item["id"] for item in packages if isinstance(item, dict)}

    assert checker.validate_policy(REPO_ROOT, policy) == []
    assert package_ids.isdisjoint(
        {
            "fdai-github-app-auth",
            "fdai-runtime-diagnostics",
            "fdai-code-assurance",
            "fdai-aks-commerce",
        }
    )


def test_distributed_artifact_cannot_drop_integrity_or_provenance() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    package = _package(policy, "fdai-deployment-cli")
    package["required_controls"] = ["exact-digest"]

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("boundary minimums" in error and "provenance" in error for error in errors)


def test_published_contract_requires_versioning_not_global_n_minus_one() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    package = _package(policy, "fdai-service-contracts")
    package["required_controls"] = []

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("versioned-contract" in error for error in errors)
    assert all("n-minus-one" not in error for error in errors)


def test_connected_profile_requires_only_declared_closure_digest_and_provenance() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    profiles = policy["artifact_profiles"]
    assert isinstance(profiles, dict)
    connected = profiles["connected"]
    assert isinstance(connected, dict)
    connected["recommended_controls"] = []

    assert checker.validate_policy(REPO_ROOT, policy) == []


def test_offline_profile_cannot_drop_signed_root_or_no_public_fallback() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    profiles = policy["artifact_profiles"]
    assert isinstance(profiles, dict)
    offline = profiles["offline"]
    assert isinstance(offline, dict)
    offline["required_controls"] = [
        "declared-dependency-closure",
        "exact-digest",
        "provenance",
    ]

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("no-public-fallback" in error and "signed-root" in error for error in errors)


def test_recommended_controls_never_become_hidden_hard_gates() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    profiles = policy["artifact_profiles"]
    assert isinstance(profiles, dict)
    for profile in profiles.values():
        assert isinstance(profile, dict)
        profile["recommended_controls"] = []

    assert checker.validate_policy(REPO_ROOT, policy) == []


def test_owner_can_add_a_known_stronger_control() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    package = _package(policy, "fdai-deployment-cli")
    controls = package["required_controls"]
    assert isinstance(controls, list)
    controls.append("sbom")

    assert checker.validate_policy(REPO_ROOT, policy) == []


def test_package_operations_and_enablement_cannot_grant_authority() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    invariants = policy["runtime_invariants"]
    assert isinstance(invariants, dict)
    invariants["package_operation_grants_authority"] = True

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("package_operation_grants_authority" in error for error in errors)


def test_state_change_success_keeps_independent_verification() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    invariants = policy["runtime_invariants"]
    assert isinstance(invariants, dict)
    invariants["state_change_success_requires_independent_verification"] = False

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any(
        "state_change_success_requires_independent_verification" in error for error in errors
    )


def test_unknown_controls_and_typo_fields_fail_closed() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    package = _package(policy, "fdai-deployment-cli")
    controls = package["required_controls"]
    assert isinstance(controls, list)
    controls.append("ceremony-for-everything")
    package["assurance_level"] = "effect-bearing"

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("unsupported controls" in error for error in errors)
    assert any("unsupported fields" in error for error in errors)
