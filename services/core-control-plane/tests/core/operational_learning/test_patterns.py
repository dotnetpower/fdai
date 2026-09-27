from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.case_history import (
    OperationalOutcomeClass,
    OperationalReceiptType,
    compile_operational_case,
)
from fdai.core.operational_learning import (
    OperatingPatternCompiler,
    PatternCase,
    pattern_case_from_operational_case,
)
from fdai.core.operational_learning.cohort_retention import (
    LegacyCaseCohortRetention,
    cohort_state_key,
    retain_cohort_case,
)
from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.case_history.test_operational_case import _case_input, _receipt


def _pattern_case(
    identifier: str,
    outcome_class: OperationalOutcomeClass,
):  # type: ignore[no-untyped-def]
    case_input = _case_input(outcome_class=outcome_class)
    if outcome_class is OperationalOutcomeClass.SUCCESS:
        receipts = tuple(
            _receipt(
                OperationalReceiptType.AUDIT,
                "1",
                (("event_type", "action.completed"), ("decision", "auto"), ("mode", "enforce")),
            )
            if receipt.receipt_type is OperationalReceiptType.AUDIT
            else receipt
            for receipt in case_input.receipts
        )
        case_input = replace(case_input, receipts=receipts)
    projection = compile_operational_case(case_input).projection(
        case_id=f"case-{identifier}",
        case_revision=1,
        manifest_digest=identifier * 64,
    )
    return pattern_case_from_operational_case(case_input, projection)


def test_only_verified_enforce_outcome_is_reusable() -> None:
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)

    assert case is not None
    assert case.reusable is True
    assert case.negative is False


async def _retain(store: InMemoryStateStore, case: PatternCase) -> dict[str, Any]:
    return await retain_cohort_case(
        store,
        key="operational-case-fingerprint-cohort:v2:example",
        case=case,
        access_scope_digest="a" * 64,
        purpose="operational-learning",
        recorded_at=case.event_time_cutoff,
    )


def _cohort_key(case: PatternCase) -> str:
    return cohort_state_key(
        access_scope_digest="a" * 64,
        purpose="operational-learning",
        failure_fingerprint=case.failure_fingerprint,
        action_type=case.action_type,
        fdai_revision=case.fdai_revision,
        scenario_set_version=case.scenario_set_version,
        source_kind=case.source_kind.value,
        source_synthetic=case.source_synthetic,
    )


async def _retain_legacy(store: InMemoryStateStore, case: PatternCase) -> dict[str, Any]:
    return await retain_cohort_case(
        store,
        key=_cohort_key(case),
        case=case,
        access_scope_digest="a" * 64,
        purpose="operational-learning",
        recorded_at=case.event_time_cutoff,
    )


def _deletion_record(
    case: PatternCase,
    *,
    legal_hold: bool = False,
) -> CaseHistoryRevisionRecord:
    deletion_due_at = case.event_time_cutoff + timedelta(days=2)
    return CaseHistoryRevisionRecord(
        case_id=case.case_id,
        revision=case.revision,
        kind="action",
        correlation_id=f"correlation-{case.case_id}",
        purpose="operational-learning",
        access_scope_digest="a" * 64,
        manifest_digest=case.manifest_digest,
        parent_manifest_digest=None,
        source_set_digest="d" * 64,
        storage_ref=f"case-history/{case.case_id}",
        artifact_size=1,
        outcome_label=case.outcome_class.value,
        detector_id=None,
        detector_version=None,
        metric=None,
        event_time_cutoff=case.event_time_cutoff,
        created_by_agent="Muninn",
        sealed_at=case.event_time_cutoff,
        retention_until=case.event_time_cutoff + timedelta(days=1),
        deletion_due_at=deletion_due_at,
        metadata=(
            ("action_type", case.action_type),
            ("failure_fingerprint", case.failure_fingerprint),
            ("fdai_revision", case.fdai_revision),
            ("operational_outcome", case.outcome_class.value),
            ("resource_type", case.resource_type),
            ("scenario_set_version", case.scenario_set_version),
            ("source_identity_digest", case.source_identity_digest),
            ("source_kind", case.source_kind.value),
        ),
        legal_hold=legal_hold,
        legal_hold_ref="hold-authority" if legal_hold else None,
        deletion_started_at=deletion_due_at,
        deletion_storage_refs=(f"case-history/{case.case_id}",),
    )


