"""Replay and inert cohort adapters for settled Cost Governance cases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from fdai.shared.providers.cost_governance_decision import (
    CostCaseProjection,
    CostDecisionOutcome,
    CostDecisionRecord,
    CostEpisodeSettlement,
    CostLearningCohortInput,
    CostRecoveryAttempt,
    CostSettlementStatus,
)


def build_cost_case_projection(
    *,
    revision: int,
    decision: CostDecisionRecord,
    settlement: CostEpisodeSettlement | None,
    recovery_attempts: Sequence[CostRecoveryAttempt],
    evidence_refs: tuple[str, ...],
    terminal_audit_digest: str | None,
) -> CostCaseProjection:
    """Build one immutable Muninn replay projection from complete owned records."""

    attempts = tuple(recovery_attempts)
    lineage_complete = _lineage_complete(
        decision,
        settlement,
        terminal_audit_digest=terminal_audit_digest,
    )
    material = {
        "decision": {
            "decision_frame_digest": decision.decision_frame_digest,
            "outcome": decision.outcome.value,
            "reason": decision.reason,
            "terminal": decision.terminal,
        },
        "episode_id": decision.episode_id,
        "evidence_refs": sorted(set(evidence_refs)),
        "lineage_complete": lineage_complete,
        "recovery_attempts": [
            {
                "hypothesis_id": attempt.hypothesis_id,
                "input_frame_digest": attempt.input_frame_digest,
                "status": attempt.status.value,
                "step": attempt.step.value,
            }
            for attempt in attempts
        ],
        "revision": revision,
        "settlement": _settlement_material(settlement),
        "terminal_audit_digest": terminal_audit_digest,
    }
    digest = f"sha256:{hashlib.sha256(_canonical(material)).hexdigest()}"
    return CostCaseProjection(
        episode_id=decision.episode_id,
        revision=revision,
        decision=decision,
        settlement=settlement,
        recovery_attempts=attempts,
        evidence_refs=evidence_refs,
        terminal_audit_digest=terminal_audit_digest,
        lineage_complete=lineage_complete,
        projection_digest=digest,
    )


class CostLearningCohortCompiler:
    """Compile only complete positive-plus-negative cases into inert Norns input."""

    def compile(
        self,
        cases: Sequence[CostCaseProjection],
    ) -> CostLearningCohortInput | None:
        if len(cases) < 2 or len(cases) > 100:
            return None
        if any(not case.lineage_complete for case in cases):
            return None
        identities = {(case.episode_id, case.revision) for case in cases}
        if len(identities) != len(cases):
            return None
        positive = sum(_positive(case) for case in cases)
        negative = sum(_negative(case) for case in cases)
        if positive < 1 or negative < 1 or positive + negative != len(cases):
            return None
        case_refs = tuple(
            sorted(
                f"cost-case:{case.episode_id}:{case.revision}:"
                f"{case.projection_digest.removeprefix('sha256:')}"
                for case in cases
            )
        )
        lineage_digest = f"sha256:{hashlib.sha256(_canonical(case_refs)).hexdigest()}"
        cohort_digest = hashlib.sha256(_canonical((lineage_digest, case_refs))).hexdigest()
        cohort_id = f"cost-cohort:{cohort_digest}"
        return CostLearningCohortInput(
            cohort_id=cohort_id,
            case_refs=case_refs,
            positive_count=positive,
            negative_count=negative,
            lineage_digest=lineage_digest,
            inert=True,
        )


def _lineage_complete(
    decision: CostDecisionRecord,
    settlement: CostEpisodeSettlement | None,
    *,
    terminal_audit_digest: str | None,
) -> bool:
    if terminal_audit_digest is None:
        return False
    if decision.outcome in {CostDecisionOutcome.NO_OP, CostDecisionOutcome.DENY}:
        return decision.terminal
    if decision.outcome is CostDecisionOutcome.EXECUTE:
        return (
            settlement is not None
            and settlement.terminal
            and all(effect.terminal for effect in settlement.effects)
            and all(
                effect.status in {CostSettlementStatus.VERIFIED, CostSettlementStatus.FAILED}
                for effect in settlement.effects
            )
        )
    if decision.outcome is CostDecisionOutcome.ROLLBACK:
        return (
            settlement is not None
            and settlement.terminal
            and settlement.rollback_request is not None
            and settlement.recovery_observed
        )
    return False


def _positive(case: CostCaseProjection) -> bool:
    settlement = case.settlement
    return (
        case.decision.outcome is CostDecisionOutcome.EXECUTE
        and settlement is not None
        and settlement.rollback_request is None
        and settlement.realized_savings > 0
        and all(effect.status is CostSettlementStatus.VERIFIED for effect in settlement.effects)
    )


def _negative(case: CostCaseProjection) -> bool:
    if case.decision.outcome in {
        CostDecisionOutcome.NO_OP,
        CostDecisionOutcome.DENY,
        CostDecisionOutcome.ROLLBACK,
    }:
        return True
    settlement = case.settlement
    return settlement is not None and (
        settlement.rollback_request is not None
        or any(effect.status is CostSettlementStatus.FAILED for effect in settlement.effects)
    )


def _settlement_material(
    settlement: CostEpisodeSettlement | None,
) -> dict[str, object] | None:
    if settlement is None:
        return None
    return {
        "effects": [
            {
                "effect_id": effect.effect_id,
                "kind": effect.kind.value,
                "reason": effect.reason,
                "status": effect.status.value,
                "terminal": effect.terminal,
            }
            for effect in settlement.effects
        ],
        "realized_savings": str(settlement.realized_savings),
        "recovery_observed": settlement.recovery_observed,
        "rollback_request_id": (
            settlement.rollback_request.request_id
            if settlement.rollback_request is not None
            else None
        ),
        "terminal": settlement.terminal,
    }


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


__all__ = ["CostLearningCohortCompiler", "build_cost_case_projection"]
