from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = (
    REPO_ROOT / "scripts/quality/architecture/check-cost-governance-package-convergence.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_cost_governance_package_convergence",
        CHECKER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def snapshot(checker: ModuleType) -> dict[str, Any]:
    return checker.load_repository_snapshot()


def test_repository_w0_w1_w2_contracts_converge(checker: ModuleType) -> None:
    assert checker.validate_repository() == {
        "vertical_id": "cost-governance",
        "ontology_release_digest": (
            "sha256:900b922381ea7326ae20a36cb5dea6d3f918655b6e9fb786ff5d9e328a5715c7"
        ),
        "semantic_profile_sha256": (
            "sha256:d119843fb870a779c038a879c4f0890abffb1cc5a70f418a2de3941af4b46208"
        ),
        "cost_rules": 12,
        "package_assets": 38,
    }


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("inventory.package_identity", "vertical_id", "cost-governance-drift", "identity"),
        ("package_manifest", "package_id", "cost-governance-drift", "identity"),
        ("bundle", "extension_id", "cost-governance-drift", "identity"),
        ("bundle", "descriptor_vertical_id", "cost-governance-drift", "identity"),
        ("root", "package_distribution", "fdai-cost-drift", "distribution"),
        ("root", "package_namespace", "fdai_cost_drift", "namespace"),
    ],
)
def test_identity_mutations_are_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    section: str,
    field: str,
    value: str,
    message: str,
) -> None:
    mutated = deepcopy(snapshot)
    target: dict[str, Any] = mutated
    if section != "root":
        for part in section.split("."):
            target = target[part]
    target[field] = value

    assert any(message in error for error in checker.validate_convergence_data(mutated))


def test_exact_ontology_release_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["bundle"]["ontology_release_digest"] = "sha256:" + ("0" * 64)

    assert "exact ontology release digest drift" in checker.validate_convergence_data(mutated)


def test_packaged_manifest_digest_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["bundle"]["asset_manifest_sha256"] = "0" * 64

    assert "packaged manifest digest drift" in checker.validate_convergence_data(mutated)


@pytest.mark.parametrize(
    ("location", "message"),
    [
        ("profile", "semantic profile canonical digest drift"),
        ("bundle", "semantic profile canonical digest drift"),
        ("manifest", "semantic profile resource digest drift"),
    ],
)
def test_semantic_profile_digest_mutations_are_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    location: str,
    message: str,
) -> None:
    mutated = deepcopy(snapshot)
    if location == "profile":
        mutated["profile"]["canonical_sha256"] = "sha256:" + ("0" * 64)
    elif location == "bundle":
        mutated["bundle"]["semantic_profile_sha256"] = "sha256:" + ("0" * 64)
    else:
        semantic = next(
            item
            for item in mutated["package_manifest"]["assets"]
            if item["id"] == "semantic-profile:cost-governance"
        )
        semantic["sha256"] = "0" * 64

    assert message in checker.validate_convergence_data(mutated)


@pytest.mark.parametrize("source", ["inventory", "package_manifest"])
def test_stable_rule_id_mutations_are_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    source: str,
) -> None:
    mutated = deepcopy(snapshot)
    if source == "inventory":
        mutated["inventory"]["cost_rule_bindings"][0]["rule_id"] = "cache.drift"
    else:
        rule = next(
            item
            for item in mutated["package_manifest"]["assets"]
            if item["id"] == "rule:cache.tier-overprovisioned"
        )
        rule["id"] = "rule:cache.drift"

    assert any(
        "stable cost rule id drift" in error for error in checker.validate_convergence_data(mutated)
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "rule_path",
            "rule-catalog/catalog/cache.drift.yaml",
            "rule_path",
        ),
        ("policy_path", "policies/cache/drift.rego", "policy_path"),
        (
            "remediation_path",
            "rule-catalog/remediation/cache/drift.tftpl",
            "remediation_path",
        ),
        ("action_type_id", "remediate.drift", "references drift"),
        (
            "action_type_path",
            "rule-catalog/action-types/remediate.drift.yaml",
            "ActionType path",
        ),
    ],
)
def test_rule_graph_reference_mutations_are_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    field: str,
    value: str,
    message: str,
) -> None:
    mutated = deepcopy(snapshot)
    mutated["inventory"]["cost_rule_bindings"][0][field] = value

    assert any(message in error for error in checker.validate_convergence_data(mutated))


def test_packaged_rule_reference_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    rule = next(
        item
        for item in mutated["package_manifest"]["assets"]
        if item["id"] == "rule:cache.tier-overprovisioned"
    )
    rule["references"][0] = "action:remediate.drift"

    assert any("references drift" in error for error in checker.validate_convergence_data(mutated))


def test_candidate_state_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["package_manifest"]["candidate_state"] = "enabled"

    assert "package candidate state must remain inert" in (
        checker.validate_convergence_data(mutated)
    )


@pytest.mark.parametrize("location", ["manifest", "bundle", "inventory"])
def test_package_version_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    location: str,
) -> None:
    mutated = deepcopy(snapshot)
    if location == "manifest":
        mutated["package_manifest"]["package_version"] = "0.1.2"
    elif location == "bundle":
        mutated["bundle"]["package_version"] = "0.1.2"
    else:
        mutated["inventory"]["w6_cutover"]["package_version"] = "0.1.2"

    assert any(
        "exact package version drift" in error
        for error in checker.validate_convergence_data(mutated)
    )


def test_active_base_asset_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["active_base_asset_paths"] = ["policies/cache/tier_overprovisioned.rego"]

    assert any(
        "base catalog retains package-owned assets" in error
        for error in checker.validate_convergence_data(mutated)
    )


@pytest.mark.parametrize("field", ["base_action_types_present", "base_ontology_present"])
def test_generic_base_contract_removal_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
    field: str,
) -> None:
    mutated = deepcopy(snapshot)
    mutated[field] = False

    assert checker.validate_convergence_data(mutated)


def test_package_asset_count_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["package_manifest"]["assets"] = [
        item
        for item in mutated["package_manifest"]["assets"]
        if item["id"] != "policy:cache.tier-overprovisioned"
    ]

    assert any(
        "package asset ownership counts drift" in error
        for error in checker.validate_convergence_data(mutated)
    )


def test_workflow_reference_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    workflow = next(
        item
        for item in mutated["package_manifest"]["assets"]
        if item["id"] == "workflow:cost-aware-remediation"
    )
    workflow["references"] = ["action:remediate.drift"]

    assert any(
        "workflow references drift" in error for error in checker.validate_convergence_data(mutated)
    )


def test_core_import_mutation_is_detected(
    checker: ModuleType,
    snapshot: dict[str, Any],
) -> None:
    mutated = deepcopy(snapshot)
    mutated["core_imports"] = ["services/core-control-plane/src/fdai/composition.py:1"]

    assert any(
        "Core imports fdai_cost_governance" in error
        for error in checker.validate_convergence_data(mutated)
    )


@pytest.mark.parametrize(
    "source",
    [
        "import fdai_cost_governance\n",
        "from fdai_cost_governance.resource_loader import load_resource_manifest\n",
    ],
)
def test_core_import_scanner_detects_forbidden_import_syntax(
    checker: ModuleType,
    source: str,
) -> None:
    assert checker._forbidden_imports(source, "fdai/core/example.py") == ("fdai/core/example.py:1",)
