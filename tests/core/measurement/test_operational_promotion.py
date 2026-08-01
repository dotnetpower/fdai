from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import pytest

from fdai.core.measurement.operational_promotion import (
    CausalPromotionReceipt,
    OperationalPromotionBatch,
    OperationalPromotionEvaluator,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.core.measurement.operational_promotion_runner import (
    OperationalPromotionMeasurementRunner,
)
from fdai.core.risk_gate import ActionPromotionRegistry, PromotionMetrics
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "a" * 40
_SCENARIO = "v2026.08"
_SEALED = datetime(2026, 8, 1, tzinfo=UTC)
_ACTION = "ops.publish-change-summary"


class _AcceptingCausalVerifier:
    def verify(self, receipt: CausalPromotionReceipt) -> bool:
        return True


class _SelectiveCausalVerifier:
    def verify(self, receipt: CausalPromotionReceipt) -> bool:
        return receipt.hypothesis_revision_digest != "9" * 64


class _UnitVerifier:
    def verify(self, record: OperationalPromotionRecord) -> bool:
        return not record.measurement_unit_id.startswith("unverified-")


@cache
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
    action = _action()
    assert action.provenance is not None
    causal_receipt = CausalPromotionReceipt(
        hypothesis_id=f"causal-{index:04d}",
        hypothesis_revision_digest=f"{index + 10_000:064x}",
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        status="supported",
    )
    values: dict[str, object] = {
        "sample_id": f"sample-{index:04d}",
        "measurement_unit_id": f"event-{index:04d}",
        "audit_sequence": 1,
        "action_type_name": _ACTION,
        "action_type_version": action.version,
        "action_type_digest": action.provenance.content_hash.removeprefix("sha256:"),
        "fdai_revision": _REVISION,
        "scenario_set_version": _SCENARIO,
        "scenario_case_id": f"scenario-{index:04d}",
        "cohort": cohort,
        "observed_at": observed_at,
        "correct": True,
        "policy_escape": False,
        "executed": True,
        "rolled_back": False,
        "recurrence_window_complete": True,
        "recurrence": False,
        "causal_receipt": causal_receipt,
        "simulation_requires_review": False,
        "evidence_refs": (f"{index:064x}", causal_receipt.content_digest),
    }
    values.update(changes)
    return OperationalPromotionRecord(**values)  # type: ignore[arg-type]


def _passing_batch() -> OperationalPromotionBatch:
    action = _action()
    sample_count = max(action.promotion_gate.min_samples, 400)
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
        action_type_version=action.version,
        action_type_digest=action.provenance.content_hash.removeprefix("sha256:"),
        sealed_at=_SEALED,
        records=records,
    )


def _evaluator() -> OperationalPromotionEvaluator:
    return OperationalPromotionEvaluator(
        expected_fdai_revision=_REVISION,
        expected_scenario_set_version=_SCENARIO,
        causal_receipt_verifier=_SelectiveCausalVerifier(),
        as_of_fn=lambda: _SEALED,
        unit_verifier=_UnitVerifier(),
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
        action_type_version=action.version,
        action_type_digest=action.provenance.content_hash.removeprefix("sha256:"),
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


def test_insufficient_causal_receipt_blocks_promotion() -> None:
    batch = _passing_batch()
    records = []
    for record in batch.records:
        causal = replace(
            record.causal_receipt,
            evidence_grade=CausalEvidenceGrade.ASSOCIATION,
        )
        records.append(
            replace(
                record,
                causal_receipt=causal,
                evidence_refs=(record.evidence_refs[0], causal.content_digest),
            )
        )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=tuple(records)))

    assert receipt.ready is False
    assert any("causal_evidence" in item for item in receipt.gaps)


def test_unresolved_causal_receipt_blocks_promotion() -> None:
    batch = _passing_batch()
    record = batch.records[0]
    causal = replace(record.causal_receipt, hypothesis_revision_digest="9" * 64)
    updated = replace(
        record,
        causal_receipt=causal,
        evidence_refs=(record.evidence_refs[0], causal.content_digest),
    )

    receipt = _evaluator().evaluate(
        _action(),
        replace(batch, records=(updated, *batch.records[1:])),
    )

    assert receipt.ready is False
    assert receipt.causal_evidence_failures == 1


def test_unverified_measurement_unit_blocks_promotion() -> None:
    batch = _passing_batch()
    updated = replace(batch.records[0], measurement_unit_id="unverified-event-1")

    receipt = _evaluator().evaluate(
        _action(),
        replace(batch, records=(updated, *batch.records[1:])),
    )

    assert receipt.ready is False
    assert "unverified_measurement_units=1" in receipt.gaps


