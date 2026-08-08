"""Active/challenger Dynamic effect-model behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
    simulate_effect_branches,
    update_challenger,
)
from fdai.shared.contracts.models import ResponseOutcome

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


def _model(
    *,
    action_type: str,
    status: EffectModelStatus,
    bias: float = 0.0,
    grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL,
    learned_through: datetime = _NOW,
) -> EffectModel:
    return EffectModel(
        model_id=f"effect.{action_type}",
        version="1.0.0",
        revision=1,
        action_type_id=action_type,
        metric="latency_p99_ms",
        status=status,
        evidence_grade=grade,
        causal_evidence_receipt_digest="a" * 64,
        learned_at=_NOW,
        learned_through=learned_through,
        bias_correction=bias,
    )


def _outcome(*, recorded_at: datetime = _NOW + timedelta(minutes=2)) -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": "00000000-0000-0000-0000-000000000101",
            "idempotency_key": "response-outcome:example",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": "prediction-1",
            "metric": "latency_p99_ms",
            "expected_min": 90.0,
            "expected_max": 110.0,
            "observed_value": 80.0,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1),
            "label": "mismatch",
            "verification_status": "mismatch",
            "verification_reason": "value_outside_acceptable_range",
            "execution_mode": "shadow",
            "execution_outcome": "published",
            "decision": "auto",
            "evidence_refs": ["effect:prediction-1"],
            "recorded_at": recorded_at,
        }
    )


def test_only_challenger_learns_from_post_cutoff_scorable_outcome() -> None:
    active = _model(action_type="ops.scale-out", status=EffectModelStatus.ACTIVE)
    challenger = _model(action_type="ops.scale-out", status=EffectModelStatus.CHALLENGER)

    active_update = update_challenger(active, _outcome())
    challenger_update = update_challenger(challenger, _outcome())

    assert active_update.accepted is False
    assert active_update.model == active
    assert challenger_update.accepted is True
    assert challenger_update.model.revision == 2
    assert challenger_update.model.sample_count == 1
    assert challenger_update.model.bias_correction == -20.0


def test_learning_cutoff_prevents_temporal_leakage() -> None:
    challenger = _model(
        action_type="ops.scale-out",
        status=EffectModelStatus.CHALLENGER,
        learned_through=_NOW + timedelta(minutes=2),
    )

    update = update_challenger(
        challenger,
        _outcome(recorded_at=_NOW + timedelta(minutes=1)),
    )

    assert update.accepted is False
    assert update.reason == "outcome_not_after_learning_cutoff"


def test_simulation_uses_active_prediction_and_flags_challenger_divergence() -> None:
    snapshot = SimulationSnapshot(
        snapshot_id="snapshot-1",
        target_digest="0" * 64,
        metric="latency_p99_ms",
        observed_at=_NOW,
    )
    branches = (
        SimulationBranch("noop", "noop", 150.0, 10.0),
        SimulationBranch("scale", "ops.scale-out", 100.0, 10.0),
    )
    active = {
        "noop": _model(action_type="noop", status=EffectModelStatus.ACTIVE),
        "ops.scale-out": _model(action_type="ops.scale-out", status=EffectModelStatus.ACTIVE),
    }
    challenger = {
        "ops.scale-out": _model(
            action_type="ops.scale-out",
            status=EffectModelStatus.CHALLENGER,
            bias=-25.0,
        )
    }

    first = simulate_effect_branches(
        snapshot=snapshot,
        branches=branches,
        active_models=active,
        challenger_models=challenger,
        divergence_threshold=5.0,
    )
    second = simulate_effect_branches(
        snapshot=snapshot,
        branches=tuple(reversed(branches)),
        active_models=active,
        challenger_models=challenger,
        divergence_threshold=5.0,
    )

    scale = next(item for item in first.predictions if item.branch_id == "scale")
    assert scale.active_value == 100.0
    assert scale.challenger_value == 75.0
    assert scale.requires_review is True
    assert first.ordered_branch_ids == ("scale", "noop")
    assert first.simulation_id == second.simulation_id
    assert first.requires_review is True


def test_association_grade_never_yields_review_free_simulation() -> None:
    result = simulate_effect_branches(
        snapshot=SimulationSnapshot(
            snapshot_id="snapshot-1",
            target_digest="0" * 64,
            metric="latency_p99_ms",
            observed_at=_NOW,
        ),
        branches=(SimulationBranch("noop", "noop", 100.0, 5.0),),
        active_models={
            "noop": _model(
                action_type="noop",
                status=EffectModelStatus.ACTIVE,
                grade=CausalEvidenceGrade.ASSOCIATION,
            )
        },
    )

    assert result.requires_review is True
    assert result.predictions[0].reason == "causal_evidence_below_quasi_experimental"


def test_simulation_identity_binds_snapshot_time_and_raw_branch_values() -> None:
    model = _model(action_type="noop", status=EffectModelStatus.ACTIVE)
    first = simulate_effect_branches(
        snapshot=SimulationSnapshot("snapshot-1", "0" * 64, "latency_p99_ms", _NOW),
        branches=(SimulationBranch("noop", "noop", 100.0, 5.0),),
        active_models={"noop": model},
    )
    changed_value = simulate_effect_branches(
        snapshot=SimulationSnapshot("snapshot-1", "0" * 64, "latency_p99_ms", _NOW),
        branches=(SimulationBranch("noop", "noop", 101.0, 5.0),),
        active_models={"noop": model},
    )
    changed_time = simulate_effect_branches(
        snapshot=SimulationSnapshot(
            "snapshot-1",
            "0" * 64,
            "latency_p99_ms",
            _NOW + timedelta(seconds=1),
        ),
        branches=(SimulationBranch("noop", "noop", 100.0, 5.0),),
        active_models={"noop": model},
    )

    assert len({first.simulation_id, changed_value.simulation_id, changed_time.simulation_id}) == 3


def test_simulation_identity_normalizes_equivalent_timestamp_offsets() -> None:
    model = _model(action_type="noop", status=EffectModelStatus.ACTIVE)
    branch = (SimulationBranch("noop", "noop", 100.0, 5.0),)
    utc_result = simulate_effect_branches(
        snapshot=SimulationSnapshot("snapshot-1", "0" * 64, "latency_p99_ms", _NOW),
        branches=branch,
        active_models={"noop": model},
    )
    offset_result = simulate_effect_branches(
        snapshot=SimulationSnapshot(
            "snapshot-1",
            "0" * 64,
            "latency_p99_ms",
            _NOW.astimezone(timezone(timedelta(hours=9))),
        ),
        branches=branch,
        active_models={"noop": model},
    )

    assert utc_result.simulation_id == offset_result.simulation_id


def test_pure_simulation_rejects_model_after_snapshot_cutoff() -> None:
    snapshot = SimulationSnapshot("snapshot-1", "0" * 64, "latency_p99_ms", _NOW)
    future_model = replace(
        _model(action_type="noop", status=EffectModelStatus.ACTIVE),
        learned_through=_NOW + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="crosses the simulation snapshot cutoff"):
        simulate_effect_branches(
            snapshot=snapshot,
            branches=(SimulationBranch("noop", "noop", 100.0, 5.0),),
            active_models={"noop": future_model},
        )


def test_effect_prediction_rejects_finite_input_overflow() -> None:
    model = replace(
        _model(action_type="noop", status=EffectModelStatus.ACTIVE),
        bias_correction=1e308,
    )

    with pytest.raises(ValueError, match="arithmetic MUST remain finite"):
        model.predict(1e308, 1.0)


def test_effect_prediction_rejects_finite_interval_bound_overflow() -> None:
    model = _model(action_type="noop", status=EffectModelStatus.ACTIVE)

    with pytest.raises(ValueError, match="arithmetic MUST remain finite"):
        model.predict(1e308, 1e308)


def test_simulation_rejects_finite_divergence_overflow() -> None:
    active = replace(
        _model(action_type="noop", status=EffectModelStatus.ACTIVE),
        bias_correction=1e308,
    )
    challenger = replace(
        _model(action_type="noop", status=EffectModelStatus.CHALLENGER),
        bias_correction=-1e308,
    )

    with pytest.raises(ValueError, match="divergence arithmetic MUST remain finite"):
        simulate_effect_branches(
            snapshot=SimulationSnapshot("snapshot-1", "0" * 64, "latency_p99_ms", _NOW),
            branches=(SimulationBranch("noop", "noop", 0.0, 1.0),),
            active_models={"noop": active},
            challenger_models={"noop": challenger},
        )
