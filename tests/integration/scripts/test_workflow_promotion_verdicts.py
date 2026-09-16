from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

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
