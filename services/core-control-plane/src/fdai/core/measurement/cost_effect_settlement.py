"""Independent multi-effect settlement for Cost Governance episodes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from fdai.shared.providers.cost_governance_decision import (
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostEffectSettlement,
    CostEpisodeSettlement,
    CostExpectedEffect,
    CostInterventionObservation,
    CostObservationLane,
    CostPostRecoveryObservation,
    CostRollbackRequest,
    CostSettlementStatus,
)


class CostEffectSettlementService:
    """Settle effects only from complete independent post-horizon observations."""

    def settle(
        self,
        *,
        episode_id: str,
        decision_frame_digest: str,
        expected_effects: Sequence[CostExpectedEffect],
        observations: Sequence[CostEffectObservation],
        completeness_receipts: Sequence[CostCompletenessReceipt],
        interventions: Sequence[CostInterventionObservation],
        evaluated_at: datetime,
        evidence_refs: tuple[str, ...],
        stop_condition_triggered: bool = False,
        post_recovery_observation: CostPostRecoveryObservation | None = None,
    ) -> CostEpisodeSettlement:
        """Return a replay-stable settlement without accepting executor output."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("settlement evaluation time MUST be timezone-aware")
        expected = tuple(expected_effects)
        if not expected or len({item.effect_id for item in expected}) != len(expected):
            raise ValueError("expected effects MUST be non-empty and unique")
        observed_by_effect = _one_per_effect(observations, "observation")
        completeness_by_effect = _one_per_effect(completeness_receipts, "completeness receipt")
        settlements = tuple(
            self._settle_effect(
                effect,
                observation=observed_by_effect.get(effect.effect_id),
                completeness=completeness_by_effect.get(effect.effect_id),
                interventions=interventions,
                evaluated_at=evaluated_at,
            )
            for effect in expected
        )
        failed_effects = tuple(
            item.effect_id for item in settlements if item.status is CostSettlementStatus.FAILED
        )
        rollback_request = None
        if failed_effects or stop_condition_triggered:
            affected = failed_effects or tuple(effect.effect_id for effect in expected)
            rollback_request = _rollback_request(
                episode_id=episode_id,
                decision_frame_digest=decision_frame_digest,
                failed_effect_ids=affected,
                stop_condition_triggered=stop_condition_triggered,
                requested_at=evaluated_at,
                evidence_refs=evidence_refs,
            )
        recovery_observed = _recovery_observed(
            rollback_request,
            post_recovery_observation,
        )
        effects_terminal = all(item.terminal for item in settlements)
        terminal = effects_terminal and (rollback_request is None or recovery_observed)
        realized = self._realized_savings(
            expected,
            observations=observed_by_effect,
            settlements=settlements,
            terminal=terminal,
            rollback_request=rollback_request,
        )
        return CostEpisodeSettlement(
            episode_id=episode_id,
            decision_frame_digest=decision_frame_digest,
            effects=settlements,
            terminal=terminal,
            realized_savings=realized,
            rollback_request=rollback_request,
            recovery_observed=recovery_observed,
            settled_at=evaluated_at,
        )

    @staticmethod
    def _settle_effect(
        effect: CostExpectedEffect,
        *,
        observation: CostEffectObservation | None,
        completeness: CostCompletenessReceipt | None,
        interventions: Sequence[CostInterventionObservation],
        evaluated_at: datetime,
    ) -> CostEffectSettlement:
        intervention = next(
            (
                item
                for item in sorted(
                    interventions,
                    key=lambda candidate: (
                        candidate.effective_at,
                        candidate.intervention_id,
                    ),
                )
                if item.target_ref == effect.target_ref
                and effect.predicted_at < item.effective_at <= effect.deadline_at
            ),
            None,
        )
        if intervention is not None:
            return _effect_result(
                effect,
                CostSettlementStatus.CENSORED,
                "intervention_detected",
                terminal=True,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=completeness,
            )

        window_closed = evaluated_at >= effect.deadline_at
        if effect.estimated_only:
            return _effect_result(
                effect,
                CostSettlementStatus.UNSCORABLE,
                "estimated_only",
                terminal=window_closed,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=completeness,
            )
        if completeness is None:
            return _effect_result(
                effect,
                CostSettlementStatus.UNSCORABLE,
                "completeness_missing",
                terminal=window_closed,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=None,
            )
        if (
            completeness.effect_id != effect.effect_id
            or completeness.effect_source_digest != effect.source_digest
            or completeness.lane is not CostObservationLane.INDEPENDENT
            or not completeness.complete
            or completeness.coverage_through_at < effect.horizon_ends_at
        ):
            return _effect_result(
                effect,
                CostSettlementStatus.UNSCORABLE,
                "telemetry_incomplete",
                terminal=window_closed,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=completeness,
            )
        if observation is None:
            return _effect_result(
                effect,
                CostSettlementStatus.UNSCORABLE,
                "independent_observation_missing",
                terminal=window_closed,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=completeness,
            )
        valid_observation = (
            observation.effect_id == effect.effect_id
            and observation.effect_source_digest == effect.source_digest
            and observation.target_ref == effect.target_ref
            and observation.metric == effect.metric
            and observation.lane is CostObservationLane.INDEPENDENT
            and effect.horizon_ends_at <= observation.observed_at <= effect.deadline_at
        )
        if not valid_observation:
            return _effect_result(
                effect,
                CostSettlementStatus.UNSCORABLE,
                "independent_observation_invalid",
                terminal=window_closed,
                evaluated_at=evaluated_at,
                observation=None,
                completeness=completeness,
            )
        if effect.acceptable_min <= observation.value <= effect.acceptable_max:
            return _effect_result(
                effect,
                CostSettlementStatus.VERIFIED,
                "expected_effect_observed",
                terminal=True,
                evaluated_at=evaluated_at,
                observation=observation,
                completeness=completeness,
            )
        return _effect_result(
            effect,
            CostSettlementStatus.FAILED,
            "expected_effect_failed",
            terminal=True,
            evaluated_at=evaluated_at,
            observation=observation,
            completeness=completeness,
        )

    @staticmethod
    def _realized_savings(
        expected_effects: tuple[CostExpectedEffect, ...],
        *,
        observations: dict[str, CostEffectObservation],
        settlements: tuple[CostEffectSettlement, ...],
        terminal: bool,
        rollback_request: CostRollbackRequest | None,
    ) -> Decimal:
        if (
            not terminal
            or rollback_request is not None
            or any(item.status is not CostSettlementStatus.VERIFIED for item in settlements)
        ):
            return Decimal("0")
        status_by_effect = {item.effect_id: item.status for item in settlements}
        return sum(
            (
                max(
                    Decimal("0"),
                    effect.baseline_value - observations[effect.effect_id].value,
                )
                for effect in expected_effects
                if effect.kind is CostEffectKind.COST
                and not effect.estimated_only
                and status_by_effect[effect.effect_id] is CostSettlementStatus.VERIFIED
            ),
            Decimal("0"),
        )


