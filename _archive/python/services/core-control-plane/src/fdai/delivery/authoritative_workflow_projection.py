"""Build deterministic workflow catalog projections for Operator."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _workflow_catalog(workflows: Sequence[Any], *, catalog_root: Path) -> dict[str, object]:
    """Project reviewed workflow declarations with their reviewed YAML source."""
    entries = [
        _workflow_entry(workflow, catalog_root=catalog_root)
        for workflow in sorted(workflows, key=lambda item: item.name)
    ]
    return {"workflows": entries, "count": len(entries)}


def _workflow_entry(workflow: Any, *, catalog_root: Path) -> dict[str, object]:
    source = catalog_root / "workflows" / f"{workflow.name}.yaml"
    gate = workflow.promotion_gate
    entry: dict[str, object] = {
        "schema_version": str(workflow.schema_version),
        "name": workflow.name,
        "version": str(workflow.version),
        "trigger": _workflow_trigger(workflow.trigger),
        "default_mode": str(workflow.default_mode),
        "promotion_gate": {
            "min_shadow_days": gate.min_shadow_days,
            "min_samples": gate.min_samples,
            "min_accuracy": gate.min_accuracy,
            "max_policy_escapes": gate.max_policy_escapes,
        },
        "steps": [_workflow_step(step) for step in workflow.steps],
        "step_count": len(workflow.steps),
        "yaml": source.read_text(encoding="utf-8") if source.is_file() else "",
    }
    if workflow.description is not None:
        entry["description"] = workflow.description
    anti_scope = getattr(workflow, "anti_scope", None)
    if anti_scope is not None:
        entry["anti_scope"] = anti_scope
    return entry


def _workflow_trigger(trigger: Any) -> dict[str, object]:
    projected: dict[str, object] = {"kind": str(trigger.kind)}
    signal_type = getattr(trigger, "signal_type", None)
    if signal_type is not None:
        projected["signal_type"] = str(signal_type)
    schedule = getattr(trigger, "schedule", None)
    if schedule is not None:
        projected["schedule"] = str(schedule)
    return projected


def _workflow_step(step: Any) -> dict[str, object]:
    projected: dict[str, object] = {"id": step.id}
    # A structured step (for example ``parallel``) carries branches, not an ActionType.
    action_type_ref = getattr(step, "action_type_ref", None)
    if action_type_ref is not None:
        projected["action_type_ref"] = str(action_type_ref)
    kind = getattr(step, "kind", None)
    if kind is not None:
        projected["kind"] = str(kind)
    branches = getattr(step, "branches", None)
    if branches:
        projected["branches"] = [str(branch) for branch in branches]
    outcomes = getattr(step, "outcomes", None)
    if outcomes:
        projected["outcomes"] = [str(outcome) for outcome in outcomes]
    for field in (
        "guard_rule_ref",
        "gate_ref",
        "compensated_by",
        "on_failure",
        "wait_for",
        "timeout_seconds",
        "approval_role",
    ):
        value = getattr(step, field, None)
        if value is not None:
            projected[field] = str(value)
    if kind is not None and str(kind) == "approval":
        projected["timeout_seconds"] = step.timeout_seconds
        projected["quorum"] = step.quorum
        projected["no_self_approval"] = step.no_self_approval
    elif kind is not None and str(kind) == "wait":
        projected["timeout_seconds"] = step.timeout_seconds
    params = getattr(step, "params", None)
    if params:
        projected["params"] = {key: params[key] for key in sorted(params)}
    return projected
