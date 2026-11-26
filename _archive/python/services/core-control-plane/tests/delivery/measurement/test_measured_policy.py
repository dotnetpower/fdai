from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

from fdai.core.measurement.latency_budget import LatencyObservation, Tier
from fdai.core.measurement.model_tracking import ModelObservation
from fdai.delivery.measurement.measured_policy import (
    LatencyEvidence,
    MeasuredPolicyBatch,
    MeasuredPolicyBatchSource,
    MeasuredPolicyRunner,
    StateStoreMeasuredPolicyBatchSource,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 31, 1, tzinfo=UTC)


class _Source(MeasuredPolicyBatchSource):
    def __init__(self, batches: Sequence[MeasuredPolicyBatch]) -> None:
        self._values = tuple(batches)

    def batches(self) -> AsyncIterator[MeasuredPolicyBatch]:
        return self._batches()

    async def _batches(self) -> AsyncIterator[MeasuredPolicyBatch]:
        for value in self._values:
            yield value


def _model(model_id: str, *, quality: float, cost: float) -> ModelObservation:
    return ModelObservation(
        model_id=model_id,
        scenario_set_version="v2026.07",
        quality_score=quality,
        cost_per_verified_answer=cost,
        verifier_abstain_rate=0.05,
        mixed_model_disagreement_rate=0.05,
    )


def _latency(
    tier: Tier,
    *,
    p95_ms: float | None = 50,
    sample_size: int = 100,
    unavailable_reason: str | None = None,
) -> LatencyEvidence:
    ceiling = {Tier.T0: 100.0, Tier.T1: 1_000.0, Tier.T2: 15_000.0}[tier]
    return LatencyEvidence(
        tier=tier,
        reported_budget_p95_ms=ceiling,
        observation=LatencyObservation(
            tier=tier,
            p50_ms=None if p95_ms is None else p95_ms / 2,
            p95_ms=p95_ms,
            p99_ms=None if p95_ms is None else p95_ms * 1.2,
            sample_size=sample_size,
            unavailable_reason=unavailable_reason,
        ),
    )


def _batch(
    batch_id: str,
    *,
    observed_at: datetime = _NOW,
    complete: bool = True,
    rollback_of: str | None = None,
    latency: tuple[LatencyEvidence, ...] | None = None,
) -> MeasuredPolicyBatch:
    return MeasuredPolicyBatch(
        batch_id=batch_id,
        observed_at=observed_at,
        complete=complete,
        incumbent=_model("model-a", quality=0.7, cost=1.0),
        challenger=_model("model-b", quality=0.8, cost=0.8),
        latency=latency if latency is not None else tuple(_latency(tier) for tier in Tier),
        rollback_of=rollback_of,
    )


async def test_complete_batch_records_review_only_model_and_per_tier_latency() -> None:
    store = InMemoryStateStore()
    report = await MeasuredPolicyRunner(
        source=_Source((_batch("batch-1"),)),
        store=store,
        clock=lambda: _NOW,
    ).run_once()

    assert report.processed_count == 1
    entry = store.audit_entries[-1]["entry"]
    assert entry["model_swap"]["outcome"] == "adopt_challenger"
    assert entry["model_swap"]["promotion_review_required"] is True
    assert entry["model_swap"]["binding_changed"] is False
    assert [item["tier"] for item in entry["latency"]] == ["T0", "T1", "T2"]
    assert all(item["sample_size"] == 100 for item in entry["latency"])
    assert entry["promotion_authority"] is False
    assert entry["execution_authority"] is False


async def test_restart_and_duplicate_input_are_idempotent() -> None:
    store = InMemoryStateStore()
    batch = _batch("batch-1")
    first = await MeasuredPolicyRunner(
        source=_Source((batch, batch)),
        store=store,
        clock=lambda: _NOW,
    ).run_once()
    restarted = await MeasuredPolicyRunner(
        source=_Source((batch,)),
        store=store,
        clock=lambda: _NOW,
    ).run_once()

    assert first.processed_count == 1
    assert first.duplicate_count == 1
    assert restarted.processed_count == 0
    assert restarted.duplicate_count == 1
    assert len(store.audit_entries) == 1


async def test_partial_stale_and_rollback_batches_remain_non_authoritative() -> None:
    store = InMemoryStateStore()
    report = await MeasuredPolicyRunner(
        source=_Source(
            (
                _batch("partial", complete=False),
                _batch("stale", observed_at=_NOW - timedelta(days=2)),
                _batch("rollback", rollback_of="batch-before"),
            )
        ),
        store=store,
        clock=lambda: _NOW,
    ).run_once()

    assert report.processed_count == 3
    assert report.rejected_count == 2
    assert report.rollback_count == 1
    entries = [record["entry"] for record in store.audit_entries]
    assert [entry["status"] for entry in entries] == [
        "partial",
        "stale",
        "rollback_recorded",
    ]
    assert all(entry["model_swap"] is None for entry in entries)
    assert all(entry["execution_authority"] is False for entry in entries)


