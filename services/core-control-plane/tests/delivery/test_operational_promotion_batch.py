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


def _record(cohort: PromotionEvidenceCohort) -> OperationalPromotionRecord:
    causal = CausalPromotionReceipt(
        hypothesis_id="hypothesis-1",
        hypothesis_revision_digest="c" * 64,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        status="supported",
    )
    return OperationalPromotionRecord(
        sample_id="sample-1",
        measurement_unit_id="unit-1",
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
    artifact = await GovernedLiveBatchProducer(
        source=_Records(record),
        output_dir=tmp_path,
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
    assert artifact.batch_path.exists()
    assert artifact.manifest_path.exists()


@pytest.mark.asyncio
async def test_producer_rejects_non_live_cohorts(tmp_path) -> None:
    with pytest.raises(ValueError, match="live-shadow"):
        await GovernedLiveBatchProducer(
            source=_Records(_record(PromotionEvidenceCohort.FROZEN_BENCHMARK)),
            output_dir=tmp_path,
        ).produce(
            action_type_name="ops.scale-out",
            action_type_version="1.0.0",
            action_type_digest="b" * 64,
            fdai_revision="a" * 40,
            scenario_set_version="scenario-v1",
        )
