"""Owned native-JSON candidate snapshots shared by the gate and its T2 consumer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.compatibility import canonical_digest
from pydantic import JsonValue, TypeAdapter

from fdai.core.quality_gate.deterministic_evidence import quality_candidate_digest

if TYPE_CHECKING:
    from fdai.core.quality_gate.gate import QualityCandidate, QualityDecision

_JSON_PARAMS = TypeAdapter(dict[str, JsonValue])


def snapshot_candidate_params(
    candidate: QualityCandidate, params: Mapping[str, Any]
) -> dict[str, Any]:
    """Copy native JSON without coercion, then validate the exact evidence identity."""
    snapshot = _JSON_PARAMS.validate_python(dict(params), strict=True)
    quality_candidate_digest(replace(candidate, params=snapshot))
    return snapshot


def snapshot_quality_candidate(candidate: QualityCandidate) -> QualityCandidate:
    """Detach provider-owned arguments and derived confidence before asynchronous verification."""
    return replace(
        candidate,
        params=snapshot_candidate_params(candidate, candidate.params),
        confidence_signals=dict(candidate.confidence_signals),
    )


def quality_candidate_evaluation_identity(candidate: QualityCandidate) -> tuple[str, str]:
    """Bind exact action evidence and the confidence that may lower or hold eligibility."""
    return quality_candidate_digest(candidate), canonical_digest(dict(candidate.confidence_signals))


async def evaluate_candidate_snapshot(
    candidate: QualityCandidate,
    *,
    evaluator: Callable[[QualityCandidate], Awaitable[QualityDecision]],
) -> QualityDecision:
    """Keep caller, evaluator and returned evidence on one owned candidate through all awaits."""
    from fdai.core.quality_gate.gate import QualityDecision, QualityOutcome

    try:
        baseline = snapshot_quality_candidate(candidate)
        identity = quality_candidate_evaluation_identity(baseline)
        working = snapshot_quality_candidate(baseline)
    except (TypeError, ValueError, RecursionError) as exc:
        return QualityDecision(
            outcome=QualityOutcome.ABSTAIN,
            candidate=candidate,
            reasons=(f"candidate_snapshot_invalid:{type(exc).__name__}",),
        )
    decision = await evaluator(working)
    try:
        unchanged = (
            quality_candidate_evaluation_identity(candidate) == identity
            and quality_candidate_evaluation_identity(working) == identity
            and quality_candidate_evaluation_identity(decision.candidate) == identity
        )
    except (TypeError, ValueError, RecursionError):
        unchanged = False
    if not unchanged:
        return QualityDecision(
            outcome=QualityOutcome.ABSTAIN,
            candidate=baseline,
            reasons=("candidate_changed_during_verification",),
        )
    return replace(decision, candidate=baseline)
