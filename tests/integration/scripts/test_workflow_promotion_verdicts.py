from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-workflow-promotion-verdicts.py"
    name = "check_workflow_promotion_verdicts"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _document(module: ModuleType) -> dict[str, Any]:
    raw = json.loads((REPO_ROOT / module.MANIFEST_REF).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(dict[str, Any], raw)


def test_repository_workflow_promotion_verdicts_are_complete() -> None:
    module = _load_module()

    assert module.validate() == []


def test_a_new_or_omitted_workflow_requires_a_verdict() -> None:
    module = _load_module()
    document = _document(module)
    document["verdicts"] = document["verdicts"][:-1]

    errors = module.validate_document(document)

    assert any("missing workflow verdicts" in error for error in errors)
    assert any("summary does not match" in error for error in errors)


def test_a_changed_workflow_invalidates_its_definition_digest() -> None:
    module = _load_module()
    document = _document(module)
    document["verdicts"][0]["definition_digest"] = "0" * 64

    errors = module.validate_document(document)

    assert any("cost-aware-remediation definition_digest is stale" in error for error in errors)


def test_the_inventory_cannot_grant_authority_or_change_mode() -> None:
    module = _load_module()
    document = _document(module)
    document["authority"]["grants_execution_authority"] = True
    document["verdicts"][0]["current_mode"] = "enforce"

    errors = module.validate_document(document)

    assert any("grants_execution_authority" in error for error in errors)
    assert any("current_mode" in error for error in errors)


def test_only_the_judge_only_workflow_can_be_permanently_shadow() -> None:
    module = _load_module()
    document = _document(module)
    record = document["verdicts"][0]
    record["verdict"] = "permanent_shadow"
    record["evidence_status"] = {
        "shadow_duration": "not_applicable",
        "kpi_baseline": "not_applicable",
        "guard_regression": "not_applicable",
        "policy_escapes": "not_applicable",
        "trace": "implementation_only",
    }
    record["blocking_reasons"] = ["judge_only_workflow"]
    document["summary"] = {
        "workflow_count": 13,
        "deferred": 11,
        "permanent_shadow": 2,
    }

    errors = module.validate_document(document)

    assert any("cost-aware-remediation lacks a safe deferral" in error for error in errors)


def test_deferral_requires_every_named_missing_evidence_class() -> None:
    module = _load_module()
    document = copy.deepcopy(_document(module))
    record = document["verdicts"][0]
    record["blocking_reasons"].remove("policy_escape_observation_missing")

    errors = module.validate_document(document)

    assert any(
        "cost-aware-remediation deferral evidence is inconsistent" in error for error in errors
    )


def test_trace_and_owner_references_must_resolve() -> None:
    module = _load_module()
    document = _document(module)
    record = document["verdicts"][0]
    record["trace_ref"] = "tests/missing.py::test_missing"
    record["evidence_refs"][-1] = "tests/missing.py::test_missing"

    errors = module.validate_document(document)

    assert any("trace_ref is stale" in error for error in errors)
    assert any("trace_ref does not resolve" in error for error in errors)
    assert any("evidence reference does not exist" in error for error in errors)


def test_catalog_boundary_requires_every_metadata_workflow() -> None:
    module = _load_module()
    document = _document(module)
    document["catalog_boundary"]["entries"] = document["catalog_boundary"]["entries"][:-1]

    errors = module.validate_document(document)

    assert any("missing catalog-boundary workflows" in error for error in errors)
    assert any("catalog-boundary entries MUST follow registry order" in error for error in errors)


def test_catalog_boundary_uses_exact_id_matches_not_similar_workflows() -> None:
    module = _load_module()
    document = _document(module)
    record = next(
        item
        for item in document["catalog_boundary"]["entries"]
        if item["workflow_id"] == "dr-drill-orchestration"
    )
    record["disposition"] = "cataloged"
    record["catalog_definitions"] = [
        {
            "catalog_ref": "rule-catalog/workflows/dr-failover-drill.yaml",
            "definition_digest": "0" * 64,
        }
    ]
    document["catalog_boundary"]["summary"] = {
        "workflow_count": 13,
        "cataloged": 3,
        "metadata_only": 10,
        "executable_count": 16,
        "independent": 14,
    }

    errors = module.validate_document(document)

    assert any("dr-drill-orchestration catalog disposition is stale" in error for error in errors)
    assert any("dr-drill-orchestration catalog definitions are stale" in error for error in errors)


def test_catalog_boundary_rejects_ambiguous_exact_id_entries(monkeypatch: Any) -> None:
    module = _load_module()
    document = _document(module)
    original = module._catalog_definitions_by_workflow_id

    def duplicate_definitions(root: Path) -> dict[str, tuple[tuple[str, str], ...]]:
        definitions = cast(dict[str, tuple[tuple[str, str], ...]], original(root))
        definitions["predictive-scale"] = (
            ("rule-catalog/workflows/predictive-scale.yaml", "0" * 64),
            (
                "extensions/example/src/example/resources/workflows/predictive-scale.yaml",
                "1" * 64,
            ),
        )
        return definitions

    monkeypatch.setattr(module, "_catalog_definitions_by_workflow_id", duplicate_definitions)

    errors = module.validate_document(document)

    assert any(
        "predictive-scale executable catalog identity is ambiguous" in error for error in errors
    )


def test_catalog_boundary_requires_every_independent_executable_workflow() -> None:
    module = _load_module()
    document = _document(module)
    document["catalog_boundary"]["independent_entries"] = document["catalog_boundary"][
        "independent_entries"
    ][:-1]

    errors = module.validate_document(document)

    assert any("missing independent executable workflows" in error for error in errors)


@pytest.mark.parametrize("field", ["trigger", "steps", "default_mode", "promotion_gate"])
def test_executable_semantic_drift_invalidates_catalog_definition(
    monkeypatch: Any,
    field: str,
) -> None:
    module = _load_module()
    document = _document(module)
    path = REPO_ROOT / "rule-catalog/workflows/predictive-scale.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    mutated = copy.deepcopy(raw)
    if field == "trigger":
        mutated["trigger"]["schedule"] = "5 * * * *"
    elif field == "steps":
        mutated["steps"].append({"id": "unexpected", "action_type_ref": "ops.restart-service"})
    elif field == "default_mode":
        mutated["default_mode"] = "enforce"
    else:
        mutated["promotion_gate"]["min_shadow_days"] = 1
    original = module._catalog_definitions_by_workflow_id

    def changed_definitions(root: Path) -> dict[str, tuple[tuple[str, str], ...]]:
        definitions = cast(dict[str, tuple[tuple[str, str], ...]], original(root))
        definitions["predictive-scale"] = (
            (
                "rule-catalog/workflows/predictive-scale.yaml",
                module._workflow_yaml_digest(mutated),
            ),
        )
        return definitions

    monkeypatch.setattr(module, "_catalog_definitions_by_workflow_id", changed_definitions)

    errors = module.validate_document(document)

    assert any("predictive-scale catalog definitions are stale" in error for error in errors)
