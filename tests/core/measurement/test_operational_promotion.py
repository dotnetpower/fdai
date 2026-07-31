from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.measurement.operational_promotion import (
    OperationalPromotionBatch,
    OperationalPromotionEvaluator,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.core.measurement.operational_promotion_runner import (
    OperationalPromotionMeasurementRunner,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "a" * 40
_SCENARIO = "v2026.08"
_SEALED = datetime(2026, 8, 1, tzinfo=UTC)
_ACTION = "ops.publish-change-summary"


def _action():  # type: ignore[no-untyped-def]
    catalog = load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )
    return next(item for item in catalog if item.name == _ACTION)


def _record(
    index: int,
    *,
    cohort: PromotionEvidenceCohort,
    observed_at: datetime,
    **changes: object,
) -> OperationalPromotionRecord:
    values: dict[str, object] = {
        "sample_id": f"sample-{index:04d}",
        "action_type_name": _ACTION,
        "cohort": cohort,
        "observed_at": observed_at,
        "correct": True,
        "policy_escape": False,
        "rolled_back": False,
        "recurrence": False,
        "causal_evidence_grade": CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        "simulation_requires_review": False,
        "evidence_refs": (f"{index:064x}",),
    }
    values.update(changes)
    return OperationalPromotionRecord(**values)  # type: ignore[arg-type]


def _passing_batch() -> OperationalPromotionBatch:
    action = _action()
    sample_count = max(action.promotion_gate.min_samples, 200)
    span = action.promotion_gate.min_shadow_days + 1
    records = tuple(
        _record(
            index,
            cohort=(
                PromotionEvidenceCohort.FROZEN_BENCHMARK
                if index % 2 == 0
                else PromotionEvidenceCohort.LIVE_SHADOW
            ),
            observed_at=_SEALED - timedelta(days=span - (index * span) / max(sample_count - 1, 1)),
        )
        for index in range(sample_count)
    )
    return OperationalPromotionBatch(
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
        action_type_name=_ACTION,
        sealed_at=_SEALED,
        records=records,
    )


def _evaluator() -> OperationalPromotionEvaluator:
    return OperationalPromotionEvaluator(
        expected_fdai_revision=_REVISION,
        expected_scenario_set_version=_SCENARIO,
    )


def test_complete_immutable_evidence_batch_is_ready_for_separate_review() -> None:
    receipt = _evaluator().evaluate(_action(), _passing_batch())

    assert receipt.ready is True
    assert receipt.gaps == ()
    assert receipt.sample_count == len(_passing_batch().records)
    assert receipt.benchmark_samples > 0
    assert receipt.live_shadow_samples > 0
    assert receipt.accuracy == 1.0
    assert receipt.accuracy_ci_lower >= _action().promotion_gate.min_accuracy
    assert receipt.accuracy_ci_upper == 1.0
    assert receipt.policy_escapes == 0
    assert receipt.rollback_rate == 0.0
    assert receipt.recurrence_rate == 0.0
    assert receipt.simulation_review_rate == 0.0
    assert len(receipt.evidence_digest) == 64


def test_perfect_accuracy_at_minimum_samples_still_needs_confidence() -> None:
    action = _action()
    count = action.promotion_gate.min_samples
    span = action.promotion_gate.min_shadow_days + 1
    records = tuple(
        _record(
            index,
            cohort=(
                PromotionEvidenceCohort.FROZEN_BENCHMARK
                if index % 2 == 0
                else PromotionEvidenceCohort.LIVE_SHADOW
            ),
            observed_at=_SEALED - timedelta(days=span - (index * span) / max(count - 1, 1)),
        )
        for index in range(count)
    )
    batch = OperationalPromotionBatch(
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
        action_type_name=_ACTION,
        sealed_at=_SEALED,
        records=records,
    )

    receipt = _evaluator().evaluate(action, batch)

    assert receipt.accuracy == 1.0
    assert receipt.ready is False
    assert any("accuracy_ci_lower" in gap for gap in receipt.gaps)


@pytest.mark.parametrize(
    ("changes", "gap"),
    [
        ({"rolled_back": True}, "rollback_rate"),
        ({"recurrence": True}, "recurrence_rate"),
        ({"policy_escape": True}, "policy_escapes"),
        ({"simulation_requires_review": True}, "simulation_review_rate"),
        ({"causal_evidence_grade": CausalEvidenceGrade.ASSOCIATION}, "causal_evidence"),
        ({"correct": False}, "accuracy"),
    ],
)
def test_adverse_operational_evidence_blocks_promotion(
    changes: dict[str, object],
    gap: str,
) -> None:
    batch = _passing_batch()
    records = tuple(replace(record, **changes) for record in batch.records)

    receipt = _evaluator().evaluate(_action(), replace(batch, records=records))

    assert receipt.ready is False
    assert any(gap in item for item in receipt.gaps)


def test_revision_scenario_and_action_type_must_match_review_target() -> None:
    batch = _passing_batch()
    evaluator = OperationalPromotionEvaluator(
        expected_fdai_revision="b" * 40,
        expected_scenario_set_version="v2026.09",
    )

    receipt = evaluator.evaluate(_action(), batch)

    assert receipt.ready is False
    assert "fdai_revision_mismatch" in receipt.gaps
    assert "scenario_set_version_mismatch" in receipt.gaps


def test_benchmark_and_live_shadow_cohorts_are_both_required() -> None:
    batch = _passing_batch()
    benchmark_only = tuple(
        replace(record, cohort=PromotionEvidenceCohort.FROZEN_BENCHMARK) for record in batch.records
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=benchmark_only))

    assert receipt.ready is False
    assert any("live_shadow_samples" in gap for gap in receipt.gaps)