async def test_concurrent_cohort_writers_retain_both_cases() -> None:
    class _RacingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0
            self.joined = asyncio.Event()

        async def read_state(self, key: str) -> Any:
            snapshot = await super().read_state(key)
            self.reads += 1
            if self.reads <= 2:
                if self.reads == 2:
                    self.joined.set()
                await self.joined.wait()
            return snapshot

    store = _RacingStore()
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    control = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and control is not None
    await asyncio.wait_for(
        asyncio.gather(_retain(store, success), _retain(store, control)), timeout=2
    )
    result = await store.read_state("operational-case-fingerprint-cohort:v2:example")
    assert result["revision"] == 2
    assert {record["case"]["case_id"] for record in result["cases"]} == {
        success.case_id,
        control.case_id,
    }


async def test_old_and_duplicate_case_revisions_do_not_change_cohort() -> None:
    store = InMemoryStateStore()
    original = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert original is not None
    newer = replace(original, revision=2, manifest_digest="b" * 64)
    await _retain(store, original)
    current = await _retain(store, newer)
    assert await _retain(store, original) == current
    assert await _retain(store, newer) == current
    assert len(current["cases"]) == 1
    assert current["cases"][0]["case"]["revision"] == 2
    with pytest.raises(ValueError, match="immutable case conflict"):
        await _retain(store, replace(newer, manifest_digest="c" * 64))


async def test_cohort_contention_has_a_finite_retry_budget() -> None:
    class _ContendedStore(InMemoryStateStore):
        attempts = 0

        async def write_state_with_audit_if_absent(self, *args: Any, **kwargs: Any) -> bool:
            del args, kwargs
            self.attempts += 1
            return False

        async def compare_and_set_state_with_audit(self, *args: Any, **kwargs: Any) -> bool:
            del args, kwargs
            self.attempts += 1
            return False

    store = _ContendedStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None
    with pytest.raises(RuntimeError, match="budget exhausted"):
        await _retain(store, case)
    assert store.attempts == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"access_scope_digest": "b" * 64},
        {"revision": True},
        {"cases": "invalid"},
        {"cases": [None]},
        {"deleted_case_ids": "invalid"},
        {"retired": "invalid"},
    ],
)
async def test_malformed_cohort_is_not_silently_rebuilt(changes: dict[str, Any]) -> None:
    store = InMemoryStateStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None
    state = await _retain(store, case)
    await store.write_state("operational-case-fingerprint-cohort:v2:example", {**state, **changes})
    with pytest.raises(ValueError, match="cohort"):
        await _retain(store, case)


async def test_first_cohort_uses_atomic_create_not_update_only_cas() -> None:
    class _UpdateOnlyStore(InMemoryStateStore):
        async def compare_and_set_state_with_audit(self, key, value, **kwargs):
            if await self.read_state(key) is None:
                raise AssertionError("PostgreSQL CAS cannot create a missing row")
            return await super().compare_and_set_state_with_audit(key, value, **kwargs)

    store = _UpdateOnlyStore()
    first = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    second = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert first is not None and second is not None
    assert (await _retain(store, first))["revision"] == 1
    assert (await _retain(store, second))["revision"] == 2


async def test_legacy_cohort_purge_removes_body_and_fences_replay() -> None:
    store = InMemoryStateStore()
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    retained = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and retained is not None
    await _retain_legacy(store, deleted)
    await _retain_legacy(store, retained)

    retention = LegacyCaseCohortRetention(store=store)
    record = _deletion_record(deleted)
    await retention.purge(record)

    state = await store.read_state(_cohort_key(deleted))
    assert state is not None
    assert state["deleted_case_ids"] == [deleted.case_id]
    assert [item["case"]["case_id"] for item in state["cases"]] == [retained.case_id]
    with pytest.raises(PermissionError, match="deletion fence"):
        await _retain_legacy(store, deleted)

    restarted = LegacyCaseCohortRetention(store=store)
    await restarted.purge(record)
    assert await store.read_state(_cohort_key(deleted)) == state


async def test_legacy_cohort_purge_fences_an_absent_late_writer() -> None:
    store = InMemoryStateStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None

    await LegacyCaseCohortRetention(store=store).purge(_deletion_record(case))

    state = await store.read_state(_cohort_key(case))
    assert state is not None
    assert state["cases"] == []
    assert state["deleted_case_ids"] == [case.case_id]
    with pytest.raises(PermissionError, match="deletion fence"):
        await _retain_legacy(store, case)


