from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.measurement.cost_effect_settlement import CostEffectSettlementService
from fdai.shared.providers.cost_governance_decision import (
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostExpectedEffect,
    CostInterventionObservation,
    CostObservationLane,
    CostPostRecoveryObservation,
    CostSettlementStatus,
)

NOW = datetime(2026, 8, 28, 8, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"
DIGEST_D = f"sha256:{'d' * 64}"


def _effect(
    effect_id: str,
    kind: CostEffectKind,
    *,
    baseline: str = "100",
    minimum: str = "70",
    maximum: str = "90",
    estimated_only: bool = False,
) -> CostExpectedEffect:
    return CostExpectedEffect(
        effect_id=effect_id,
        kind=kind,
        target_ref="resource-a",
        metric=f"{kind.value}.metric",
        baseline_value=Decimal(baseline),
        acceptable_min=Decimal(minimum),
        acceptable_max=Decimal(maximum),
        predicted_at=NOW,
        horizon=timedelta(hours=1),
        telemetry_grace=timedelta(minutes=15),
        source_digest=DIGEST_A,
        estimated_only=estimated_only,
    )


def _observation(
    effect: CostExpectedEffect,
    *,
    value: str = "80",
    lane: CostObservationLane = CostObservationLane.INDEPENDENT,
) -> CostEffectObservation:
    suffix = effect.effect_id[-1]
    return CostEffectObservation(
        observation_id=f"observation-{suffix}",
        effect_id=effect.effect_id,
        effect_source_digest=effect.source_digest,
        target_ref=effect.target_ref,
        metric=effect.metric,
        value=Decimal(value),
        observed_at=effect.horizon_ends_at,
        lane=lane,
        source_authority="heimdall-independent-observer",
        evidence_digest={
            "t": DIGEST_A,
            "y": DIGEST_B,
            "e": DIGEST_C,
            "a": DIGEST_D,
        }.get(suffix, DIGEST_B),
    )


def _completeness(
    effect: CostExpectedEffect,
    *,
    complete: bool = True,
    lane: CostObservationLane = CostObservationLane.INDEPENDENT,
) -> CostCompletenessReceipt:
    return CostCompletenessReceipt(
        effect_id=effect.effect_id,
        effect_source_digest=effect.source_digest,
        receipt_digest={
            "t": DIGEST_B,
            "y": DIGEST_C,
            "e": DIGEST_D,
            "a": DIGEST_A,
        }.get(effect.effect_id[-1], DIGEST_C),
        complete=complete,
        coverage_through_at=effect.horizon_ends_at,
        lane=lane,
        source_authority="heimdall-completeness",
    )


def _settle(
    effects: tuple[CostExpectedEffect, ...],
    *,
    observations: tuple[CostEffectObservation, ...] | None = None,
    completeness: tuple[CostCompletenessReceipt, ...] | None = None,
    interventions: tuple[CostInterventionObservation, ...] = (),
    evaluated_at: datetime | None = None,
    stop_condition_triggered: bool = False,
    post_recovery_observation: CostPostRecoveryObservation | None = None,
):
    return CostEffectSettlementService().settle(
        episode_id="episode-1",
        decision_frame_digest=DIGEST_A,
        expected_effects=effects,
        observations=observations
        if observations is not None
        else tuple(_observation(effect) for effect in effects),
        completeness_receipts=completeness
        if completeness is not None
        else tuple(_completeness(effect) for effect in effects),
        interventions=interventions,
        evaluated_at=evaluated_at or NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
        stop_condition_triggered=stop_condition_triggered,
        post_recovery_observation=post_recovery_observation,
    )


def test_multi_effect_settlement_requires_every_independent_effect() -> None:
    effects = (
        _effect("effect-cost", CostEffectKind.COST),
        _effect("effect-capacity", CostEffectKind.CAPACITY),
        _effect("effect-service", CostEffectKind.SERVICE),
        _effect("effect-recovery", CostEffectKind.RECOVERY),
    )

    settlement = _settle(effects)

    assert settlement.terminal is True
    assert {effect.kind for effect in settlement.effects} == set(CostEffectKind)
    assert {effect.status for effect in settlement.effects} == {CostSettlementStatus.VERIFIED}
    assert settlement.realized_savings == Decimal("20")


def test_execution_output_cannot_satisfy_observation_or_completeness() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)
    settlement = _settle(
        (effect,),
        observations=(_observation(effect, lane=CostObservationLane.EXECUTION),),
        completeness=(_completeness(effect, lane=CostObservationLane.EXECUTION),),
        evaluated_at=effect.deadline_at,
    )

    assert settlement.effects[0].status is CostSettlementStatus.UNSCORABLE
    assert settlement.effects[0].reason == "telemetry_incomplete"
    assert settlement.realized_savings == 0


