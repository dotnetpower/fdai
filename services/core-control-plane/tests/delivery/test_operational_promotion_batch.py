from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.measurement import (
    CausalPromotionReceipt,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.delivery.measurement.operational_promotion_batch import GovernedLiveBatchProducer
from fdai.delivery.measurement.operational_promotion_evidence import (
    ImmutableFileOperationalPromotionEvidenceSource,
)
from fdai.shared.contracts.models import CausalEvidenceGrade


class _Records:
    def __init__(self, record: OperationalPromotionRecord) -> None:
        self.record = record

    async def load_records(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return (self.record,)


def _record(
    cohort: PromotionEvidenceCohort,
    *,
    sample_id: str = "sample-1",
    unit_id: str = "unit-1",
    hypothesis_id: str = "hypothesis-1",
) -> OperationalPromotionRecord:
    causal = CausalPromotionReceipt(
        hypothesis_id=hypothesis_id,
        hypothesis_revision_digest="c" * 64,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        status="supported",
    )
    return OperationalPromotionRecord(
        sample_id=sample_id,
        measurement_unit_id=unit_id,
        audit_sequence=1,
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_type_digest="b" * 64,
        fdai_revision="a" * 40,
        scenario_set_version="scenario-v1",
        scenario_case_id="case-1",
        cohort=cohort,
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
        correct=True,
        policy_escape=False,
        executed=True,
        rolled_back=False,
        recurrence_window_complete=True,
        recurrence=False,
        causal_receipt=causal,
        simulation_requires_review=False,
        evidence_refs=(causal.content_digest, "d" * 64),
    )


@pytest.mark.asyncio
async def test_live_producer_emits_exact_manifest_consumable_by_o7(tmp_path) -> None:
    record = _record(PromotionEvidenceCohort.LIVE_SHADOW)
    benchmark = _record(
        PromotionEvidenceCohort.FROZEN_BENCHMARK,
        sample_id="sample-2",
        unit_id="unit-2",
        hypothesis_id="hypothesis-2",
    )
    artifact = await GovernedLiveBatchProducer(
        source=_Records(record),
        output_dir=tmp_path,
        benchmark_records=(benchmark,),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    ).produce(
        action_type_name="ops.scale-out",
        action_type_version="1.0.0",
        action_type_digest="b" * 64,
        fdai_revision="a" * 40,
        scenario_set_version="scenario-v1",
    )
    loaded = await ImmutableFileOperationalPromotionEvidenceSource(artifact.manifest).load_batch(
        action_type_name="ops.scale-out",
        fdai_revision="a" * 40,
        scenario_set_version="scenario-v1",
    )
    assert loaded == artifact.batch
    assert {item.cohort for item in loaded.records} == {
        PromotionEvidenceCohort.FROZEN_BENCHMARK,
        PromotionEvidenceCohort.LIVE_SHADOW,
    }
    assert artifact.batch_path.exists()
    assert artifact.manifest_path.exists()


@pytest.mark.asyncio
async def test_producer_rejects_non_live_cohorts(tmp_path) -> None:
    with pytest.raises(ValueError, match="live-shadow"):
        await GovernedLiveBatchProducer(
            source=_Records(_record(PromotionEvidenceCohort.FROZEN_BENCHMARK)),
            output_dir=tmp_path,
            benchmark_records=(_record(PromotionEvidenceCohort.FROZEN_BENCHMARK),),
        ).produce(
            action_type_name="ops.scale-out",
            action_type_version="1.0.0",
            action_type_digest="b" * 64,
            fdai_revision="a" * 40,
            scenario_set_version="scenario-v1",
        )


@pytest.mark.asyncio
async def test_retry_reuses_pinned_sealed_at_and_completes_a_partial_publish(tmp_path) -> None:
    """A retry with a real, advancing clock MUST NOT be treated as a conflict.

    This reproduces a crash between the batch write and the manifest write:
    the batch is already durable but the manifest never landed. A retry
    (whose clock ticks forward) must reuse the batch's already-sealed
    timestamp so the batch content is untouched, and must complete the
    missing manifest instead of raising a false content-mismatch conflict.
    """
    record = _record(PromotionEvidenceCohort.LIVE_SHADOW)
    benchmark = _record(
        PromotionEvidenceCohort.FROZEN_BENCHMARK,
        sample_id="sample-2",
        unit_id="unit-2",
        hypothesis_id="hypothesis-2",
    )
    clock_ticks = iter([datetime(2026, 8, 23, tzinfo=UTC), datetime(2026, 8, 24, tzinfo=UTC)])
    producer = GovernedLiveBatchProducer(
        source=_Records(record),
        output_dir=tmp_path,
        benchmark_records=(benchmark,),
        clock=lambda: next(clock_ticks),
    )
    kwargs = {
        "action_type_name": "ops.scale-out",
        "action_type_version": "1.0.0",
        "action_type_digest": "b" * 64,
        "fdai_revision": "a" * 40,
        "scenario_set_version": "scenario-v1",
    }

    first = await producer.produce(**kwargs)
    first.manifest_path.unlink()
    batch_bytes_before_retry = first.batch_path.read_bytes()

    second = await producer.produce(**kwargs)

    assert second.batch.sealed_at == first.batch.sealed_at
    assert second.batch.content_digest == first.batch.content_digest
    assert first.batch_path.read_bytes() == batch_bytes_before_retry
    assert second.manifest_path.exists()
    stem = "ops.scale-out"
    leftover = {path.name for path in tmp_path.iterdir()} - {
        f"{stem}.batch.json",
        f"{stem}.manifest.json",
        f".{stem}.lock",
    }
    assert not leftover, f"atomic publish left stray artifacts: {leftover}"


@pytest.mark.asyncio
async def test_conflicting_prior_batch_content_fails_closed(tmp_path) -> None:
    """A genuinely different pre-existing batch MUST still fail closed."""
    stem = "ops.scale-out"
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / f"{stem}.batch.json").write_text(
        '{"sealed_at": "2026-09-01T00:00:00+00:00", "unexpected": true}',
        encoding="utf-8",
    )
    record = _record(PromotionEvidenceCohort.LIVE_SHADOW)
    benchmark = _record(
        PromotionEvidenceCohort.FROZEN_BENCHMARK,
        sample_id="sample-2",
        unit_id="unit-2",
        hypothesis_id="hypothesis-2",
    )
    producer = GovernedLiveBatchProducer(
        source=_Records(record),
        output_dir=tmp_path,
        benchmark_records=(benchmark,),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="already exists with different content"):
        await producer.produce(
            action_type_name=stem,
            action_type_version="1.0.0",
            action_type_digest="b" * 64,
            fdai_revision="a" * 40,
            scenario_set_version="scenario-v1",
        )