async def test_legacy_cohort_purge_preserves_held_body() -> None:
    store = InMemoryStateStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None
    before = await _retain_legacy(store, case)

    with pytest.raises(PermissionError, match="unheld source deletion claim"):
        await LegacyCaseCohortRetention(store=store).purge(_deletion_record(case, legal_hold=True))

    assert await store.read_state(_cohort_key(case)) == before


async def test_legacy_cohort_purge_keeps_unrelated_bodies_at_fence_capacity() -> None:
    store = InMemoryStateStore()
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    retained = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and retained is not None
    state = await _retain_legacy(store, deleted)
    state = await _retain_legacy(store, retained)
    saturated = {
        **state,
        "deleted_case_ids": [f"deleted-{index}" for index in range(1000)],
    }
    await store.write_state(_cohort_key(deleted), saturated)

    with pytest.raises(RuntimeError, match="fence capacity exhausted"):
        await LegacyCaseCohortRetention(store=store).purge(_deletion_record(deleted))

    assert await store.read_state(_cohort_key(deleted)) == saturated


async def test_legacy_cohort_purge_ignores_prediction_records() -> None:
    store = InMemoryStateStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None
    prediction = replace(
        _deletion_record(case),
        kind="prediction",
        outcome_label="true_positive",
        detector_id="detector",
        detector_version="v1",
        metric="cpu",
        metadata=(),
    )

    await LegacyCaseCohortRetention(store=store).purge(prediction)

    assert await store.read_states("operational-case-fingerprint-cohort:v2:", limit=10) == ()


def test_mismatch_is_negative_evidence() -> None:
    case = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)

    assert case is not None
    assert case.reusable is False
    assert case.negative is True


def test_compiler_requires_one_fingerprint_and_action_with_balanced_evidence() -> None:
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    rollback = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and rollback is not None

    candidate = OperatingPatternCompiler().compile((success, rollback))

    assert candidate is not None
    assert candidate.failure_fingerprint == success.failure_fingerprint
    assert dict(candidate.outcome_counts) == {"rollback": 1, "success": 1}
    assert candidate.immutable_case_refs == (
        success.immutable_case_ref,
        rollback.immutable_case_ref,
    )
    assert (
        OperatingPatternCompiler().compile(
            (success, replace(rollback, action_type="ops.scale-out"))
        )
        is None
    )
    assert (
        OperatingPatternCompiler().compile(
            (success, replace(rollback, failure_fingerprint="f" * 64))
        )
        is None
    )


def test_success_without_explicit_rollback_result_is_not_reusable() -> None:
    case_input = _case_input(outcome_class=OperationalOutcomeClass.SUCCESS)
    receipts = []
    for receipt in case_input.receipts:
        if receipt.receipt_type is OperationalReceiptType.AUDIT:
            receipts.append(
                replace(
                    receipt,
                    facts=tuple(
                        (key, "enforce" if key == "mode" else value) for key, value in receipt.facts
                    ),
                )
            )
        elif receipt.receipt_type is OperationalReceiptType.RESPONSE_OUTCOME:
            receipts.append(
                replace(
                    receipt,
                    facts=tuple(
                        (key, value) for key, value in receipt.facts if key != "rollback_succeeded"
                    ),
                )
            )
        else:
            receipts.append(receipt)
    case_input = replace(case_input, receipts=tuple(receipts))
    projection = compile_operational_case(case_input).projection(
        case_id="case-missing-rollback",
        case_revision=1,
        manifest_digest="c" * 64,
    )

    assert pattern_case_from_operational_case(case_input, projection) is None


def test_pattern_case_and_cohort_inputs_are_bounded() -> None:
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    rollback = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and rollback is not None

    with pytest.raises(ValueError, match="case id"):
        replace(success, case_id="x" * 257)
    with pytest.raises(ValueError, match="digest evidence"):
        replace(success, digest_evidence=tuple(f"{index:064x}" for index in range(65)))
    cases: tuple[PatternCase, ...] = tuple(
        replace(
            success if index % 2 == 0 else rollback,
            case_id=f"case-{index}",
            manifest_digest=f"{index + 1:064x}",
        )
        for index in range(101)
    )
    with pytest.raises(ValueError, match="case limit"):
        OperatingPatternCompiler().compile(cases)
