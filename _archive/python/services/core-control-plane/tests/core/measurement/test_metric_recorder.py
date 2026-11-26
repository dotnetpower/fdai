"""Atomic metric persistence preserves replay, corrections, and source boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.measurement.metric_recorder import (
    MetricObservationConflictError,
    MetricObservationRecorder,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.metric_observation import MetricObservationV1, metric_observation_id

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _observation(**updates: object) -> MetricObservationV1:
    facts = {
        "metric_id": "mttr_seconds",
        "mode": "enforce",
        "arm": "treatment",
        "measurement_protocol_digest": "sha256:" + "a" * 64,
        "source_revision": "a" * 40,
        "event_id": "event-1",
        "source_id": "incident-source",
        "source_record_id": "incident-1",
        "source_refs": ("incident:1",),
        "value": 120.0,
        "unit": "seconds",
        "observed_at": NOW,
        "recorded_at": NOW,
        "synthetic": False,
        "complete": True,
        **updates,
    }
    return MetricObservationV1.model_validate(
        {**facts, "observation_id": metric_observation_id(**facts)}
    )


async def test_duplicate_and_restart_record_exactly_one_audit_row() -> None:
    store = InMemoryStateStore()
    assert await MetricObservationRecorder(store).record(_observation())
    retry = _observation(recorded_at=NOW + timedelta(seconds=5))
    assert not await MetricObservationRecorder(store).record(retry)
    assert len(store.audit_entries) == 1
    row = store.audit_entries[0]["entry"]
    assert row["action_kind"] == "measurement.metric.v1"
    assert row["claim_eligibility_authority"] is False
    assert row["execution_authority"] is False
    assert MetricObservationV1.from_audit_entry(row) == _observation()
    assert row["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")


async def test_correction_is_append_only_and_old_replay_is_idempotent() -> None:
    store = InMemoryStateStore()
    recorder = MetricObservationRecorder(store)
    original = _observation()
    corrected = _observation(
        value=140.0, complete=False, supersedes_observation_id=original.observation_id
    )
    assert await recorder.record(original)
    assert await recorder.record(corrected)
    assert not await recorder.record(original)
    assert len(store.audit_entries) == 2
    assert store.audit_entries[0]["entry"]["value"] == 120.0
    assert store.audit_entries[1]["entry"]["complete"] is False


@pytest.mark.parametrize(
    "updates",
    [
        {"value": 121.0},
        {"source_id": "another-source"},
        {"source_record_id": "another-incident"},
        {"synthetic": True},
        {"mode": "shadow"},
        {"source_revision": "b" * 40},
        {"measurement_protocol_digest": "sha256:" + "b" * 64},
        {"supersedes_observation_id": "sha256:" + "a" * 64},
    ],
)
async def test_contradictions_do_not_append_audit(updates: dict[str, object]) -> None:
    store = InMemoryStateStore()
    recorder = MetricObservationRecorder(store)
    await recorder.record(_observation())
    with pytest.raises(MetricObservationConflictError):
        await recorder.record(_observation(**updates))
    assert len(store.audit_entries) == 1


async def test_missing_predecessor_is_not_an_initial_observation() -> None:
    store = InMemoryStateStore()
    with pytest.raises(MetricObservationConflictError, match="predecessor"):
        await MetricObservationRecorder(store).record(
            _observation(supersedes_observation_id="sha256:" + "a" * 64)
        )
    assert not store.audit_entries


async def test_concurrent_duplicate_has_one_winner() -> None:
    store = InMemoryStateStore()
    recorder = MetricObservationRecorder(store)
    results = await asyncio.gather(*(recorder.record(_observation()) for _ in range(5)))
    assert results.count(True) == 1
    assert len(store.audit_entries) == 1


async def test_forged_model_copy_is_revalidated() -> None:
    store = InMemoryStateStore()
    forged = _observation().model_copy(update={"value": -1.0})
    with pytest.raises(ValueError):
        await MetricObservationRecorder(store).record(forged)
    assert not store.audit_entries
