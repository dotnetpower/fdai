"""Focused tests for the machine-readable package assurance policy."""

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


def test_effect_bearing_level_cannot_drop_independent_verification() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    levels = policy["assurance_levels"]
    assert isinstance(levels, dict)
    effect_bearing = levels["effect-bearing"]
    assert isinstance(effect_bearing, dict)
    effect_bearing["independent_effect_verification"] = False

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("effect-bearing" in error for error in errors)


def test_effect_bearing_package_cannot_be_removed_or_downgraded() -> None:
    checker = _checker()
    removed = copy.deepcopy(_policy())
    packages = removed["packages"]
    assert isinstance(packages, list)
    removed["packages"] = [
        package
        for package in packages
        if not isinstance(package, dict) or package.get("id") != "fdai-deployment-cli"
    ]
    assert any(
        "authoritative package inventory" in error
        for error in checker.validate_policy(REPO_ROOT, removed)
    )

    downgraded = copy.deepcopy(_policy())
    packages = downgraded["packages"]
    assert isinstance(packages, list)
    deployment_cli = next(
        package
        for package in packages
        if isinstance(package, dict) and package.get("id") == "fdai-deployment-cli"
    )
    deployment_cli["assurance_level"] = "lockstep-shared"
    assert any(
        "fdai-deployment-cli MUST retain assurance level effect-bearing" in error
        for error in checker.validate_policy(REPO_ROOT, downgraded)
    )


def test_review_envelope_cannot_gain_authority() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    review = policy["review_envelope"]
    assert isinstance(review, dict)
    review["promotion_authority"] = True

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("review_envelope" in error for error in errors)


def test_connected_profile_does_not_require_complete_offline_kit() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    profiles = policy["artifact_profiles"]
    assert isinstance(profiles, dict)
    connected = profiles["connected"]
    assert isinstance(connected, dict)
    connected["complete_offline_kit_required"] = True

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("connected" in error for error in errors)


def test_connected_source_profile_does_not_require_deployment_root() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    profiles = policy["artifact_profiles"]
    assert isinstance(profiles, dict)
    connected = profiles["connected"]
    assert isinstance(connected, dict)
    connected["signed_root_required"] = True

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("signed-root" in error for error in errors)


def test_lifecycle_evidence_requires_restart_readback() -> None:
    checker = _checker()
    policy = copy.deepcopy(_policy())
    lifecycle = policy["lifecycle_evidence"]
    assert isinstance(lifecycle, dict)
    transitions = lifecycle["required_transitions"]
    assert isinstance(transitions, list)
    transitions.remove("restart")

    errors = checker.validate_policy(REPO_ROOT, policy)

    assert any("lifecycle_evidence" in error for error in errors)
