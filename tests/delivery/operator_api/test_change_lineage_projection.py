"""Bounded read-only Operator projections for canonical Change lineage."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.change_lineage import (
    ChangeDecisionTrace,
    ChangeLineageRecord,
    ChangeObjectiveTrace,
    ChangeResilienceTrace,
    compute_change_lineage_id,
)
from fdai.delivery.operator_api.projections.change_lineage import (
    project_change_lineage_detail,
    project_change_lineage_summary,
)

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[3]


def _lineage(
    *,
    reason: str = "selected",
    evidence_refs: tuple[str, ...] = ("evidence:one", "evidence:two"),
) -> ChangeLineageRecord:
    effect = ChangeObjectiveTrace(
        objective_id="objective:availability",
        utility=0.8,
        confidence=0.9,
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observation_window_seconds=300,
    )
    decision = ChangeDecisionTrace(
        context_snapshot_id="context:one",
        selected_option_id="option:scale",
        option_scores=(("option:scale", 0.8),),
        margin=0.8,
        requires_human_approval=True,
        reason=reason,
        protected_objective_ids=(effect.objective_id,),
        active_constraint_ids=("constraint:one",),
        selected_effects=(effect,),
        violated_constraint_ids=(),
        proposing_agents=("forseti",),
        logic_receipt_refs=("logic:one",),
        simulation_receipt_refs=("simulation:one",),
        constraint_evaluation_refs=("constraint-evaluation:one",),
        assumptions=(),
        process_id=None,
        logic_release_digest="b" * 64,
    )
    resilience = ChangeResilienceTrace(
        execution_mode="shadow",
        blast_radius_scope="resource",
        blast_radius_count=1,
        rollback_kind="scripted",
        verification_status="hold",
        execution_outcome="shadowed",
        predicted_at=None,
        observation_deadline=None,
        observed_at=None,
        rollback_succeeded=None,
    )
    lineage_id = compute_change_lineage_id(
        change_id="change:one",
        change_source="github",
        change_ref="commit:abc",
        correlation_id="correlation:one",
        assessment_digest="c" * 64,
        decision_case_id="decision:one",
        selected_option_id=decision.selected_option_id,
        action_id="action:one",
        event_id="event:one",
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        outcome_id="outcome:one",
        outcome_label="unscorable",
        change_at=NOW,
        decision_at=NOW + timedelta(seconds=1),
        action_at=NOW + timedelta(seconds=2),
        outcome_at=NOW + timedelta(seconds=3),
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )
    return ChangeLineageRecord(
        lineage_id=lineage_id,
        change_id="change:one",
        change_source="github",
        change_ref="commit:abc",
        correlation_id="correlation:one",
        assessment_digest="c" * 64,
        decision_case_id="decision:one",
        selected_option_id=decision.selected_option_id,
        action_id="action:one",
        event_id="event:one",
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        outcome_id="outcome:one",
        outcome_label="unscorable",
        change_at=NOW,
        decision_at=NOW + timedelta(seconds=1),
        action_at=NOW + timedelta(seconds=2),
        outcome_at=NOW + timedelta(seconds=3),
        decision=decision,
        resilience=resilience,
        evidence_refs=evidence_refs,
    )


def test_summary_preserves_seal_gate_and_zero_authority() -> None:
    summary = project_change_lineage_summary(_lineage())

    assert summary.change_source == "github"
    assert summary.action_type_id == "ops.scale-out"
    assert summary.execution_mode == "shadow"
    assert summary.requires_human_approval is True
    assert summary.candidate_only is summary.requires_sealed_case is True
    assert summary.operational_reuse_eligible is False
    assert summary.execution_authority is summary.promotion_authority is False
    assert summary.to_mapping()["operational_reuse_eligible"] is False
    with pytest.raises(FrozenInstanceError):
        summary.action_type_id = "ops.restart"  # type: ignore[misc]


def test_detail_is_bounded_and_omits_raw_provider_content() -> None:
    evidence = tuple(f"evidence:{index:02d}" for index in range(40))
    detail = project_change_lineage_detail(_lineage(reason="r" * 800, evidence_refs=evidence))
    mapping = detail.to_mapping()

    assert len(detail.decision_reason) == 512
    assert detail.decision_reason_truncated is True
    assert detail.evidence_ref_count == 40
    assert len(detail.evidence_refs) == 32
    assert detail.evidence_truncated is True
    assert mapping["summary"]["execution_authority"] is False
    assert {"author", "metadata", "change_summary"}.isdisjoint(_mapping_keys(mapping))


def test_projection_rejects_oversized_identity_instead_of_truncating_it() -> None:
    lineage = _lineage()
    change_ref = "x" * 513
    lineage_id = compute_change_lineage_id(
        change_id=lineage.change_id,
        change_source=lineage.change_source,
        change_ref=change_ref,
        correlation_id=lineage.correlation_id,
        assessment_digest=lineage.assessment_digest,
        decision_case_id=lineage.decision_case_id,
        selected_option_id=lineage.selected_option_id,
        action_id=lineage.action_id,
        event_id=lineage.event_id,
        action_type_id=lineage.action_type_id,
        target_digest=lineage.target_digest,
        outcome_id=lineage.outcome_id,
        outcome_label=lineage.outcome_label,
        change_at=lineage.change_at,
        decision_at=lineage.decision_at,
        action_at=lineage.action_at,
        outcome_at=lineage.outcome_at,
        decision=lineage.decision,
        resilience=lineage.resilience,
        evidence_refs=lineage.evidence_refs,
    )
    with pytest.raises(ValueError, match="change_ref"):
        project_change_lineage_summary(
            replace(lineage, lineage_id=lineage_id, change_ref=change_ref)
        )


def test_projection_package_has_no_http_route_or_persistence_dependencies() -> None:
    package = _ROOT / "src/fdai/delivery/operator_api/projections/change_lineage"
    forbidden = (
        "starlette",
        "fdai.delivery.operator_api.routes",
        "fdai.delivery.operator_api.app",
        "fdai.delivery.persistence",
        "fdai.composition",
    )

    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            module == prefix or module.startswith(f"{prefix}.")
            for module in imports
            for prefix in forbidden
        )


def _mapping_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value} | {
            nested for child in value.values() for nested in _mapping_keys(child)
        }
    if isinstance(value, list | tuple):
        return {nested for child in value for nested in _mapping_keys(child)}
    return set()
