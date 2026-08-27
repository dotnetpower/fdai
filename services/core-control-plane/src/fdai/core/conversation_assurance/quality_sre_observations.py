"""Qualification contributions from grounded RCA results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)
from fdai.core.impact_analysis.change_assessment import ChangeAssessment
from fdai.core.rca.contract import RcaOutcome, RcaResult, RootCauseHypothesis


@dataclass(frozen=True, slots=True)
class RcaScenarioResult:
    case_id: str
    expected_outcome: RcaOutcome
    expected_cause_digest: str | None
    expected_timeline_event_ids: tuple[str, str] | None
    actual: RcaResult
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class AlternativeCauseScenarioResult:
    case_id: str
    expected_cause_digests: tuple[str, ...]
    actual: tuple[RootCauseHypothesis, ...]
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class ImpactScenarioResult:
    case_id: str
    expected_resource_digests: tuple[str, ...]
    expected_complete: bool
    actual: ChangeAssessment
    evidence_digest: str


def observe_rca_scenario(
    result: RcaScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure triage, timeline, and supported cause without inventing RCA evidence."""

    _require_digest(result.evidence_digest)
    outcome_matches = result.actual.outcome is result.expected_outcome
    contributions = [
        _contribution(result, item_id=16, correct=outcome_matches, reason="rca_outcome_match")
    ]
    hypothesis = result.actual.hypothesis
    if result.expected_timeline_event_ids is not None or (
        hypothesis is not None and hypothesis.causal_chain is not None
    ):
        actual_timeline = (
            None
            if hypothesis is None or hypothesis.causal_chain is None
            else (
                hypothesis.causal_chain.root_event_id,
                hypothesis.causal_chain.failure_event_id,
            )
        )
        contributions.append(
            _contribution(
                result,
                item_id=17,
                correct=actual_timeline == result.expected_timeline_event_ids,
                reason="rca_timeline_match",
            )
        )
    actual_cause_digest = (
        None if hypothesis is None else hashlib.sha256(hypothesis.cause.encode()).hexdigest()
    )
    contributions.append(
        _contribution(
            result,
            item_id=18,
            correct=outcome_matches
            and actual_cause_digest == result.expected_cause_digest
            and (
                result.actual.outcome is RcaOutcome.ABSTAINED
                or (hypothesis is not None and hypothesis.grounded)
            ),
            reason="supported_cause_or_abstention_match",
        )
    )
    return tuple(contributions)


def observe_alternative_causes(
    result: AlternativeCauseScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 19 from the RCA owner's grounded candidate set."""

    _require_digest(result.evidence_digest)
    expected = tuple(sorted(set(result.expected_cause_digests)))
    if any(not _is_digest(value) for value in expected):
        raise ValueError("expected cause values MUST be SHA-256 digests")
    actual = tuple(
        sorted(
            hashlib.sha256(hypothesis.cause.encode()).hexdigest()
            for hypothesis in result.actual
            if hypothesis.grounded
        )
    )
    item = CHATOPS_QUALITY_CONTRACT_V1.items[18]
    return QualificationDimensionContribution(
        case_id=result.case_id,
        item_id=19,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if actual == expected else 0.0,
        reason_code="grounded_alternative_cause_set_match",
        evidence_ref_digests=(result.evidence_digest, _digest_payload(actual)),
    )


def observe_impact_scenario(
    result: ImpactScenarioResult,
) -> QualificationDimensionContribution:
    """Measure item 20 from the deterministic change impact assessment."""

    _require_digest(result.evidence_digest)
    expected = tuple(sorted(set(result.expected_resource_digests)))
    if any(not _is_digest(value) for value in expected):
        raise ValueError("expected resource values MUST be SHA-256 digests")
    actual = tuple(
        sorted(
            hashlib.sha256(resource_id.encode()).hexdigest()
            for resource_id in result.actual.affected_set.all_resource_ids
        )
    )
    item = CHATOPS_QUALITY_CONTRACT_V1.items[19]
    correct = actual == expected and result.actual.affected_set.complete is result.expected_complete
    return QualificationDimensionContribution(
        case_id=result.case_id,
        item_id=20,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code="impact_resource_set_and_completeness_match",
        evidence_ref_digests=(
            result.evidence_digest,
            result.actual.evidence_digest,
            _digest_payload(actual),
        ),
    )


def _contribution(
    result: RcaScenarioResult,
    *,
    item_id: int,
    correct: bool,
    reason: str,
) -> QualificationDimensionContribution:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    observed = {
        "outcome": result.actual.outcome.value,
        "reason_digest": hashlib.sha256(result.actual.reason.encode()).hexdigest(),
        "hypothesis": (
            None
            if result.actual.hypothesis is None
            else {
                "cause_digest": hashlib.sha256(result.actual.hypothesis.cause.encode()).hexdigest(),
                "grounded": result.actual.hypothesis.grounded,
                "causal_chain": (
                    None
                    if result.actual.hypothesis.causal_chain is None
                    else result.actual.hypothesis.causal_chain.to_dict()
                ),
            }
        ),
    }
    observed_digest = hashlib.sha256(
        json.dumps(observed, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return QualificationDimensionContribution(
        case_id=result.case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code=reason,
        evidence_ref_digests=(result.evidence_digest, observed_digest),
    )

def _require_digest(value: str) -> None:
    if not _is_digest(value):
        raise ValueError("scenario evidence_digest MUST be a lowercase SHA-256 digest")


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _digest_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


__all__ = [
    "AlternativeCauseScenarioResult",
    "ImpactScenarioResult",
    "RcaScenarioResult",
    "observe_alternative_causes",
    "observe_impact_scenario",
    "observe_rca_scenario",
]