def test_revision_scenario_and_action_type_must_match_review_target() -> None:
    batch = _passing_batch()
    evaluator = OperationalPromotionEvaluator(
        expected_fdai_revision="b" * 40,
        expected_scenario_set_version="v2026.09",
        causal_receipt_verifier=_AcceptingCausalVerifier(),
        unit_verifier=_UnitVerifier(),
        as_of_fn=lambda: _SEALED,
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

    assert receipt.live_observation_days == 1
    assert receipt.ready is False
    assert any("min_shadow_days" in gap for gap in receipt.gaps)


def test_successful_benchmark_cannot_hide_failed_live_shadow_cohort() -> None:
    batch = _passing_batch()
    records = tuple(
        replace(
            record,
            correct=(record.cohort is PromotionEvidenceCohort.FROZEN_BENCHMARK),
        )
        for record in batch.records
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=records))

    assert receipt.benchmark_accuracy == 1.0
    assert receipt.live_shadow_accuracy == 0.0
    assert receipt.ready is False
    assert any("live_shadow_accuracy_ci_lower" in gap for gap in receipt.gaps)


def test_two_endpoint_samples_do_not_satisfy_distinct_observation_days() -> None:
    batch = _passing_batch()
    action = _action()
    live_dates = (
        _SEALED - timedelta(days=action.promotion_gate.min_shadow_days),
        _SEALED,
    )
    live_index = 0
    records = []
    for record in batch.records:
        if record.cohort is PromotionEvidenceCohort.LIVE_SHADOW:
            record = replace(record, observed_at=live_dates[live_index % 2])
            live_index += 1
        records.append(record)

    receipt = _evaluator().evaluate(action, replace(batch, records=tuple(records)))

    assert receipt.live_observation_days == 2
    assert receipt.ready is False
    assert any("live_observation_days" in gap for gap in receipt.gaps)


def test_rollback_denominator_uses_executed_actions_only() -> None:
    batch = _passing_batch()
    records = tuple(
        replace(
            record,
            executed=(index == 0),
            rolled_back=(index == 0),
        )
        for index, record in enumerate(batch.records)
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=records))

    assert receipt.executed_samples == 1
    assert receipt.rollback_rate == 1.0
    assert receipt.ready is False


def test_incomplete_recurrence_window_blocks_promotion() -> None:
    batch = _passing_batch()
    records = (
        replace(batch.records[0], recurrence_window_complete=False),
        *batch.records[1:],
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=records))

    assert receipt.recurrence_incomplete_samples == 1
    assert receipt.ready is False
    assert any("recurrence_incomplete_samples" in gap for gap in receipt.gaps)


def test_batch_digest_is_order_independent_and_duplicate_ids_are_rejected() -> None:
    batch = _passing_batch()
    reversed_batch = replace(batch, records=tuple(reversed(batch.records)))

    assert batch.content_digest == reversed_batch.content_digest
    first = batch.records[0]
    refs_reordered = replace(
        first,
        evidence_refs=tuple(reversed(first.evidence_refs)),
    )
    canonical_refs = replace(batch, records=(refs_reordered, *batch.records[1:]))
    assert batch.content_digest == canonical_refs.content_digest
    with pytest.raises(ValueError, match="sample ids MUST be unique"):
        replace(batch, records=(batch.records[0], batch.records[0]))


def test_aliases_count_once_and_latest_correction_wins() -> None:
    batch = _passing_batch()
    original = batch.records[0]
    aliases = tuple(
        replace(
            original,
            sample_id=f"alias-{index:04d}",
            audit_sequence=index + 1,
            correct=index < 199,
        )
        for index in range(200)
    )
    aliased_batch = replace(batch, records=(*batch.records[1:], *aliases))

    receipt = _evaluator().evaluate(_action(), aliased_batch)

    assert receipt.sample_count == len(batch.records)
    assert receipt.correct_count == len(batch.records) - 1
    assert receipt.ready is False


@pytest.mark.parametrize(
    "changes",
    [
        {"cohort": PromotionEvidenceCohort.LIVE_SHADOW},
        {"scenario_case_id": "scenario-reassigned"},
        {"observed_at": _SEALED - timedelta(hours=1)},
    ],
)
def test_correction_cannot_change_observation_lineage(changes: dict[str, object]) -> None:
    batch = _passing_batch()
    original = batch.records[0]
    correction = replace(
        original,
        sample_id="sample-correction",
        audit_sequence=2,
        **changes,
    )

    with pytest.raises(ValueError, match="preserve observation lineage"):
        replace(batch, records=(*batch.records, correction))