async def test_unavailable_latency_is_recorded_without_false_pass() -> None:
    store = InMemoryStateStore()
    report = await MeasuredPolicyRunner(
        source=_Source(
            (
                _batch(
                    "unavailable",
                    latency=(
                        _latency(Tier.T0),
                        _latency(
                            Tier.T1,
                            p95_ms=None,
                            sample_size=0,
                            unavailable_reason="provider_timeout",
                        ),
                        _latency(Tier.T2),
                    ),
                ),
            )
        ),
        store=store,
        clock=lambda: _NOW,
    ).run_once()

    assert report.processed_count == 1
    t1 = store.audit_entries[-1]["entry"]["latency"][1]
    assert t1["tier"] == "T1"
    assert t1["outcome"] == "unavailable"
    assert t1["available"] is False
    assert t1["reasons"] == ["provider_timeout"]


async def test_reported_budget_cannot_raise_server_owned_ceiling() -> None:
    store = InMemoryStateStore()
    evidence = _latency(Tier.T0, p95_ms=200)
    evidence = LatencyEvidence(
        tier=evidence.tier,
        reported_budget_p95_ms=1_000_000,
        observation=evidence.observation,
    )
    await MeasuredPolicyRunner(
        source=_Source(
            (
                _batch(
                    "self-reported-budget",
                    latency=(evidence, _latency(Tier.T1), _latency(Tier.T2)),
                ),
            )
        ),
        store=store,
        clock=lambda: _NOW,
    ).run_once()

    t0 = store.audit_entries[-1]["entry"]["latency"][0]
    assert t0["budget_p95_ms"] == 100.0
    assert t0["reported_budget_p95_ms"] == 1_000_000
    assert t0["outcome"] == "over_budget"


async def test_state_store_source_parses_durable_batch() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:phase4:evidence:batch-1",
        {
            "schema_version": "1.0.0",
            "batch_id": "batch-1",
            "observed_at": _NOW.isoformat(),
            "complete": True,
            "incumbent": {
                "model_id": "model-a",
                "scenario_set_version": "v2026.07",
                "quality_score": 0.7,
                "cost_per_verified_answer": 1.0,
                "verifier_abstain_rate": 0.05,
                "mixed_model_disagreement_rate": 0.05,
            },
            "challenger": {
                "model_id": "model-b",
                "scenario_set_version": "v2026.07",
                "quality_score": 0.8,
                "cost_per_verified_answer": 0.8,
                "verifier_abstain_rate": 0.05,
                "mixed_model_disagreement_rate": 0.05,
            },
            "latency": [
                {
                    "tier": tier.value,
                    "budget_p95_ms": 1000,
                    "sample_size": 100,
                    "p50_ms": 10,
                    "p95_ms": 20,
                    "p99_ms": 30,
                }
                for tier in Tier
            ],
        },
    )

    values = [batch async for batch in StateStoreMeasuredPolicyBatchSource(store).batches()]

    assert [batch.batch_id for batch in values] == ["batch-1"]


async def test_malformed_batch_is_rejected_once_without_poisoning_following_input() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:phase4:evidence:malformed",
        {"batch_id": "malformed"},
    )
    await store.write_state(
        "measurement:phase4:evidence:valid",
        {
            "schema_version": "1.0.0",
            "batch_id": "valid",
            "observed_at": _NOW.isoformat(),
            "complete": True,
            "incumbent": {
                "model_id": "model-a",
                "scenario_set_version": "v2026.07",
                "quality_score": 0.7,
                "cost_per_verified_answer": 1.0,
                "verifier_abstain_rate": 0.05,
                "mixed_model_disagreement_rate": 0.05,
            },
            "challenger": {
                "model_id": "model-b",
                "scenario_set_version": "v2026.07",
                "quality_score": 0.8,
                "cost_per_verified_answer": 0.8,
                "verifier_abstain_rate": 0.05,
                "mixed_model_disagreement_rate": 0.05,
            },
            "latency": [
                {
                    "tier": tier.value,
                    "budget_p95_ms": 1000,
                    "sample_size": 100,
                    "p50_ms": 10,
                    "p95_ms": 20,
                    "p99_ms": 30,
                }
                for tier in Tier
            ],
        },
    )
    runner = MeasuredPolicyRunner(
        source=StateStoreMeasuredPolicyBatchSource(store),
        store=store,
        clock=lambda: _NOW,
    )

    first = await runner.run_once()
    restarted = await runner.run_once()

    assert first.processed_count == 2
    assert first.rejected_count == 1
    assert restarted.processed_count == 0
    assert restarted.duplicate_count == 2
    assert {entry["entry"]["status"] for entry in store.audit_entries} == {
        "evaluated",
        "malformed",
    }