def test_benchmark_age_cannot_satisfy_live_shadow_observation_days() -> None:
    batch = _passing_batch()
    live_at = _SEALED - timedelta(days=1)
    stacked_live = tuple(
        replace(
            record,
            observed_at=(
                live_at
                if record.cohort is PromotionEvidenceCohort.LIVE_SHADOW
                else record.observed_at
            ),
        )
        for record in batch.records
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=stacked_live))

    assert receipt.observation_days == 0.0
    assert receipt.ready is False
    assert any("min_shadow_days" in gap for gap in receipt.gaps)


def test_batch_digest_is_order_independent_and_duplicate_ids_are_rejected() -> None:
    batch = _passing_batch()
    reversed_batch = replace(batch, records=tuple(reversed(batch.records)))

    assert batch.content_digest == reversed_batch.content_digest
    with pytest.raises(ValueError, match="sample ids MUST be unique"):
        replace(batch, records=(batch.records[0], batch.records[0]))


def test_record_after_batch_sealing_is_rejected() -> None:
    batch = _passing_batch()
    with pytest.raises(ValueError, match="MUST NOT follow sealing"):
        replace(
            batch,
            records=(
                _record(
                    999,
                    cohort=PromotionEvidenceCohort.LIVE_SHADOW,
                    observed_at=_SEALED + timedelta(seconds=1),
                ),
            ),
        )


class _Source:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises

    async def load_batch(self, **kwargs: object) -> OperationalPromotionBatch:
        if self.raises:
            raise RuntimeError("evidence store unavailable")
        return _passing_batch()


async def test_measurement_runner_audits_receipt_without_promoting() -> None:
    audit = InMemoryStateStore()
    runner = OperationalPromotionMeasurementRunner(
        source=_Source(),
        evaluator=_evaluator(),
        audit_store=audit,
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
    )

    (result,) = await runner.run((_action(),))

    assert result.receipt is not None
    assert result.receipt.ready is True
    entry = audit.audit_entries[0]["entry"]
    assert entry["action_kind"] == "operational_promotion.measured"
    assert entry["mode"] == "shadow"
    assert entry["ready"] is True
    assert entry["evidence_digest"] == result.receipt.evidence_digest


async def test_measurement_runner_audits_source_failure_as_not_ready() -> None:
    audit = InMemoryStateStore()
    runner = OperationalPromotionMeasurementRunner(
        source=_Source(raises=True),
        evaluator=_evaluator(),
        audit_store=audit,
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
    )

    (result,) = await runner.run((_action(),))

    assert result.receipt is None
    assert result.aborted_reason == "evidence_load_failed:RuntimeError"
    assert audit.audit_entries[0]["entry"]["ready"] is False
