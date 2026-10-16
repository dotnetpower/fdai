"""Real Dynamic consumer and audit-source cursor with isolated in-memory storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from fdai.core.assurance_twin import EffectModelStatus
from fdai.core.measurement.runners import DynamicLearningRunner
from fdai.delivery.measurement.postgres_growth import (
    PostgresResponseOutcomeSource,
)
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _NOW, _model, _registry


class _AuditSource(PostgresResponseOutcomeSource):
    def __init__(self, store: InMemoryStateStore, outcomes: tuple[ResponseOutcome, ...]) -> None:
        super().__init__(dsn="unused-local-fake", state_store=store)
        self._outcomes = outcomes

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        return [
            {"seq": index, "entry": outcome.model_dump(mode="json")}
            for index, outcome in enumerate(self._outcomes, start=1)
            if index > after_seq
        ]


async def test_unfinished_learner_replays_while_committed_event_is_not_learned_twice() -> None:
    store = InMemoryStateStore()
    first = _feedback(1)
    second = _feedback(2).model_copy(update={"action_type_id": "ops.restart-service"})
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")

    def runner() -> DynamicLearningRunner:
        return DynamicLearningRunner(
            outcome_source=_AuditSource(store, (first, second)),
            registry=_registry(store),
            audit_store=store,
            clock=lambda: _NOW,
        )

    with pytest.raises(RuntimeError, match="retry required: challenger_not_registered"):
        await runner().run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") is None
    await registry.register(
        replace(_model(EffectModelStatus.CHALLENGER), action_type_id=second.action_type_id),
        registered_by="Mimir",
    )
    report = await runner().run_once()
    assert report.total_outcomes == 2
    assert report.accepted_count == 1
    assert ("outcome_already_applied", 1) in report.reasons
    assert await store.read_state("measurement:dynamic_learning:watermark") == {"seq": 2}
    assert await store.read_state("measurement:pattern_growth:watermark") is None
    for action in (first.action_type_id, second.action_type_id):
        model = await registry.get(
            status=EffectModelStatus.CHALLENGER, action_type_id=action, metric="latency_p99_ms"
        )
        assert model is not None and model.sample_count == 1
    assert (await runner().run_once()).total_outcomes == 0


async def test_persistent_contention_does_not_advance_feedback_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")

    async def conflict(*args: Any, **kwargs: Any) -> bool:
        return False

    with monkeypatch.context() as patch:
        patch.setattr(store, "compare_and_set_state_with_audit", conflict)
        with pytest.raises(RuntimeError, match="retry required: revision_conflict"):
            await DynamicLearningRunner(
                outcome_source=_AuditSource(store, (_feedback(1),)),
                registry=registry,
                audit_store=store,
            ).run_once()
    assert await store.read_state("measurement:dynamic_learning:watermark") is None
    assert tuple(store.audit_entries)[-1]["entry"]["reason"] == "revision_conflict"
    assert (await registry.update_from_outcome(_feedback(1))).accepted


async def test_unknown_outcome_is_audited_without_learning_or_inventing_failure() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    unknown = ResponseOutcome.model_validate(
        {
            **_feedback(1).model_dump(),
            "label": "unscorable",
            "verification_status": "hold",
            "verification_reason": "observation_provider_failed",
            "observed_value": None,
            "observed_at": None,
        }
    )
    report = await DynamicLearningRunner(
        outcome_source=_AuditSource(store, (unknown,)),
        registry=registry,
        audit_store=store,
    ).run_once()
    assert report.accepted_count == 0
    assert report.reasons == (("outcome_unscorable", 1),)
    assert tuple(store.audit_entries)[-2]["entry"]["response_outcome_id"] == str(unknown.outcome_id)
    assert unknown.metric is not None
    model = await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id=unknown.action_type_id,
        metric=unknown.metric,
    )
    assert model is not None and model.sample_count == 0
