"""Canonical mapping codec for persisted adaptive investigation results."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from fdai.core.rca.discrimination import (
    CandidateRejection,
    CandidateRejectionReason,
    DiscriminationDisposition,
    DiscriminationHoldReason,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
)

from .adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    AdaptiveInvestigationIteration,
    AdaptiveInvestigationResult,
    AdaptiveObservationExecution,
    HypothesisRevisionSet,
)


def adaptive_result_to_mapping(result: AdaptiveInvestigationResult) -> dict[str, object]:
    """Serialize one validated terminal result without raw query values."""

    return {
        "session_id": result.session_id,
        "incident_id": result.incident_id,
        "workflow_version": result.workflow_version,
        "reducer_version": result.reducer_version,
        "active_strategy_digest": result.active_strategy_digest,
        "challenger_strategy_digest": result.challenger_strategy_digest,
        "budget": {
            "max_rounds": result.budget.max_rounds,
            "max_queries": result.budget.max_queries,
            "max_cost_units": result.budget.max_cost_units,
            "deadline_at": _timestamp_text(result.budget.deadline_at),
            "policy_digest": result.budget.policy_digest,
        },
        "iterations": [_iteration_to_mapping(item) for item in result.iterations],
        "disposition": result.disposition.value,
        "terminal_frame_digest": result.terminal_frame_digest,
        "terminal_active_set_receipt_digest": (result.terminal_active_set_receipt_digest),
        "used_queries": result.used_queries,
        "used_cost_units": result.used_cost_units,
        "result_digest": result.result_digest,
        "execution_authority": False,
        "mutation_authority": False,
        "promotion_authority": False,
    }


def adaptive_result_from_mapping(
    value: Mapping[str, Any],
) -> AdaptiveInvestigationResult:
    """Restore and revalidate one terminal result from its Process event."""

    budget = _mapping(value.get("budget"), "budget")
    iterations = value.get("iterations")
    if not isinstance(iterations, list):
        raise ValueError("adaptive persisted iterations MUST be an array")
    return AdaptiveInvestigationResult(
        session_id=_text(value, "session_id"),
        incident_id=_text(value, "incident_id"),
        workflow_version=_text(value, "workflow_version"),
        reducer_version=_text(value, "reducer_version"),
        active_strategy_digest=_text(value, "active_strategy_digest"),
        challenger_strategy_digest=_optional_text(
            value,
            "challenger_strategy_digest",
        ),
        budget=AdaptiveInvestigationBudget(
            max_rounds=_integer(budget, "max_rounds"),
            max_queries=_integer(budget, "max_queries"),
            max_cost_units=_integer(budget, "max_cost_units"),
            deadline_at=_timestamp(budget, "deadline_at"),
            policy_digest=_text(budget, "policy_digest"),
        ),
        iterations=tuple(
            _iteration_from_mapping(_mapping(item, "iteration")) for item in iterations
        ),
        disposition=AdaptiveInvestigationDisposition(_text(value, "disposition")),
        terminal_frame_digest=_text(value, "terminal_frame_digest"),
        terminal_active_set_receipt_digest=_text(
            value,
            "terminal_active_set_receipt_digest",
        ),
        used_queries=_integer(value, "used_queries"),
        used_cost_units=_integer(value, "used_cost_units"),
        result_digest=_text(value, "result_digest"),
        execution_authority=_false(value, "execution_authority"),
        mutation_authority=_false(value, "mutation_authority"),
        promotion_authority=_false(value, "promotion_authority"),
    )


def _iteration_to_mapping(
    iteration: AdaptiveInvestigationIteration,
) -> dict[str, object]:
    selection = iteration.selection
    return {
        "round_index": iteration.round_index,
        "frame": {
            "incident_id": iteration.frame.incident_id,
            "graph_revision": iteration.frame.graph_revision,
            "evidence_cutoff": _timestamp_text(iteration.frame.evidence_cutoff),
            "active_hypothesis_ids": list(iteration.frame.active_hypothesis_ids),
            "active_set_receipt_digest": (iteration.frame.active_set_receipt_digest),
            "cost_model_digest": iteration.frame.cost_model_digest,
            "frame_digest": iteration.frame.frame_digest,
        },
        "selection": {
            "selection_id": selection.selection_id,
            "selection_digest": selection.selection_digest,
            "frame_digest": selection.frame_digest,
            "method_version": selection.method_version,
            "disposition": selection.disposition.value,
            "candidate_digests": list(selection.candidate_digests),
            "rejected_candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "reason": item.reason.value,
                }
                for item in selection.rejected_candidates
            ],
            "total_pair_count": selection.total_pair_count,
            "separated_pair_count": selection.separated_pair_count,
            "selected_candidate_id": selection.selected_candidate_id,
            "hold_reason": (
                selection.hold_reason.value if selection.hold_reason is not None else None
            ),
        },
        "execution": (
            {
                "round_index": iteration.execution.round_index,
                "frame_digest": iteration.execution.frame_digest,
                "selection_digest": iteration.execution.selection_digest,
                "candidate_digest": iteration.execution.candidate_digest,
                "binding_digest": iteration.execution.binding_digest,
                "verification_receipt_digest": (iteration.execution.verification_receipt_digest),
                "plan_digest": iteration.execution.plan_digest,
                "result_digest": iteration.execution.result_digest,
                "query_status": iteration.execution.query_status,
                "evidence_refs": list(iteration.execution.evidence_refs),
                "reserved_cost_units": iteration.execution.reserved_cost_units,
                "actual_cost_units": iteration.execution.actual_cost_units,
                "execution_digest": iteration.execution.execution_digest,
            }
            if iteration.execution is not None
            else None
        ),
        "revision": (
            {
                "prior_active_set_receipt_digest": (
                    iteration.revision.prior_active_set_receipt_digest
                ),
                "prior_frame_digest": iteration.revision.prior_frame_digest,
                "observation_result_digest": (iteration.revision.observation_result_digest),
                "scorer_version": iteration.revision.scorer_version,
                "graph_revision": iteration.revision.graph_revision,
                "evidence_cutoff": _timestamp_text(iteration.revision.evidence_cutoff),
                "active_hypothesis_ids": list(iteration.revision.active_hypothesis_ids),
                "active_set_receipt_digest": (iteration.revision.active_set_receipt_digest),
                "evidence_refs": list(iteration.revision.evidence_refs),
                "complete": iteration.revision.complete,
                "truncated": iteration.revision.truncated,
                "disposition": iteration.revision.disposition.value,
                "revision_digest": iteration.revision.revision_digest,
            }
            if iteration.revision is not None
            else None
        ),
        "shadow_comparison_digest": iteration.shadow_comparison_digest,
        "iteration_digest": iteration.iteration_digest,
    }


def _iteration_from_mapping(
    value: Mapping[str, Any],
) -> AdaptiveInvestigationIteration:
    frame = _mapping(value.get("frame"), "frame")
    selection = _mapping(value.get("selection"), "selection")
    rejected = selection.get("rejected_candidates")
    if not isinstance(rejected, list):
        raise ValueError("adaptive persisted rejected candidates MUST be an array")
    execution = _optional_mapping(value.get("execution"), "execution")
    revision = _optional_mapping(value.get("revision"), "revision")
    return AdaptiveInvestigationIteration(
        round_index=_integer(value, "round_index"),
        frame=HypothesisDiscriminationFrame(
            incident_id=_text(frame, "incident_id"),
            graph_revision=_text(frame, "graph_revision"),
            evidence_cutoff=_timestamp(frame, "evidence_cutoff"),
            active_hypothesis_ids=_strings(
                frame,
                "active_hypothesis_ids",
            ),
            active_set_receipt_digest=_text(
                frame,
                "active_set_receipt_digest",
            ),
            cost_model_digest=_text(frame, "cost_model_digest"),
            frame_digest=_text(frame, "frame_digest"),
        ),
        selection=HypothesisDiscriminationSelection(
            selection_id=_text(selection, "selection_id"),
            selection_digest=_text(selection, "selection_digest"),
            frame_digest=_text(selection, "frame_digest"),
            method_version=_text(selection, "method_version"),
            disposition=DiscriminationDisposition(_text(selection, "disposition")),
            candidate_digests=_strings(selection, "candidate_digests"),
            rejected_candidates=tuple(
                CandidateRejection(
                    candidate_id=_text(
                        rejection_mapping := _mapping(item, "candidate rejection"),
                        "candidate_id",
                    ),
                    reason=CandidateRejectionReason(_text(rejection_mapping, "reason")),
                )
                for item in rejected
            ),
            total_pair_count=_integer(selection, "total_pair_count"),
            separated_pair_count=_integer(
                selection,
                "separated_pair_count",
            ),
            selected_candidate_id=_optional_text(
                selection,
                "selected_candidate_id",
            ),
            hold_reason=(
                DiscriminationHoldReason(hold_reason)
                if (hold_reason := _optional_text(selection, "hold_reason")) is not None
                else None
            ),
        ),
        execution=_execution_from_mapping(execution) if execution else None,
        revision=_revision_from_mapping(revision) if revision else None,
        shadow_comparison_digest=_optional_text(
            value,
            "shadow_comparison_digest",
        ),
        iteration_digest=_text(value, "iteration_digest"),
    )


def _execution_from_mapping(
    value: Mapping[str, Any],
) -> AdaptiveObservationExecution:
    return AdaptiveObservationExecution(
        round_index=_integer(value, "round_index"),
        frame_digest=_text(value, "frame_digest"),
        selection_digest=_text(value, "selection_digest"),
        candidate_digest=_text(value, "candidate_digest"),
        binding_digest=_text(value, "binding_digest"),
        verification_receipt_digest=_text(
            value,
            "verification_receipt_digest",
        ),
        plan_digest=_text(value, "plan_digest"),
        result_digest=_text(value, "result_digest"),
        query_status=_text(value, "query_status"),
        evidence_refs=_strings(value, "evidence_refs"),
        reserved_cost_units=_integer(value, "reserved_cost_units"),
        actual_cost_units=_optional_integer(value, "actual_cost_units"),
        execution_digest=_text(value, "execution_digest"),
    )


def _revision_from_mapping(value: Mapping[str, Any]) -> HypothesisRevisionSet:
    return HypothesisRevisionSet(
        prior_active_set_receipt_digest=_text(
            value,
            "prior_active_set_receipt_digest",
        ),
        prior_frame_digest=_text(value, "prior_frame_digest"),
        observation_result_digest=_text(value, "observation_result_digest"),
        scorer_version=_text(value, "scorer_version"),
        graph_revision=_text(value, "graph_revision"),
        evidence_cutoff=_timestamp(value, "evidence_cutoff"),
        active_hypothesis_ids=_strings(value, "active_hypothesis_ids"),
        active_set_receipt_digest=_text(value, "active_set_receipt_digest"),
        evidence_refs=_strings(value, "evidence_refs"),
        complete=_boolean(value, "complete"),
        truncated=_boolean(value, "truncated"),
        disposition=AdaptiveInvestigationDisposition(_text(value, "disposition")),
        revision_digest=_text(value, "revision_digest"),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"adaptive persisted {label} MUST be an object")
    return dict(value)


def _optional_mapping(value: object, label: str) -> dict[str, Any] | None:
    return None if value is None else _mapping(value, label)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"adaptive persisted {key} MUST be text")
    return item


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    return None if item is None else _text(value, key)


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 0:
        raise ValueError(f"adaptive persisted {key} MUST be an integer")
    return item


def _optional_integer(value: Mapping[str, Any], key: str) -> int | None:
    item = value.get(key)
    return None if item is None else _integer(value, key)


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"adaptive persisted {key} MUST be boolean")
    return item


def _false(value: Mapping[str, Any], key: str) -> Literal[False]:
    if value.get(key) is not False:
        raise ValueError(f"adaptive persisted {key} MUST be false")
    return False


def _timestamp(value: Mapping[str, Any], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"adaptive persisted {key} MUST be timezone-aware")
    return parsed


def _strings(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
        raise ValueError(f"adaptive persisted {key} MUST be strings")
    return tuple(items)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["adaptive_result_from_mapping", "adaptive_result_to_mapping"]
