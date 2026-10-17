"""Corrected observations rebuild an inert challenger, never an active policy."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.assurance_twin import EffectModelStatus, StateStoreEffectModelRegistry
from fdai.core.assurance_twin.feedback_generation import REBUILD_PURPOSE, generation_scope
from fdai.core.assurance_twin.feedback_rebuild import latest_feedback_revisions, rebuild_feedback
from fdai.core.assurance_twin.prequential_evaluation import evaluate_frozen_predictions
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _NOW, _CurrentFixtureSource, _model, _registry

_AS_OF = _NOW + timedelta(hours=2)


def _corrected(outcome: ResponseOutcome, *, unknown: bool = False) -> ResponseOutcome:
    assert outcome.outcome_revision is not None
    return ResponseOutcome.model_validate(
        {
            **outcome.model_dump(),
            "outcome_revision": outcome.outcome_revision + 1,
            "previous_revision_digest": outcome.revision_digest,
            "idempotency_key": f"{outcome.idempotency_key}:revision",
            "observed_value": None if unknown else 90.0,
            "observed_at": None if unknown else outcome.observed_at,
            "label": "unscorable" if unknown else "verified",
            "verification_status": "hold" if unknown else "verified",
            "recorded_at": outcome.recorded_at + timedelta(minutes=1),
        }
    )


def _admission(manifest: str) -> DecisionEvidenceAdmission:
    return DecisionEvidenceAdmission(
        receipt_digest="sha256:" + "d" * 64,
        verification_bundle_digest="sha256:" + "e" * 64,
        evidence_digest="sha256:" + manifest,
        scope_digest=generation_scope("ops.scale-out", "latency_p99_ms"),
        purpose_id=REBUILD_PURPOSE,
        source_revision=manifest,
        verified_at=_AS_OF,
        valid_until=_AS_OF + timedelta(hours=1),
    )


class _CurrentSource:
    def __init__(self, expected: tuple[str, ...]) -> None:
        self.expected = expected
        self.available = True

    async def current(self, revision_digests: tuple[str, ...]) -> bool:
        return self.available and revision_digests == self.expected


def test_corrected_revision_replaces_a_training_label_without_adding_a_sample() -> None:
    first = _feedback(1)
    corrected = _corrected(first)
    result = rebuild_feedback(
        seed=_model(EffectModelStatus.CHALLENGER),
        outcomes=(corrected, first, first),
        as_of=_AS_OF,
        complete=True,
    )
    assert result.model.sample_count == 1
    assert result.model.bias_correction == -10.0
    assert result.accepted_episodes == 1
    assert result.promotion_authority is False
    assert result.execution_authority is False


def test_withdrawn_observation_removes_its_contribution_instead_of_becoming_failure() -> None:
    first = _feedback(1)
    result = rebuild_feedback(
        seed=_model(EffectModelStatus.CHALLENGER),
        outcomes=(first, _corrected(first, unknown=True)),
        as_of=_AS_OF,
        complete=True,
    )
    assert result.model.sample_count == 0
    assert result.model.bias_correction == 0.0
    assert result.held_episodes == 1


def test_missing_predecessor_and_changed_immutable_identity_are_rejected() -> None:
    first = _feedback(1)
    corrected = _corrected(first)
    with pytest.raises(ValueError, match="predecessor is missing"):
        latest_feedback_revisions((corrected,), as_of=_AS_OF)
    forged = corrected.model_copy(update={"action_type_id": "ops.restart-service"})
    with pytest.raises(ValueError, match="lineage is invalid"):
        latest_feedback_revisions((first, forged), as_of=_AS_OF)


@pytest.mark.parametrize(
    ("field", "original", "replacement"),
    [
        ("decision", "deny", "auto"),
        ("decision", "abstain", "hil"),
        ("decision", "auto", "hil"),
        ("decision", "hil", "deny"),
        ("execution_mode", "shadow", "enforce"),
        ("execution_mode", "enforce", "shadow"),
    ],
)
def test_correction_cannot_rewrite_original_authorization(
    field: str, original: str, replacement: str
) -> None:
    first = ResponseOutcome.model_validate({**_feedback(1).model_dump(), field: original})
    corrected = ResponseOutcome.model_validate(
        {**_corrected(first).model_dump(), field: replacement}
    )
    for records in ((first, corrected), (corrected, first, corrected)):
        with pytest.raises(ValueError, match="lineage is invalid"):
            rebuild_feedback(
                seed=_model(EffectModelStatus.CHALLENGER),
                outcomes=records,
                as_of=_AS_OF,
                complete=True,
            )
        with pytest.raises(ValueError, match="lineage is invalid"):
            evaluate_frozen_predictions(
                records,
                as_of=_AS_OF,
                training_independence_keys=frozenset(),
                source_kind="synthetic",
            )


@pytest.mark.parametrize("decision", ["deny", "abstain", "auto", "hil"])
def test_effect_correction_preserves_authorization_and_unknown_outcomes(decision: str) -> None:
    first = ResponseOutcome.model_validate({**_feedback(1).model_dump(), "decision": decision})
    corrected = _corrected(first)
    assert latest_feedback_revisions((first, corrected), as_of=_AS_OF) == (corrected,)
    rebuilt = rebuild_feedback(
        seed=_model(EffectModelStatus.CHALLENGER),
        outcomes=(first, corrected),
        as_of=_AS_OF,
        complete=True,
    )
    assert rebuilt.accepted_episodes == (1 if decision in {"auto", "hil"} else 0)
    unknown = _corrected(first, unknown=True)
    evaluation = evaluate_frozen_predictions(
        (first, unknown),
        as_of=_AS_OF,
        training_independence_keys=frozenset(),
        source_kind="synthetic",
    )
    assert evaluation.scored_episodes == 0
    assert evaluation.mean_absolute_error is None
    assert not evaluation.policy_effect_measured


def test_complete_replay_is_order_stable_but_binds_every_seed_fact() -> None:
    outcomes = (_feedback(1), _feedback(2))
    seed = _model(EffectModelStatus.CHALLENGER)
    first = rebuild_feedback(seed=seed, outcomes=outcomes, as_of=_AS_OF, complete=True)
    reverse = rebuild_feedback(
        seed=seed, outcomes=tuple(reversed(outcomes)), as_of=_AS_OF, complete=True
    )
    assert first == reverse
    changed = rebuild_feedback(
        seed=replace(seed, causal_evidence_receipt_digest="f" * 64),
        outcomes=outcomes,
        as_of=_AS_OF,
        complete=True,
    )
    assert changed.input_manifest_digest != first.input_manifest_digest
    with pytest.raises(ValueError, match="complete authoritative"):
        rebuild_feedback(seed=seed, outcomes=outcomes, as_of=_AS_OF, complete=False)


async def test_reviewed_rebuild_retains_old_generation_and_rechecks_sources_after_restart() -> None:
    store = InMemoryStateStore()
    original = _registry(store)
    seed = _model(EffectModelStatus.CHALLENGER)
    active = _model(EffectModelStatus.ACTIVE)
    await original.register(active, registered_by="Mimir")
    await original.register(seed, registered_by="Mimir")
    first = _feedback(1)
    await original.update_from_outcome(first)
    corrected = _corrected(first)
    assert (
        await original.update_from_outcome(corrected)
    ).reason == "outcome_revision_requires_rebuild"
    candidate = rebuild_feedback(
        seed=seed, outcomes=(first, corrected), as_of=_AS_OF, complete=True
    )
    source = _CurrentSource(candidate.source_digests)
    registry = StateStoreEffectModelRegistry(store, clock=lambda: _AS_OF, feedback_source=source)
    result = await registry.rebuild_challenger(
        seed=seed,
        outcomes=(first, corrected),
        as_of=_AS_OF,
        expected_revision=3,
        admission=_admission(candidate.input_manifest_digest),
    )
    assert result.accepted
    rebuilt = await registry.get(
        status=EffectModelStatus.CHALLENGER, action_type_id=seed.action_type_id, metric=seed.metric
    )
    assert rebuilt is not None and rebuilt.bias_correction == -10.0
    assert rebuilt.sample_count == 1 and rebuilt.revision == 4
    assert (await registry.update_from_outcome(corrected)).reason == "outcome_already_applied"
    replay = await registry.rebuild_challenger(
        seed=seed,
        outcomes=(first, corrected),
        as_of=_AS_OF,
        expected_revision=3,
        admission=_admission(candidate.input_manifest_digest),
    )
    assert not replay.accepted and replay.reason == "rebuild_already_applied"
    assert (
        await registry.get(
            status=EffectModelStatus.ACTIVE,
            action_type_id=active.action_type_id,
            metric=active.metric,
        )
        == active
    )
    assert await store.verify_chain()
    source.available = False
    assert (
        await StateStoreEffectModelRegistry(
            store, clock=lambda: _AS_OF, feedback_source=source
        ).get(
            status=EffectModelStatus.CHALLENGER,
            action_type_id=seed.action_type_id,
            metric=seed.metric,
        )
        is None
    )


def test_prequential_scoring_never_reconstructs_a_prediction_or_scores_training_groups() -> None:
    outcome = _feedback(1)
    snapshot = outcome.prediction_snapshot
    assert snapshot is not None
    scored = evaluate_frozen_predictions(
        (outcome,),
        as_of=_AS_OF,
        training_independence_keys=frozenset(),
        source_kind="synthetic",
    )
    assert scored.mean_absolute_error == 20.0
    assert scored.interval_coverage == 0.0
    assert scored.mean_interval_width == 20.0
    assert scored.policy_effect_measured is False
    excluded = evaluate_frozen_predictions(
        (outcome,),
        as_of=_AS_OF,
        training_independence_keys=frozenset({snapshot.independence_key}),
        source_kind="synthetic",
    )
    assert excluded.scored_episodes == 0 and excluded.mean_absolute_error is None
    unexecuted = outcome.model_copy(update={"decision": "deny"})
    assert (
        evaluate_frozen_predictions(
            (unexecuted,),
            as_of=_AS_OF,
            training_independence_keys=frozenset(),
            source_kind="synthetic",
        ).scored_episodes
        == 0
    )


async def test_ordinary_learned_model_honors_current_source_withdrawal() -> None:
    store = InMemoryStateStore()
    original = _registry(store)
    await original.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    unavailable = _CurrentFixtureSource(False)
    guarded = StateStoreEffectModelRegistry(
        store, clock=lambda: _AS_OF, feedback_source=unavailable
    )
    blocked = await guarded.update_from_outcome(_feedback(1))
    assert blocked.reason == "model_generation_sources_unavailable"
    assert unavailable.requests
    assert (await original.update_from_outcome(_feedback(1))).accepted
    assert (
        await guarded.get(
            status=EffectModelStatus.CHALLENGER,
            action_type_id="ops.scale-out",
            metric="latency_p99_ms",
        )
        is None
    )


async def test_review_admission_cannot_substitute_a_different_registered_seed() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    seed = _model(EffectModelStatus.CHALLENGER)
    await registry.register(seed, registered_by="Mimir")
    malicious = replace(
        seed, sample_count=999, bias_correction=123, causal_evidence_receipt_digest="f" * 64
    )
    candidate = rebuild_feedback(
        seed=malicious, outcomes=(_feedback(1),), as_of=_AS_OF, complete=True
    )
    reviewed = StateStoreEffectModelRegistry(
        store, clock=lambda: _AS_OF, feedback_source=_CurrentSource(candidate.source_digests)
    )
    result = await reviewed.rebuild_challenger(
        seed=malicious,
        outcomes=(_feedback(1),),
        as_of=_AS_OF,
        expected_revision=1,
        admission=_admission(candidate.input_manifest_digest),
    )
    assert result.reason == "rebuild_seed_mismatch"
    assert (
        await registry.get(
            status=EffectModelStatus.CHALLENGER,
            action_type_id=seed.action_type_id,
            metric=seed.metric,
        )
        == seed
    )


def test_default_replay_is_chronological_not_uuid_ordered_and_retries_count_once() -> None:
    from fdai.core.assurance_twin import update_challenger

    seed = _model(EffectModelStatus.CHALLENGER)
    outcomes = tuple(
        ResponseOutcome.model_validate(
            {
                **_feedback(index, minutes=position + 2).model_dump(),
                "observed_value": value,
                "label": "verified" if value == 100 else "mismatch",
                "verification_status": "verified" if value == 100 else "mismatch",
            }
        )
        for position, (index, value) in enumerate(((3, 0.0), (1, 100.0), (2, 200.0)))
    )
    expected = seed
    for item in outcomes:
        expected = update_challenger(expected, item, learning_cutoff=seed.learned_through).model
    rebuilt = rebuild_feedback(seed=seed, outcomes=outcomes, as_of=_AS_OF, complete=True)
    assert rebuilt.model == expected
    first, retry = _feedback(1), _feedback(2)
    assert first.prediction_snapshot is not None and retry.prediction_snapshot is not None
    retry = ResponseOutcome.model_validate(
        {
            **retry.model_dump(),
            "prediction_snapshot": retry.prediction_snapshot.model_copy(
                update={"independence_key": first.prediction_snapshot.independence_key}
            ),
        }
    )
    grouped = rebuild_feedback(seed=seed, outcomes=(first, retry), as_of=_AS_OF, complete=True)
    assert grouped.model.sample_count == grouped.accepted_episodes == 1


async def test_excluded_future_evidence_does_not_block_reviewed_rebuild() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    seed = _model(EffectModelStatus.CHALLENGER)
    await registry.register(seed, registered_by="Mimir")
    first = _feedback(1)
    future = _feedback(99, minutes=180)
    candidate = rebuild_feedback(seed=seed, outcomes=(first, future), as_of=_AS_OF, complete=True)
    reviewed = StateStoreEffectModelRegistry(
        store, clock=lambda: _AS_OF, feedback_source=_CurrentSource(candidate.source_digests)
    )
    result = await reviewed.rebuild_challenger(
        seed=seed,
        outcomes=(first, future),
        as_of=_AS_OF,
        expected_revision=1,
        admission=_admission(candidate.input_manifest_digest),
    )
    assert result.accepted


def test_rebuild_cannot_clear_cross_outcome_idempotency_conflicts() -> None:
    first = _feedback(1)
    second = ResponseOutcome.model_validate(
        {**_feedback(2).model_dump(), "idempotency_key": first.idempotency_key}
    )
    with pytest.raises(ValueError, match="idempotency key is bound"):
        rebuild_feedback(
            seed=_model(EffectModelStatus.CHALLENGER),
            outcomes=(first, second),
            as_of=_AS_OF,
            complete=True,
        )