def test_correction_cannot_change_causal_hypothesis_lineage() -> None:
    batch = _passing_batch()
    original = batch.records[0]
    causal = replace(original.causal_receipt, hypothesis_id="causal-reassigned")
    correction = replace(
        original,
        sample_id="sample-correction",
        audit_sequence=2,
        causal_receipt=causal,
        evidence_refs=(original.evidence_refs[0], causal.content_digest),
    )

    with pytest.raises(ValueError, match="preserve observation lineage"):
        replace(batch, records=(*batch.records, correction))


def test_independent_scenario_and_hypothesis_cannot_alias_measurement_units() -> None:
    batch = _passing_batch()
    original = batch.records[0]
    alias = replace(
        original,
        sample_id="sample-alias",
        measurement_unit_id="event-alias",
    )

    with pytest.raises(ValueError, match="scenario cases MUST map to one measurement unit"):
        replace(batch, records=(*batch.records, alias))


def test_recurrence_denominator_ignores_nonexecuted_samples() -> None:
    batch = _passing_batch()
    records = tuple(
        replace(
            record,
            executed=(index == 0),
            recurrence_window_complete=(index == 0),
        )
        for index, record in enumerate(batch.records)
    )

    receipt = _evaluator().evaluate(_action(), replace(batch, records=records))

    assert receipt.executed_samples == 1
    assert receipt.recurrence_complete_samples == 1
    assert receipt.recurrence_incomplete_samples == 0
    assert receipt.recurrence_rate == 0.0
    assert receipt.ready is True


def test_future_sealed_batch_is_not_ready() -> None:
    batch = _passing_batch()
    future = replace(batch, sealed_at=_SEALED + timedelta(seconds=1))

    receipt = _evaluator().evaluate(_action(), future)

    assert receipt.ready is False
    assert "batch_sealed_in_future" in receipt.gaps


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

    await runner.run((_action(),))
    assert len(audit.audit_entries) == 1


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


async def test_measurement_runner_distinguishes_evaluation_failure() -> None:
    class _FailingEvaluator:
        def evaluate(self, action_type, batch):  # type: ignore[no-untyped-def]
            raise ValueError("malformed measurement")

    audit = InMemoryStateStore()
    runner = OperationalPromotionMeasurementRunner(
        source=_Source(),
        evaluator=_FailingEvaluator(),  # type: ignore[arg-type]
        audit_store=audit,
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
    )

    (result,) = await runner.run((_action(),))

    assert result.aborted_reason == "evidence_evaluation_failed:ValueError"
    entry = audit.audit_entries[0]["entry"]
    assert entry["gaps"] == ["evidence_evaluation_failed:ValueError"]
    assert entry["evidence_digest"] == _passing_batch().content_digest


async def test_evaluation_failure_does_not_block_later_success_audit() -> None:
    class _FlakyEvaluator:
        def __init__(self) -> None:
            self.failed = False

        def evaluate(self, action_type, batch):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise ValueError("transient evaluator failure")
            return _evaluator().evaluate(action_type, batch)

    audit = InMemoryStateStore()
    runner = OperationalPromotionMeasurementRunner(
        source=_Source(),
        evaluator=_FlakyEvaluator(),  # type: ignore[arg-type]
        audit_store=audit,
        fdai_revision=_REVISION,
        scenario_set_version=_SCENARIO,
    )

    (failed,) = await runner.run((_action(),))
    (succeeded,) = await runner.run((_action(),))

    assert failed.receipt is None
    assert succeeded.receipt is not None
    assert succeeded.receipt.ready is True
    assert [entry["entry"]["ready"] for entry in audit.audit_entries] == [False, True]


def test_registry_requires_matching_verified_operational_receipt() -> None:
    action = _action()
    receipt = _evaluator().evaluate(action, _passing_batch())
    metrics = PromotionMetrics(
        action_type=action.name,
        shadow_days=receipt.live_observation_days,
        samples=receipt.sample_count,
        accuracy=receipt.accuracy,
        policy_escapes=receipt.policy_escapes,
    )

    raw_registry = ActionPromotionRegistry()
    assert raw_registry.consider_promotion(action_type=action, metrics=metrics).mode.value == (
        "shadow"
    )

    class _ReceiptVerifier:
        def verify(self, *, action_type, receipt):  # type: ignore[no-untyped-def]
            return receipt.evidence_digest == _passing_batch().content_digest

    verified_registry = ActionPromotionRegistry(receipt_verifier=_ReceiptVerifier())
    record = verified_registry.consider_promotion(
        action_type=action,
        metrics=metrics,
        receipt=receipt,
    )

    assert record.mode.value == "enforce"
    assert record.promotion_evidence_digest == receipt.evidence_digest
    assert record.fdai_revision == _REVISION

    replayed = verified_registry.consider_promotion(
        action_type=action,
        metrics=metrics,
        receipt=receipt,
    )
    assert replayed.promoted_at == record.promoted_at