def _effect_result(
    effect: CostExpectedEffect,
    status: CostSettlementStatus,
    reason: str,
    *,
    terminal: bool,
    evaluated_at: datetime,
    observation: CostEffectObservation | None,
    completeness: CostCompletenessReceipt | None,
) -> CostEffectSettlement:
    return CostEffectSettlement(
        effect_id=effect.effect_id,
        kind=effect.kind,
        status=status,
        reason=reason,
        terminal=terminal,
        observed_value=observation.value if observation is not None else None,
        observation_digest=(observation.evidence_digest if observation is not None else None),
        completeness_digest=(completeness.receipt_digest if completeness is not None else None),
        settled_at=evaluated_at,
    )


def _rollback_request(
    *,
    episode_id: str,
    decision_frame_digest: str,
    failed_effect_ids: tuple[str, ...],
    stop_condition_triggered: bool,
    requested_at: datetime,
    evidence_refs: tuple[str, ...],
) -> CostRollbackRequest:
    material = json.dumps(
        {
            "decision_frame_digest": decision_frame_digest,
            "episode_id": episode_id,
            "failed_effect_ids": sorted(failed_effect_ids),
            "stop_condition_triggered": stop_condition_triggered,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request_id = f"rollback:{hashlib.sha256(material).hexdigest()}"
    return CostRollbackRequest(
        request_id=request_id,
        episode_id=episode_id,
        decision_frame_digest=decision_frame_digest,
        failed_effect_ids=failed_effect_ids,
        stop_requested=True,
        rollback_requested=True,
        reason=(
            "stop_condition_triggered" if stop_condition_triggered else "expected_effect_failed"
        ),
        requested_at=requested_at,
        evidence_refs=evidence_refs,
    )


def _recovery_observed(
    request: CostRollbackRequest | None,
    observation: CostPostRecoveryObservation | None,
) -> bool:
    if request is None:
        if observation is not None:
            raise ValueError("post-recovery observation requires a rollback request")
        return False
    if observation is None:
        return False
    return (
        observation.recovery_request_id == request.request_id
        and observation.observed_at >= request.requested_at
        and observation.restored
        and observation.complete
        and observation.lane is CostObservationLane.INDEPENDENT
    )


def _one_per_effect[T](
    values: Sequence[T],
    kind: str,
) -> dict[str, T]:
    result: dict[str, T] = {}
    for value in values:
        effect_id = getattr(value, "effect_id", None)
        if not isinstance(effect_id, str) or not effect_id:
            raise ValueError(f"{kind} MUST cite an effect id")
        if effect_id in result:
            raise ValueError(f"{kind} effect ids MUST be unique")
        result[effect_id] = value
    return result


__all__ = ["CostEffectSettlementService"]
