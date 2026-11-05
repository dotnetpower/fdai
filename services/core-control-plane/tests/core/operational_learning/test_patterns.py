from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
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
from fdai.core.operational_learning.legacy_suffix_retention import LegacyCaseSuffixRetention
from fdai.core.operational_learning.patterns import valid_pattern_publication_envelope
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


def _deletion_record(case: PatternCase, *, legal_hold: bool = False) -> CaseHistoryRevisionRecord:
    due = case.event_time_cutoff + timedelta(days=2)
    meta = (
        ("action_type", case.action_type),
        ("failure_fingerprint", case.failure_fingerprint),
        ("fdai_revision", case.fdai_revision),
        ("operational_outcome", case.outcome_class.value),
        ("resource_type", case.resource_type),
        ("scenario_set_version", case.scenario_set_version),
        ("source_identity_digest", case.source_identity_digest),
        ("source_kind", case.source_kind.value),
    )
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
        deletion_due_at=due,
        metadata=meta,
        legal_hold=legal_hold,
        legal_hold_ref="hold-authority" if legal_hold else None,
        deletion_started_at=due,
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


async def test_legacy_suffix_cleanup_preserves_held_peer_and_blocks_replay() -> None:
    store = InMemoryStateStore()
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    held = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and held is not None
    cohort = await _retain_legacy(store, deleted)
    cohort = await _retain_legacy(store, held)
    key = _cohort_key(deleted)
    digest = hashlib.sha256(
        json.dumps(cohort["cases"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot_key = f"{key}:snapshot:{digest}"
    pattern_key = f"{key}:pattern:{'e' * 64}"
    orphan_candidate_key = f"{key}:pattern:{'d' * 64}"
    emission_key = f"{key}:emitted:{digest}"
    pattern = {
        "schema_version": "1.0.0",
        "pattern_id": "e" * 64,
        "cohort_key": key,
        "access_scope_digest": "a" * 64,
        "purpose": "operational-learning",
        "cases": [deleted.to_mapping(), held.to_mapping()],
        "candidate": {"case_reviews": [deleted.to_mapping()]},
    }
    await store.write_state(snapshot_key, cohort)
    await store.write_state(pattern_key, pattern)
    await store.write_state(
        orphan_candidate_key,
        {
            **pattern,
            "pattern_id": "d" * 64,
            "cases": [held.to_mapping()],
            "candidate": {"immutable_case_refs": [deleted.immutable_case_ref]},
        },
    )
    await store.write_state(emission_key, {"digest": digest, "revision": cohort["revision"]})
    unrelated_key = f"operational-case-fingerprint-cohort:v2:{'f' * 64}:pattern:{'c' * 64}"
    await store.write_state(unrelated_key, {"untouched_scope": "b" * 64})
    await LegacyCaseCohortRetention(store=store).purge(_deletion_record(deleted))
    for _ in range(12):
        try:
            await LegacyCaseSuffixRetention(store=store).purge(_deletion_record(deleted))
            break
        except RuntimeError as exc:
            assert "pending" in str(exc)
    else:
        pytest.fail("historical suffix cleanup did not complete")

    snapshot = await store.read_state(snapshot_key)
    pattern_after = await store.read_state(pattern_key)
    emitted = await store.read_state(emission_key)
    assert snapshot is not None and snapshot["retired"] is True
    assert [row["case"]["case_id"] for row in snapshot["cases"]] == [held.case_id]
    assert pattern_after is not None and pattern_after["retired"] is True
    assert [case["case_id"] for case in pattern_after["cases"]] == [held.case_id]
    assert "candidate" not in pattern_after
    orphan = await store.read_state(orphan_candidate_key)
    assert orphan is not None and orphan["retired"] is True
    assert "candidate" not in orphan and orphan["cases"][0]["case_id"] == held.case_id
    assert emitted is not None and emitted["retired"] is True
    assert await store.read_state(unrelated_key) == {"untouched_scope": "b" * 64}
    assert await store.write_state_if_absent(snapshot_key, cohort) is False
    assert await store.write_state_if_absent(pattern_key, pattern) is False
    with pytest.raises(PermissionError, match="retired snapshot"):
        await retain_cohort_case(
            store,
            key=snapshot_key,
            case=deleted,
            access_scope_digest="a" * 64,
            purpose="operational-learning",
            recorded_at=deleted.event_time_cutoff,
        )
    assert await store.verify_chain() is True


async def test_legacy_suffix_hold_and_failed_readback_remain_pending() -> None:
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert deleted is not None
    store = InMemoryStateStore()
    cohort = await _retain_legacy(store, deleted)
    digest = hashlib.sha256(
        json.dumps(cohort["cases"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    key = f"{_cohort_key(deleted)}:snapshot:{digest}"
    await store.write_state(key, cohort)
    with pytest.raises(PermissionError, match="unheld"):
        await LegacyCaseSuffixRetention(store=store).purge(
            _deletion_record(deleted, legal_hold=True)
        )
    assert await store.read_state(key) == cohort

    class _MissingReadback(InMemoryStateStore):
        async def read_state(self, key: str) -> Any:
            value = await super().read_state(key)
            if key.endswith(digest) and value is not None and value.get("retired"):
                return None
            return value

    failed = _MissingReadback()
    await failed.write_state(key, cohort)
    with pytest.raises(RuntimeError, match="readback"):
        await LegacyCaseSuffixRetention(store=failed).purge(_deletion_record(deleted))


async def test_legacy_suffix_old_backend_without_optional_keyset_stays_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    assert case is not None
    cohort = await _retain_legacy(store, case)
    monkeypatch.setattr(store, "read_state_keys", None)
    with pytest.raises(RuntimeError, match="keyset-capable"):
        await LegacyCaseSuffixRetention(store=store).purge(_deletion_record(case))
    assert await store.read_state(_cohort_key(case)) == cohort


async def test_legacy_suffix_scan_resumes_many_rows_and_verifies_earlier_insert() -> None:
    store = InMemoryStateStore()
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    held = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and held is not None
    cohort = await _retain_legacy(store, deleted)
    cohort = await _retain_legacy(store, held)
    prefix = f"{_cohort_key(deleted)}:snapshot:"
    snapshots = []
    for index in range(70):
        variant = {**cohort, "revision": cohort["revision"] + index}
        variant["cases"] = [
            {**row, "recorded_at": f"2026-09-26T00:00:{index:02d}+00:00"} for row in cohort["cases"]
        ]
        digest = hashlib.sha256(
            json.dumps(variant["cases"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        key = prefix + digest
        snapshots.append(key)
        await store.write_state(key, variant)

    worker = LegacyCaseSuffixRetention(store=store)
    record = _deletion_record(deleted)
    with pytest.raises(RuntimeError, match="pending"):
        await worker.purge(record)
    # A late historical row ordered before the cursor is found in the second pass.
    checkpoints = await store.read_states("case-history:legacy-suffix-scan:v1:", limit=2)
    assert checkpoints
    cursor = next(item for item in checkpoints if item["after"])
    for index in range(1000):
        late = {
            **cohort,
            "cases": [{**row, "recorded_at": f"late-{index}"} for row in cohort["cases"]],
        }
        digest = hashlib.sha256(
            json.dumps(late["cases"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if prefix + digest < cursor["after"] and prefix + digest not in snapshots:
            late_key = prefix + digest
            await store.write_state(late_key, late)
            snapshots.append(late_key)
            break
    else:
        pytest.fail("could not construct a snapshot before the scan cursor")
    for _ in range(12):
        try:
            await LegacyCaseSuffixRetention(store=store).purge(record)
            break
        except RuntimeError as exc:
            assert "pending" in str(exc)
    else:
        pytest.fail("historical suffix scan did not reach independent verification")
    for key in snapshots:
        state = await store.read_state(key)
        assert state is not None and state["retired"] is True
        assert [row["case"]["case_id"] for row in state["cases"]] == [held.case_id]


def test_mismatch_is_negative_evidence() -> None:
    case = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)

    assert case is not None
    assert case.reusable is False
    assert case.negative is True


def test_compiler_requires_one_fingerprint_and_action_with_balanced_evidence() -> None:
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    rollback = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and rollback is not None

    compiler = OperatingPatternCompiler()
    candidate = compiler.compile((success, rollback))
    assert candidate is not None
    assert candidate.failure_fingerprint == success.failure_fingerprint
    assert dict(candidate.outcome_counts) == {"rollback": 1, "success": 1}
    assert candidate.immutable_case_refs == (
        success.immutable_case_ref,
        rollback.immutable_case_ref,
    )
    assert compiler.compile((success, replace(rollback, action_type="ops.scale-out"))) is None
    assert compiler.compile((success, replace(rollback, failure_fingerprint="f" * 64))) is None


def test_success_without_explicit_rollback_result_is_not_reusable() -> None:
    case_input = _case_input(outcome_class=OperationalOutcomeClass.SUCCESS)
    receipts = []
    for receipt in case_input.receipts:
        if receipt.receipt_type is OperationalReceiptType.AUDIT:
            facts = tuple((k, "enforce" if k == "mode" else v) for k, v in receipt.facts)
            receipts.append(replace(receipt, facts=facts))
        elif receipt.receipt_type is OperationalReceiptType.RESPONSE_OUTCOME:
            facts = tuple((k, v) for k, v in receipt.facts if k != "rollback_succeeded")
            receipts.append(replace(receipt, facts=facts))
        else:
            receipts.append(receipt)
    case_input = replace(case_input, receipts=tuple(receipts))
    projection = compile_operational_case(case_input).projection(
        case_id="case-missing-rollback", case_revision=1, manifest_digest="c" * 64
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


def test_pattern_envelope_and_case_validation_branches() -> None:
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    rollback = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and rollback is not None
    envelope = dict.fromkeys(
        (
            "producer_principal",
            "kind",
            "pattern_id",
            "cohort_key",
            "cohort_snapshot_ref",
            "access_scope_digest",
            "purpose",
            "correlation_id",
            "idempotency_key",
        ),
        "x",
    ) | {"schema_version": "1.0.0"}
    assert valid_pattern_publication_envelope(envelope) is True
    assert valid_pattern_publication_envelope({**envelope, "envelope_schema_version": 1}) is True
    assert not valid_pattern_publication_envelope({**envelope, "envelope_schema_version": True})
    for bad in (
        {"manifest_digest": "bad"},
        {"resource_type": "BAD"},
        {"reusable": False},
        {"outcome_class": "other", "reusable": False, "negative": False},
        {"fdai_revision": "bad"},
        {"scenario_set_version": "BAD"},
        {"event_time_cutoff": datetime(2026, 9, 26, 0, 0)},  # noqa: DTZ001
        {"source_identity_digest": "bad"},
        {"source_synthetic": "no"},
        {"conflict_digests": ("bad",)},
    ):
        with pytest.raises(ValueError):
            replace(success, **bad)  # type: ignore[arg-type]
    raw = success.to_mapping()
    assert PatternCase.from_mapping(raw) == success
    with pytest.raises(ValueError, match="standard schema"):
        PatternCase.from_mapping({})
    for key, val in (
        ("revision", True),
        ("reusable", "yes"),
        ("source_synthetic", "no"),
        ("outcome_class", "unsupported"),
        ("digest_evidence", "bad"),
        ("digest_evidence", []),
        ("digest_evidence", [1]),
        ("case_id", ""),
        ("event_time_cutoff", "2026-09-26T00:00:00"),
        ("conflict_digests", "bad"),
        ("conflict_digests", [1]),
    ):
        with pytest.raises(ValueError):
            PatternCase.from_mapping({**raw, key: val})
    compiler = OperatingPatternCompiler()
    candidate = compiler.compile((success, rollback))
    assert candidate is not None and candidate.to_rule_candidate_mapping()["proposed_by"] == "Norns"
    dup = replace(rollback, case_id=success.case_id, manifest_digest=success.manifest_digest)
    for bad_cohort in (
        (success,),
        (success, replace(rollback, fdai_revision="c" * 40)),
        (success, replace(rollback, evidence_complete=False)),
        (success, success),
        (success, dup),
    ):
        assert compiler.compile(bad_cohort) is None
    with pytest.raises(ValueError, match="review bounds"):
        compiler.compile((success, rollback), max_case_age=timedelta(0))
    many_ev = tuple(
        replace(
            success if i % 2 == 0 else rollback,
            case_id=f"c-{i}",
            manifest_digest=f"{i + 1:064x}",
            digest_evidence=tuple(f"{i * 100 + j + 1:064x}" for j in range(60)),
        )
        for i in range(5)
    )
    with pytest.raises(ValueError, match="aggregate limit"):
        compiler.compile(many_ev)
    case_in = _case_input(outcome_class=OperationalOutcomeClass.SUCCESS)
    proj = compile_operational_case(case_in).projection(
        case_id="c-inc", case_revision=1, manifest_digest="d" * 64
    )
    with pytest.raises(ValueError, match="sealed input"):
        pattern_case_from_operational_case(case_in, replace(proj, action_type="ops.other"))
    object.__setattr__(case_in, "outcome_class", "other")
    object.__setattr__(proj, "outcome_class", "other")
    assert pattern_case_from_operational_case(case_in, proj) is None


async def test_legacy_suffix_retention_error_and_edge_branches() -> None:
    store = InMemoryStateStore()
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    held = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and held is not None
    record, retention = _deletion_record(deleted), LegacyCaseSuffixRetention(store=store)
    pred = dict(
        kind="prediction",
        outcome_label="true_positive",
        detector_id="d",
        detector_version="v1",
        metric="cpu",
        metadata=(),
    )
    await retention.purge(replace(record, **pred))  # type: ignore[arg-type]
    cohort, ckey = await _retain_legacy(store, held), _cohort_key(deleted)
    cursor_hash = hashlib.sha256(f"{ckey}:{record.case_id}".encode()).hexdigest()
    cursor_key = f"case-history:legacy-suffix-scan:v1:{cursor_hash}"
    await store.write_state(cursor_key, {"after": f"{ckey}:unknown:{'a' * 64}"})
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        await retention._page(ckey, record)
    retention._store._state.pop(cursor_key, None)
    await store.write_state(f"{ckey}:other:1", {})
    with pytest.raises(ValueError, match="unknown historical cohort suffix"):
        await retention._page(ckey, record)
    retention._store._state.pop(f"{ckey}:other:1", None)
    no_keyset = LegacyCaseSuffixRetention(store=store)
    no_keyset._keyset = None
    with pytest.raises(RuntimeError, match="unavailable"):
        await no_keyset._page(ckey, record)
    digest = retention._digest(cohort["cases"])
    skey, skey_ok = f"{ckey}:snapshot:{'a' * 64}", f"{ckey}:snapshot:{digest}"
    pkey, ekey = f"{ckey}:pattern:{'b' * 64}", f"{ckey}:emitted:{digest}"
    for fn, missing_key in (
        (retention._snapshot, skey),
        (retention._pattern, pkey),
        (retention._emission, ekey),
    ):
        with pytest.raises(RuntimeError, match="disappeared"):
            await fn(missing_key, record, ckey)
    for bad_snap, msg in (
        ({**cohort, "failure_fingerprint": "f" * 64}, "fingerprint conflict"),
        (cohort, "digest conflict"),
    ):
        await store.write_state(skey, bad_snap)
        with pytest.raises(ValueError, match=msg):
            await retention._snapshot(skey, record, ckey)
    await store.write_state(skey_ok, cohort)
    await retention._snapshot(skey_ok, record, ckey)
    base_pat = {
        "schema_version": "1.0.0",
        "pattern_id": "b" * 64,
        "cohort_key": ckey,
        "access_scope_digest": "a" * 64,
        "purpose": "operational-learning",
        "cases": [held.to_mapping()],
    }
    for patch, msg in (
        ({"pattern_id": "wrong"}, "identity conflict"),
        ({"deleted_case_ids": "bad"}, "deletion fences"),
        ({"cases": [deleted.to_mapping()], "revision": True}, "Pattern revision"),
    ):
        await store.write_state(pkey, {**base_pat, **patch})
        with pytest.raises(ValueError, match=msg):
            await retention._pattern(pkey, record, ckey)
    await store.write_state(pkey, base_pat)
    await retention._pattern(pkey, record, ckey)
    await retention._emission(ekey, record, ckey, optional=True)
    await store.write_state(ekey, {"digest": "wrong", "revision": 1})
    with pytest.raises(ValueError, match="marker identity"):
        await retention._emission(ekey, record, ckey)
    for key_to_write, val in (
        (f"{ckey}:emitted:{'c' * 64}", {"digest": "c" * 64, "revision": 1}),
        (ekey, {"digest": digest, "revision": 1}),
    ):
        await store.write_state(key_to_write, val)
        await retention._emission(key_to_write, record, ckey)
    await store.write_state(
        skey_ok, {**cohort, "deleted_case_ids": [deleted.case_id], "retired": True}
    )
    await store.write_state(ekey, {"digest": digest, "revision": 1, "retired": True})
    await retention._emission(ekey, record, ckey)
    with pytest.raises(ValueError, match="row revision"):
        await retention._replace(ekey, {"revision": -1}, {}, record)
    with pytest.raises(RuntimeError, match="CAS or independent"):
        await retention._replace(ekey, {"revision": 99}, {}, record)
    for bad_cases in ([{}] * 101, ["bad"], [{"case": "bad"}]):
        with pytest.raises(ValueError):
            retention._remaining(bad_cases, "x")
    with pytest.raises(ValueError, match="cohort key is invalid"):
        retention._valid_suffix_key(f"{ckey}:snapshot:bad", ckey)
    assert retention._valid_suffix_key(f"{ckey}:unknown:{'a' * 64}", ckey) is False
    unclaimed = replace(record, deletion_started_at=None, deletion_storage_refs=())
    with pytest.raises(PermissionError, match="source deletion claim"):
        retention._audit(unclaimed, ekey, 1)
