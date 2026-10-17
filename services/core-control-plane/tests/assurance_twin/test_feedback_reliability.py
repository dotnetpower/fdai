"""Scalar feedback durability and the next shadow prediction, without live effects."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.core.assurance_twin import (
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
    model_registry,
)
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.assurance_twin.test_model_registry import _NOW, _model, _outcome, _registry, _snapshot


def _feedback(index: int, *, minutes: int = 2) -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            **_outcome().model_dump(),
            "outcome_id": UUID(int=100 + index),
            "idempotency_key": f"response-outcome:{index}",
            "event_id": UUID(int=index),
            "action_id": UUID(int=1000 + index),
            "prediction_id": f"prediction-{index}",
            "recorded_at": _NOW + timedelta(minutes=minutes),
            "execution_mode": "enforce",
            "execution_outcome": "succeeded",
            "rollback_succeeded": False,
            "prediction_snapshot": _snapshot(index),
        }
    )


async def _challenger(registry: StateStoreEffectModelRegistry) -> EffectModel | None:
    return await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )


async def test_distinct_equal_time_outcomes_both_update_after_restart() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    first = await registry.update_from_outcome(_feedback(1))
    restarted = _registry(store)
    second = await restarted.update_from_outcome(_feedback(2))
    model = await _challenger(restarted)
    assert first.accepted and second.accepted
    assert model is not None and model.sample_count == 2


async def test_late_outcome_is_not_lost_behind_another_events_timestamp() -> None:
    registry = _registry(InMemoryStateStore())
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1, minutes=4))
    late = await registry.update_from_outcome(_feedback(2, minutes=2))
    assert late.accepted
    model = await _challenger(registry)
    assert model is not None and model.sample_count == 2


async def test_same_outcome_with_later_recording_is_not_a_new_sample() -> None:
    registry = _registry(InMemoryStateStore())
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1))
    rewritten = _feedback(1, minutes=3)
    result = await registry.update_from_outcome(rewritten)
    assert not result.accepted
    assert result.reason == "outcome_revision_requires_rebuild"
    assert await _challenger(registry) is None


async def test_exact_replay_is_a_noop_with_the_same_durable_receipt() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1))
    before = await _challenger(registry)
    count = len(tuple(store.audit_entries))
    replay = await _registry(store).update_from_outcome(_feedback(1))
    assert replay.reason == "outcome_already_applied"
    assert await _challenger(registry) == before
    assert len(tuple(store.audit_entries)) == count


async def test_model_receipt_and_audit_roll_back_together_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    before = await _challenger(registry)

    def fail_audit(entry: Mapping[str, Any]) -> None:
        raise RuntimeError("injected audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_append_audit_locked", fail_audit)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            await registry.update_from_outcome(_feedback(1))
    assert await _challenger(registry) == before
    assert (
        sum(
            item["entry"]["action_kind"] == "dynamic.effect_model.challenger.updated"
            for item in store.audit_entries
        )
        == 0
    )
    assert (await registry.update_from_outcome(_feedback(1))).accepted
    assert (await registry.update_from_outcome(_feedback(1))).reason == "outcome_already_applied"
    assert await store.verify_chain()


async def test_commit_then_lost_response_retries_without_another_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    commit = store.compare_and_set_state_with_audit

    async def lose_response(*args: Any, **kwargs: Any) -> bool:
        assert await commit(*args, **kwargs)
        raise TimeoutError("commit response lost")

    with monkeypatch.context() as patch:
        patch.setattr(store, "compare_and_set_state_with_audit", lose_response)
        with pytest.raises(TimeoutError, match="commit response lost"):
            await registry.update_from_outcome(_feedback(1))
    restarted = _registry(store)
    assert (await restarted.update_from_outcome(_feedback(1))).reason == "outcome_already_applied"
    model = await _challenger(restarted)
    assert model is not None and model.sample_count == 1
    assert (
        sum(
            item["entry"]["action_kind"] == "dynamic.effect_model.challenger.updated"
            for item in store.audit_entries
        )
        == 1
    )


@pytest.mark.parametrize("duplicate", [False, True])
async def test_concurrent_consumers_commit_each_event_once(
    monkeypatch: pytest.MonkeyPatch, duplicate: bool
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    read = store.read_state
    ready = asyncio.Event()
    readers = 0

    async def racing_read(key: str) -> Mapping[str, Any] | None:
        nonlocal readers
        result = await read(key)
        readers += 1
        if readers <= 2:
            if readers == 2:
                ready.set()
            await ready.wait()
        return result

    monkeypatch.setattr(store, "read_state", racing_read)
    results = await asyncio.gather(
        registry.update_from_outcome(_feedback(1)),
        _registry(store).update_from_outcome(_feedback(1 if duplicate else 2)),
    )
    model = await _challenger(registry)
    expected = 1 if duplicate else 2
    assert sum(result.accepted for result in results) == expected
    assert model is not None and model.sample_count == expected
    assert (
        sum(
            item["entry"]["action_kind"] == "dynamic.effect_model.challenger.updated"
            for item in store.audit_entries
        )
        == expected
    )


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": UUID(int=99)},
        {"observed_value": 85.0},
        {"outcome_id": UUID(int=999), "idempotency_key": "corrected:1", "observed_value": 85.0},
    ],
)
async def test_wrong_attribution_or_unversioned_correction_holds_only_challenger(
    change: dict[str, object],
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    active = _model(EffectModelStatus.ACTIVE)
    await registry.register(active, registered_by="Mimir")
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1))
    if "event_id" in change:
        with pytest.raises(ValueError, match="frozen prediction identity"):
            ResponseOutcome.model_validate({**_feedback(1).model_dump(), **change})
        assert await _challenger(registry) is not None
        return
    corrected = ResponseOutcome.model_validate({**_feedback(1).model_dump(), **change})
    assert (
        await registry.update_from_outcome(corrected)
    ).reason == "outcome_revision_requires_rebuild"
    restarted = _registry(store)
    assert await _challenger(restarted) is None
    assert (
        await restarted.get(
            status=EffectModelStatus.ACTIVE,
            action_type_id=active.action_type_id,
            metric=active.metric,
        )
        == active
    )
    entry = tuple(store.audit_entries)[-1]["entry"]
    assert entry["action_kind"] == "dynamic.effect_model.challenger.held"
    assert entry["promotion_authority"] is False


async def test_retry_of_same_event_is_not_an_independent_sample() -> None:
    registry = _registry(InMemoryStateStore())
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1))
    retry = ResponseOutcome.model_validate(
        {
            **_feedback(2).model_dump(),
            "prediction_snapshot": _snapshot(2).model_copy(
                update={"independence_key": _snapshot(1).independence_key}
            ),
        }
    )
    result = await registry.update_from_outcome(retry)
    assert result.reason == "dependent_event_already_learned"
    model = await _challenger(registry)
    assert model is not None and model.sample_count == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"decision": "deny"}, "outcome_not_executed"),
        ({"decision": "abstain"}, "outcome_not_executed"),
        ({"execution_mode": "shadow"}, "outcome_not_executed"),
        ({"execution_outcome": "dispatch_not_attempted"}, "outcome_execution_unconfirmed"),
        ({"execution_outcome": "failed"}, "outcome_execution_unconfirmed"),
        ({"rollback_succeeded": None}, "outcome_rollback_unresolved"),
        ({"rollback_succeeded": True}, "outcome_rollback_unresolved"),
        (
            {
                "label": "unscorable",
                "verification_status": "hold",
                "observed_value": None,
                "observed_at": None,
            },
            "outcome_unscorable",
        ),
    ],
)
async def test_permission_and_unknown_are_not_effect_labels(
    change: dict[str, object], reason: str
) -> None:
    registry = _registry(InMemoryStateStore())
    initial = _model(EffectModelStatus.CHALLENGER)
    await registry.register(initial, registered_by="Mimir")
    outcome = ResponseOutcome.model_validate({**_feedback(1).model_dump(), **change})
    result = await registry.update_from_outcome(outcome)
    assert result.reason == reason
    assert await _challenger(registry) == initial


async def test_known_observed_mismatch_with_human_permission_can_calibrate() -> None:
    registry = _registry(InMemoryStateStore())
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    assert (
        await registry.update_from_outcome(_feedback(1).model_copy(update={"decision": "hil"}))
    ).accepted


async def test_checkpoint_full_holds_instead_of_evicting_deduplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_registry, "_MAX_FEEDBACK_RECEIPTS", 1)
    registry = _registry(InMemoryStateStore())
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    await registry.update_from_outcome(_feedback(1))
    assert (await registry.update_from_outcome(_feedback(2))).reason == "feedback_checkpoint_full"
    assert await _challenger(registry) is None
    assert (await registry.update_from_outcome(_feedback(1))).reason == "feedback_checkpoint_full"


async def test_legacy_empty_model_adopts_checkpoint_but_unknown_history_is_held() -> None:
    store = InMemoryStateStore()
    key = model_registry._state_key(EffectModelStatus.CHALLENGER, "ops.scale-out", "latency_p99_ms")
    legacy = _model(EffectModelStatus.CHALLENGER)
    await store.write_state(key, model_registry._serialize(replace(legacy, sample_count=2)))
    registry = _registry(store)
    assert (await registry.update_from_outcome(_feedback(1))).reason == (
        "untracked_challenger_requires_rebuild"
    )
    assert await _challenger(registry) is None
    await store.write_state(key, model_registry._serialize(legacy))
    await retain_prediction(store, _snapshot(1), recorded_at=_NOW)
    assert (await registry.update_from_outcome(_feedback(1))).accepted


async def test_corrupt_checkpoint_fails_explicitly_without_overwriting_model() -> None:
    store = InMemoryStateStore()
    key = model_registry._state_key(EffectModelStatus.CHALLENGER, "ops.scale-out", "latency_p99_ms")
    value = {
        **model_registry._serialize(_model(EffectModelStatus.CHALLENGER)),
        "feedback_checkpoint": {"schema_version": "unsupported"},
    }
    await store.write_state(key, value)
    registry = _registry(store)
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        await registry.update_from_outcome(_feedback(1))
    assert await store.read_state(key) == value


async def test_fixed_cutoff_rejects_preexisting_evidence_and_future_recording() -> None:
    registry = StateStoreEffectModelRegistry(
        InMemoryStateStore(), clock=lambda: _NOW + timedelta(minutes=3)
    )
    initial = replace(
        _model(EffectModelStatus.CHALLENGER), learned_through=_NOW + timedelta(minutes=2)
    )
    await registry.register(initial, registered_by="Mimir")
    assert (await registry.update_from_outcome(_feedback(1))).reason == (
        "outcome_not_after_learning_cutoff"
    )
    assert (await registry.update_from_outcome(_feedback(2, minutes=4))).reason == (
        "outcome_recorded_in_future"
    )
    assert await _challenger(registry) == initial


async def test_missing_model_or_metric_remains_explicitly_unavailable() -> None:
    registry = _registry(InMemoryStateStore())
    assert await _challenger(registry) is None
    assert (await registry.update_from_outcome(_feedback(1))).reason == "challenger_not_registered"
    unknown = ResponseOutcome.model_validate(
        {
            **_feedback(1).model_dump(),
            **dict.fromkeys(
                (
                    "prediction_id",
                    "metric",
                    "expected_min",
                    "expected_max",
                    "predicted_at",
                    "observation_deadline",
                    "observed_value",
                    "observed_at",
                    "prediction_snapshot",
                    "observation_unit",
                    "observation_receipt_ref",
                )
            ),
            "label": "unscorable",
            "verification_status": "hold",
        }
    )
    assert (await registry.update_from_outcome(unknown)).reason == "outcome_metric_unavailable"


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"schema_version": "1.0.0", "cutoff": _NOW.isoformat(), "receipts": {}, "hold_reason": []},
        {
            "schema_version": "1.0.0",
            "cutoff": (_NOW + timedelta(days=1)).isoformat(),
            "receipts": {},
            "hold_reason": None,
        },
        {
            "schema_version": "1.0.0",
            "cutoff": _NOW.isoformat(),
            "receipts": {"not-a-digest": {}},
            "hold_reason": None,
        },
    ],
)
async def test_corrupt_checkpoint_details_fail_closed(checkpoint: dict[str, object]) -> None:
    store = InMemoryStateStore()
    key = model_registry._state_key(EffectModelStatus.CHALLENGER, "ops.scale-out", "latency_p99_ms")
    await store.write_state(
        key,
        {
            **model_registry._serialize(_model(EffectModelStatus.CHALLENGER)),
            "feedback_checkpoint": checkpoint,
        },
    )
    with pytest.raises(ValueError, match="stored effect feedback"):
        await _registry(store).update_from_outcome(_feedback(1))


@pytest.mark.parametrize("cancel", [False, True])
async def test_stalled_learning_is_bounded_and_cancellation_never_commits(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    started = asyncio.Event()
    never = asyncio.Event()

    async def stall(*args: Any, **kwargs: Any) -> bool:
        started.set()
        await never.wait()
        return False

    with monkeypatch.context() as patch:
        patch.setattr(store, "compare_and_set_state_with_audit", stall)
        patch.setattr(model_registry, "_UPDATE_TIMEOUT_SECONDS", 0.02)
        task = asyncio.create_task(registry.update_from_outcome(_feedback(1)))
        await started.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
    assert await _challenger(registry) == _model(EffectModelStatus.CHALLENGER)
    assert (await registry.update_from_outcome(_feedback(1))).accepted
