"""Focused unit tests for operational-learning qualification and separate effect reporting."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.operational_learning.qualification_evaluation import (
    FrozenT1ShadowIntakeSummary,
    OperationalLearningEpisode,
    PredeclaredLearningEvaluationGates,
    QualificationVenueSelection,
    evaluate_operational_learning_effects,
    qualify_frozen_intervention_provenance,
)
from fdai.shared.contracts.models import EffectPredictionSnapshot, Mode, ResponseOutcome

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SCOPE_DIGEST = "a" * 64
ACCESS_DIGEST = "f" * 64
GRAPH_DIGEST = "b" * 64
MODEL_DIGEST = "c" * 64


def _scope(**overrides: object) -> QualificationVenueSelection:
    values: dict[str, object] = {
        "installation_id": "fdai-local-isolated-validation",
        "venue": "local-isolated-validation",
        "target_scope_digest": SCOPE_DIGEST,
        "access_scope_digest": ACCESS_DIGEST,
        "fdai_revision": "1e7778a701",
        "read_source_revision": "d" * 40,
        "graph_source_revision": GRAPH_DIGEST,
        "slo_revision": "slo-v2026.10",
        "safety_budget_revision": "safety-budget-v2026.10",
        "window_start": T0,
        "window_end": T0 + timedelta(hours=6),
        "deadline_seconds": 5.0,
        "authorized_by_operator": True,
    }
    values.update(overrides)
    return QualificationVenueSelection(**values)  # type: ignore[arg-type]


def _gates(**overrides: object) -> PredeclaredLearningEvaluationGates:
    values: dict[str, object] = {
        "slo_revision": "slo-v2026.10",
        "safety_budget_revision": "safety-budget-v2026.10",
        "min_independent_episodes_per_arm": 3,
        "min_time_separation": timedelta(minutes=5),
        "observation_window": timedelta(hours=1),
        "recurrence_window": timedelta(hours=24),
        "min_recovery_rate": 0.75,
        "max_recurrence_rate": 0.25,
        "max_rollback_rate": 0.10,
        "max_side_effect_count": 0,
        "max_policy_escape_count": 0,
        "max_mean_absolute_error": 15.0,
        "max_brier_score": 0.20,
        "min_interval_coverage": 0.75,
    }
    values.update(overrides)
    return PredeclaredLearningEvaluationGates(**values)  # type: ignore[arg-type]


def _snapshot(idx: int = 1, *, model_digest: str = MODEL_DIGEST) -> EffectPredictionSnapshot:
    predicted_at = T0 + timedelta(minutes=idx)
    return EffectPredictionSnapshot(
        prediction_id=f"pred-{idx}",
        event_id=UUID(int=1000 + idx),
        action_id=UUID(int=2000 + idx),
        action_type_id="ops.scale-out",
        target_digest="0" * 64,
        model_ref="scalar-effect-model:v1",
        model_digest=model_digest,
        source_digest="d" * 64,
        metric="latency_p99_ms",
        unit="ms",
        objective="minimize",
        point_prediction=50.0,
        interval_lower=40.0,
        interval_upper=60.0,
        nominal_coverage=0.90,
        known_at=predicted_at,
        predicted_at=predicted_at,
        observation_deadline=predicted_at + timedelta(minutes=15),
        independence_key=hashlib.sha256(f"ind-key-{idx}".encode()).hexdigest(),
    )


def _outcome(
    idx: int = 1,
    *,
    scorable: bool = True,
    observed_value: float | None = 48.0,
    snapshot: EffectPredictionSnapshot | None = None,
    execution_mode: Mode = Mode.ENFORCE,
    decision: str = "auto",
    execution_outcome: str = "succeeded",
    rollback_succeeded: bool | None = False,
    observation_unit: str | None = "ms",
    observation_receipt_ref: str | None = "obs-receipt-1",
    observed_at: datetime | None = None,
) -> ResponseOutcome:
    snap = snapshot if snapshot is not None else _snapshot(idx)
    predicted_at = snap.predicted_at
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.1.0",
            "outcome_id": str(UUID(int=3000 + idx)),
            "outcome_revision": 1,
            "idempotency_key": f"idem-{idx}",
            "action_id": str(snap.action_id),
            "event_id": str(snap.event_id),
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": snap.prediction_id,
            "metric": "latency_p99_ms",
            "expected_min": 40.0,
            "expected_max": 60.0,
            "observed_value": observed_value,
            "predicted_at": predicted_at,
            "observation_deadline": predicted_at + timedelta(minutes=15),
            "observed_at": (observed_at or (predicted_at + timedelta(minutes=5)))
            if scorable
            else None,
            "label": "verified" if scorable else "unscorable",
            "verification_status": "verified" if scorable else "hold",
            "verification_reason": (
                "value_within_acceptable_range" if scorable else "observation_withheld"
            ),
            "execution_mode": execution_mode.value,
            "execution_outcome": execution_outcome,
            "rollback_succeeded": rollback_succeeded,
            "decision": decision,
            "evidence_refs": [f"effect:{idx}"],
            "recorded_at": predicted_at + timedelta(minutes=6),
            "prediction_snapshot": snap if scorable else None,
            "observation_unit": observation_unit if scorable else None,
            "observation_receipt_ref": observation_receipt_ref if scorable else None,
        }
    )


def test_venue_selection_enforces_explicit_authorization_and_digests() -> None:
    scope = _scope()
    assert scope.scope_manifest_digest.startswith("sha256:")
    with pytest.raises(PermissionError):
        _scope(authorized_by_operator=False)
    with pytest.raises(PermissionError):
        _scope(venue="runtime")
    with pytest.raises(PermissionError):
        _scope(venue="port:5432")
    with pytest.raises(ValueError):
        _scope(target_scope_digest="not-a-digest")
    with pytest.raises(ValueError):
        _scope(window_end=T0 - timedelta(seconds=1))


def test_predeclared_gates_validate_thresholds_and_digest() -> None:
    gates = _gates()
    assert gates.gate_plan_digest.startswith("sha256:")
    with pytest.raises(ValueError):
        _gates(min_independent_episodes_per_arm=0)
    with pytest.raises(ValueError):
        _gates(min_recovery_rate=1.5)
    with pytest.raises(ValueError):
        _gates(max_side_effect_count=-1)


def test_frozen_provenance_qualifies_interventions_and_preserves_unknown_outcomes() -> None:
    snap1 = _snapshot(1)
    snap3 = _snapshot(3, model_digest="e" * 64)
    snap4 = _snapshot(4)
    valid = _outcome(1, snapshot=snap1, observed_value=52.0)
    unknown = _outcome(
        2,
        scorable=False,
        observed_value=None,
        execution_mode=Mode.SHADOW,
        decision="abstain",
        execution_outcome="held",
        rollback_succeeded=None,
    )
    unretained_gen = _outcome(3, snapshot=snap3, observed_value=49.0)
    wrong_unit = _outcome(4, snapshot=snap4, observation_unit="s")

    result = qualify_frozen_intervention_provenance(
        (valid, unknown, unretained_gen, wrong_unit),
        retained_predictions={
            snap1.prediction_id: snap1,
            snap3.prediction_id: snap3,
            snap4.prediction_id: snap4,
        },
        model_generation_digests=frozenset({MODEL_DIGEST}),
        as_of=T0 + timedelta(hours=1),
    )
    assert result.total_latest_outcomes == 4
    assert result.qualified_interventions_count == 1
    assert result.unknown_preserved_count == 1
    assert result.held_provenance_count == 2
    assert result.qualified_outcome_ids == (str(valid.outcome_id),)
    assert result.unknown_outcome_ids == (str(unknown.outcome_id),)
    assert result.execution_authority is False
    assert result.promotion_authority is False


def test_evaluate_operational_learning_effects_deduplicates_and_reports_separately() -> None:
    scope = _scope()
    gates = _gates(min_independent_episodes_per_arm=3)
    snap = _snapshot(1)
    provenance = qualify_frozen_intervention_provenance(
        (_outcome(1, snapshot=snap),),
        retained_predictions={snap.prediction_id: snap},
        model_generation_digests=frozenset({MODEL_DIGEST}),
        as_of=T0 + timedelta(hours=1),
    )
    intake = FrozenT1ShadowIntakeSummary(
        evaluated_events=12,
        baseline_selections_preserved=12,
        coherent_qualified_shadow_matches=1,
        leased_qualified_shadow_matches=1,
        withdrawal_rejections_verified=11,
        deadline_and_cancellation_holds_verified=2,
        stale_or_expired_holds_verified=2,
    )
    episodes: list[OperationalLearningEpisode] = []
    for idx in range(4):
        base_time = T0 + timedelta(minutes=idx * 10)
        episodes.append(
            OperationalLearningEpisode(
                episode_id=f"base-{idx}",
                arm="baseline",
                incident_id=f"inc-base-{idx}",
                independence_key=f"ind-base-{idx}",
                common_cause_key=f"cc-base-{idx}",
                idempotency_key=f"idem-base-{idx}",
                observed_at=base_time,
                execution_mode="enforce",
                decision="auto",
                recommended=idx < 3,
                abstained=idx == 3,
                intervention_completed=idx < 3,
                outcome_known=idx < 3,
                recovered=True if idx < 2 else (False if idx == 2 else None),
                recovery_seconds=120.0 if idx < 2 else None,
                recurrence_window_complete=idx < 2,
                recurred=False if idx < 2 else None,
                rolled_back=False,
                predicted_recovery_probability=0.80 if idx < 3 else None,
                point_prediction=50.0 if idx < 3 else None,
                interval_lower=40.0 if idx < 3 else None,
                interval_upper=60.0 if idx < 3 else None,
                observed_value=55.0 if idx < 3 else None,
            )
        )
    # Add retry and duplicate incident to baseline - must be excluded from independent counts
    episodes.append(
        OperationalLearningEpisode(
            episode_id="base-retry",
            arm="baseline",
            incident_id="inc-base-0",
            independence_key="ind-base-retry",
            common_cause_key="cc-base-retry",
            idempotency_key="idem-base-retry",
            observed_at=T0 + timedelta(minutes=50),
            is_retry_or_replay=True,
        )
    )
    episodes.append(
        OperationalLearningEpisode(
            episode_id="base-dup-inc",
            arm="baseline",
            incident_id="inc-base-1",
            independence_key="ind-base-dup",
            common_cause_key="cc-base-dup",
            idempotency_key="idem-base-dup",
            observed_at=T0 + timedelta(minutes=60),
        )
    )

    for idx in range(4):
        chal_time = T0 + timedelta(minutes=100 + idx * 10)
        episodes.append(
            OperationalLearningEpisode(
                episode_id=f"chal-{idx}",
                arm="challenger",
                incident_id=f"inc-chal-{idx}",
                independence_key=f"ind-chal-{idx}",
                common_cause_key=f"cc-chal-{idx}",
                idempotency_key=f"idem-chal-{idx}",
                observed_at=chal_time,
                execution_mode="enforce",
                decision="auto",
                recommended=True,
                abstained=False,
                intervention_completed=True,
                outcome_known=True,
                recovered=True,
                recovery_seconds=90.0,
                recurrence_window_complete=idx < 3,
                recurred=False if idx < 3 else None,
                rolled_back=False,
                predicted_recovery_probability=0.90,
                point_prediction=50.0,
                interval_lower=40.0,
                interval_upper=60.0,
                observed_value=48.0,
                propensity_overlap_verified=False,
            )
        )

    report = evaluate_operational_learning_effects(
        scope=scope,
        gates=gates,
        provenance=provenance,
        t1_shadow_intake=intake,
        episodes=episodes,
        claim_policy_effect=False,
    )
    assert report.gates_passed is True
    assert report.gate_failures == ()
    assert report.policy_effect_claimed is False
    assert report.execution_authority is False
    assert report.promotion_authority is False

    assert report.baseline.sample_counts.raw_observation_count == 6
    assert report.baseline.sample_counts.excluded_retry_or_replay_count == 1
    assert report.baseline.sample_counts.excluded_duplicate_group_count == 1
    assert report.baseline.sample_counts.independent_episode_count == 4
    assert report.baseline.sample_counts.unknown_outcome_count == 1

    assert report.challenger.recovery.executed_denominator == 4
    assert report.challenger.recovery.recovered_count == 4
    assert report.challenger.recovery.recovery_rate == 1.0
    assert report.challenger.recovery.wilson_95_lower is not None
    assert report.challenger.recurrence.completed_window_denominator == 3
    assert report.challenger.recurrence.censored_incomplete_window_count == 1
    assert report.challenger.recurrence.recurrence_rate == 0.0
    assert report.challenger.rollback_and_side_effects.rollback_rate == 0.0
    assert report.challenger.abstention_and_coverage.recommendation_coverage == 1.0
    assert report.challenger.prediction_and_calibration.mean_absolute_error == pytest.approx(2.0)
    assert report.challenger.prediction_and_calibration.interval_coverage == 1.0
    assert report.challenger.prediction_and_calibration.brier_score == pytest.approx(0.01)

    with pytest.raises(ValueError, match="policy effect cannot be claimed"):
        evaluate_operational_learning_effects(
            scope=scope,
            gates=gates,
            provenance=provenance,
            t1_shadow_intake=intake,
            episodes=episodes,
            claim_policy_effect=True,
        )