def test_prior_effect_revision_evidence_cannot_settle_current_effect() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)
    stale_observation = replace(_observation(effect), effect_source_digest=DIGEST_D)
    stale_completeness = replace(_completeness(effect), effect_source_digest=DIGEST_D)

    settlement = _settle(
        (effect,),
        observations=(stale_observation,),
        completeness=(stale_completeness,),
        evaluated_at=effect.deadline_at,
    )

    assert settlement.effects[0].status is CostSettlementStatus.UNSCORABLE
    assert settlement.effects[0].reason == "telemetry_incomplete"
    assert settlement.realized_savings == 0


def test_missing_observation_is_pending_until_grace_then_unscorable() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)

    pending = _settle(
        (effect,),
        observations=(),
        evaluated_at=effect.horizon_ends_at,
    )
    terminal = _settle(
        (effect,),
        observations=(),
        evaluated_at=effect.deadline_at,
    )

    assert pending.effects[0].status is CostSettlementStatus.UNSCORABLE
    assert pending.effects[0].terminal is False
    assert terminal.effects[0].terminal is True


def test_intervening_action_censors_instead_of_verifying() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)
    intervention = CostInterventionObservation(
        intervention_id="intervention-1",
        target_ref=effect.target_ref,
        effective_at=NOW + timedelta(minutes=30),
        source_authority="independent-change-ledger",
        evidence_digest=DIGEST_D,
    )

    settlement = _settle((effect,), interventions=(intervention,))

    assert settlement.effects[0].status is CostSettlementStatus.CENSORED
    assert settlement.realized_savings == 0


def test_failed_effect_emits_vidar_request_and_requires_post_recovery_observation() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)
    failed = _settle(
        (effect,),
        observations=(_observation(effect, value="120"),),
    )
    request = failed.rollback_request
    assert request is not None
    assert request.stop_requested and request.rollback_requested
    assert failed.terminal is False
    assert failed.realized_savings == 0

    executor_echo = CostPostRecoveryObservation(
        recovery_request_id=request.request_id,
        observed_at=request.requested_at,
        restored=True,
        complete=True,
        lane=CostObservationLane.EXECUTION,
        source_authority="executor-output",
        evidence_digest=DIGEST_C,
    )
    echoed = _settle(
        (effect,),
        observations=(_observation(effect, value="120"),),
        post_recovery_observation=executor_echo,
    )
    assert echoed.terminal is False

    independent = CostPostRecoveryObservation(
        recovery_request_id=request.request_id,
        observed_at=request.requested_at,
        restored=True,
        complete=True,
        lane=CostObservationLane.INDEPENDENT,
        source_authority="heimdall-independent-observer",
        evidence_digest=DIGEST_D,
    )
    recovered = _settle(
        (effect,),
        observations=(_observation(effect, value="120"),),
        post_recovery_observation=independent,
    )
    assert recovered.terminal is True
    assert recovered.recovery_observed is True
    assert recovered.realized_savings == 0


def test_stop_condition_alone_emits_rollback_request() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)

    settlement = _settle((effect,), stop_condition_triggered=True)

    assert settlement.rollback_request is not None
    assert settlement.rollback_request.reason == "stop_condition_triggered"
    assert settlement.realized_savings == 0


def test_estimated_only_and_incomplete_effects_never_become_savings() -> None:
    estimated = _effect(
        "effect-cost",
        CostEffectKind.COST,
        estimated_only=True,
    )
    incomplete = _effect("effect-capacity", CostEffectKind.CAPACITY)

    settlement = _settle(
        (estimated, incomplete),
        completeness=(
            _completeness(estimated),
            _completeness(incomplete, complete=False),
        ),
        evaluated_at=max(estimated.deadline_at, incomplete.deadline_at),
    )

    assert {item.status for item in settlement.effects} == {CostSettlementStatus.UNSCORABLE}
    assert settlement.realized_savings == 0


def test_duplicate_observation_or_completeness_is_rejected() -> None:
    effect = _effect("effect-cost", CostEffectKind.COST)
    observation = _observation(effect)
    completeness = _completeness(effect)

    with pytest.raises(ValueError, match="observation effect ids"):
        _settle((effect,), observations=(observation, observation))
    with pytest.raises(ValueError, match="completeness receipt effect ids"):
        _settle((effect,), completeness=(completeness, completeness))
