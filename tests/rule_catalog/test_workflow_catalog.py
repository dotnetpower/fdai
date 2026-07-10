"""Workflow catalog loader tests.

Covers:
- The shipped workflows load cleanly against the real ActionType catalog.
- Every shipped workflow defaults to shadow (the upstream invariant).
- Unknown `action_type_ref` / `compensated_by` fail-close.
- `guard_rule_ref` is validated only when `rule_ids` is supplied.
- Structural invariants (duplicate step id, unresolved `on_failure`,
  trigger payload) surface with a file + JSON pointer origin.
- Duplicate `name` across files fails-close.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.workflow import compile_workflow
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import (
    WorkflowCatalogError,
    load_workflow_catalog,
    load_workflow_from_mapping,
    workflow_names,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
PROBES_ROOT = REPO_ROOT / "rule-catalog" / "probes"
WORKFLOWS_ROOT = REPO_ROOT / "rule-catalog" / "workflows"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _action_type_names() -> set[str]:
    catalog = load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=_registry(),
        probes_root=PROBES_ROOT if PROBES_ROOT.is_dir() else None,
    )
    return {a.name for a in catalog}


def _base_mapping() -> dict:
    return {
        "schema_version": "1.0.0",
        "name": "sample-flow",
        "version": "1.0.0",
        "trigger": {"kind": "signal", "signal_type": "object.drift"},
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 14,
            "min_samples": 100,
            "min_accuracy": 0.95,
            "max_policy_escapes": 0,
        },
        "steps": [
            {"id": "step_one", "action_type_ref": "remediate.tag-add"},
        ],
    }


def test_shipped_workflows_load() -> None:
    catalog = load_workflow_catalog(
        WORKFLOWS_ROOT,
        schema_registry=_registry(),
        action_type_names=_action_type_names(),
    )
    names = workflow_names(catalog)
    assert {"cost-aware-remediation", "predictive-scale", "dr-failover-drill"} <= names


def test_every_shipped_workflow_defaults_to_shadow() -> None:
    catalog = load_workflow_catalog(
        WORKFLOWS_ROOT,
        schema_registry=_registry(),
        action_type_names=_action_type_names(),
    )
    for wf in catalog:
        assert wf.default_mode is Mode.SHADOW, (
            f"{wf.name}: upstream workflow must default to shadow"
        )


def test_shipped_workflow_action_refs_resolve() -> None:
    names = _action_type_names()
    catalog = load_workflow_catalog(
        WORKFLOWS_ROOT, schema_registry=_registry(), action_type_names=names
    )
    for wf in catalog:
        for step in wf.steps:
            assert step.action_type_ref in names
            if step.compensated_by is not None:
                assert step.compensated_by in names


def test_workflow_step_can_reference_a_tool_action_type() -> None:
    """The 'generate a document from a workflow' scenario: a workflow
    step references a tool.* ActionType by action_type_ref exactly like
    any mutation ActionType, so it inherits the four safety invariants.
    tool.generate-pdf is a shipped ActionType, so a real catalog resolves
    the reference."""
    names = _action_type_names()
    assert "tool.generate-pdf" in names

    raw = _base_mapping()
    raw["name"] = "generate-resilience-report"
    raw["steps"] = [{"id": "render", "action_type_ref": "tool.generate-pdf"}]
    wf = load_workflow_from_mapping(
        raw, schema_registry=_registry(), action_type_names=names
    )
    assert wf.steps[0].action_type_ref == "tool.generate-pdf"
    assert wf.default_mode is Mode.SHADOW


def test_shipped_workflows_compile_to_runbooks() -> None:
    catalog = load_workflow_catalog(
        WORKFLOWS_ROOT,
        schema_registry=_registry(),
        action_type_names=_action_type_names(),
    )
    for wf in catalog:
        compiled = compile_workflow(wf)
        assert compiled.runbook.id == wf.name
        assert [s.id for s in compiled.runbook.steps] == [s.id for s in wf.steps]
        assert [s.action_type for s in compiled.runbook.steps] == [
            s.action_type_ref for s in wf.steps
        ]
        # Shipped workflows are shadow-first.
        assert compiled.is_shadow is True


def test_empty_steps_rejected() -> None:
    raw = _base_mapping()
    raw["steps"] = []
    with pytest.raises(WorkflowCatalogError):
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )


def test_guard_rule_ref_resolves_when_present_in_rule_ids() -> None:
    raw = _base_mapping()
    raw["steps"][0]["guard_rule_ref"] = "known.rule"
    model = load_workflow_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.tag-add"},
        rule_ids={"known.rule", "other.rule"},
    )
    assert model.steps[0].guard_rule_ref == "known.rule"


def test_unknown_action_type_ref_fails() -> None:
    raw = _base_mapping()
    raw["steps"][0]["action_type_ref"] = "remediate.does-not-exist"
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown actiontype 'remediate.does-not-exist'" in joined


def test_unknown_compensated_by_fails() -> None:
    raw = _base_mapping()
    raw["steps"][0]["compensated_by"] = "ops.nope"
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    keys = " ".join(i.key for i in info.value.issues)
    assert "steps.step_one.compensated_by" in keys


def test_guard_rule_ref_validated_when_rule_ids_supplied() -> None:
    raw = _base_mapping()
    raw["steps"][0]["guard_rule_ref"] = "some.rule.id"
    # rule_ids provided but does not contain the ref -> fail.
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw,
            schema_registry=_registry(),
            action_type_names={"remediate.tag-add"},
            rule_ids={"other.rule"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown rule 'some.rule.id'" in joined


def test_guard_rule_ref_skipped_when_rule_ids_none() -> None:
    raw = _base_mapping()
    raw["steps"][0]["guard_rule_ref"] = "some.rule.id"
    # rule_ids None -> guard validation skipped, load succeeds.
    model = load_workflow_from_mapping(
        raw,
        schema_registry=_registry(),
        action_type_names={"remediate.tag-add"},
        rule_ids=None,
    )
    assert model.steps[0].guard_rule_ref == "some.rule.id"


def test_duplicate_step_id_fails() -> None:
    raw = _base_mapping()
    raw["steps"] = [
        {"id": "dup", "action_type_ref": "remediate.tag-add"},
        {"id": "dup", "action_type_ref": "remediate.tag-add"},
    ]
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate step id 'dup'" in joined


def test_unresolved_on_failure_fails() -> None:
    raw = _base_mapping()
    raw["steps"][0]["on_failure"] = "ghost"
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "on_failure -> unknown step 'ghost'" in joined


def test_self_referential_on_failure_fails() -> None:
    raw = _base_mapping()
    raw["steps"][0]["on_failure"] = "step_one"
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "points at itself" in joined


def test_backward_on_failure_fails() -> None:
    # A fallback that points at an EARLIER step would make the runner re-run an
    # already-applied step (double execution once the enforce path lands); the
    # forward-only invariant rejects it at load.
    raw = _base_mapping()
    raw["steps"] = [
        {"id": "first", "action_type_ref": "remediate.tag-add"},
        {"id": "second", "action_type_ref": "remediate.tag-add", "on_failure": "first"},
    ]
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "must appear later" in joined


def test_signal_trigger_requires_signal_type() -> None:
    raw = _base_mapping()
    raw["trigger"] = {"kind": "signal"}
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "signal_type" in joined


def test_schedule_trigger_requires_schedule() -> None:
    raw = _base_mapping()
    raw["trigger"] = {"kind": "schedule"}
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "schedule" in joined


def test_invalid_name_pattern_fails() -> None:
    raw = _base_mapping()
    raw["name"] = "Bad Name"
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_from_mapping(
            raw, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    keys = " ".join(i.key for i in info.value.issues)
    assert "name" in keys


def test_duplicate_name_across_files_fails(tmp_path: Path) -> None:
    body = (
        'schema_version: "1.0.0"\n'
        "name: dupe-flow\n"
        'version: "1.0.0"\n'
        "trigger:\n"
        "  kind: signal\n"
        "  signal_type: object.drift\n"
        "default_mode: shadow\n"
        "promotion_gate:\n"
        "  min_shadow_days: 14\n"
        "  min_samples: 100\n"
        "  min_accuracy: 0.95\n"
        "  max_policy_escapes: 0\n"
        "steps:\n"
        "  - id: only\n"
        "    action_type_ref: remediate.tag-add\n"
    )
    (tmp_path / "one.yaml").write_text(body)
    (tmp_path / "two.yaml").write_text(body)
    with pytest.raises(WorkflowCatalogError) as info:
        load_workflow_catalog(
            tmp_path, schema_registry=_registry(), action_type_names={"remediate.tag-add"}
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate workflow name 'dupe-flow'" in joined
