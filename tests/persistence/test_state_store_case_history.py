from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.delivery.persistence.state_store_case_history import (
    StateStoreCaseHistoryMetadataStore,
)
from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _record(*, revision: int = 1, parent: str | None = None) -> CaseHistoryRevisionRecord:
    return CaseHistoryRevisionRecord(
        case_id="case-1",
        revision=revision,
        kind="prediction",
        correlation_id="corr-1",
        purpose="forecast-error-analysis",
        access_scope_digest="a" * 64,
        manifest_digest=("b" if revision == 1 else "c") * 64,
        parent_manifest_digest=parent,
        source_set_digest=("d" if revision == 1 else "e") * 64,
        storage_ref=f"case-history/case-1/{revision}.json",
        artifact_size=100,
        outcome_label="false_positive",
        detector_id="capacity-linear",
        detector_version="1.0.0",
        metric="capacity_percent",
        event_time_cutoff=T0,
        created_by_agent="Muninn",
        sealed_at=T0 + timedelta(hours=1),
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
    )


async def test_state_store_append_is_idempotent_and_audited() -> None:
    state = InMemoryStateStore()
    store = StateStoreCaseHistoryMetadataStore(store=state)
    record = _record()
    assert await store.append_revision(record) is True
    assert await store.append_revision(record) is False
    assert len(tuple(state.audit_entries)) == 1
    assert state.verify_chain()


async def test_state_store_appends_parent_linked_revision() -> None:
    state = InMemoryStateStore()
    store = StateStoreCaseHistoryMetadataStore(store=state)
    first = _record()
    second = _record(revision=2, parent=first.manifest_digest)
    assert await store.append_revision(first) is True
    assert await store.append_revision(second) is True
    assert await store.latest("case-1", access_scope_digest="a" * 64) == second


async def test_state_store_rejects_revision_gap() -> None:
    store = StateStoreCaseHistoryMetadataStore(store=InMemoryStateStore())
    with pytest.raises((RuntimeError, ValueError), match="CAS failed|revision or parent"):
        await store.append_revision(_record(revision=2, parent="b" * 64))


async def test_state_store_rejects_scope_change() -> None:
    store = StateStoreCaseHistoryMetadataStore(store=InMemoryStateStore())
    record = _record()
    await store.append_revision(record)
    changed = replace(
        _record(revision=2, parent=record.manifest_digest),
        access_scope_digest="f" * 64,
    )
    with pytest.raises(PermissionError, match="scope cannot change"):
        await store.append_revision(changed)


async def test_state_store_retention_tombstones_due_case_and_audits() -> None:
    state = InMemoryStateStore()
    store = StateStoreCaseHistoryMetadataStore(store=state)
    record = _record()
    await store.append_revision(record)
    due = await store.list_due(now=record.deletion_due_at, limit=10)
    assert due == (record,)
    pending = await store.mark_deletion_started(
        record.case_id,
        access_scope_digest=record.access_scope_digest,
        revision=record.revision,
        storage_refs=(record.storage_ref or "",),
        started_at=record.deletion_due_at,
    )
    assert pending.deletion_started_at == record.deletion_due_at
    assert pending.state_revision == 2
    deleted = await store.mark_deleted(
        record.case_id,
        access_scope_digest=record.access_scope_digest,
        revision=record.revision,
        deleted_at=record.deletion_due_at,
    )
    assert deleted.storage_ref is None
    assert deleted.deleted_at == record.deletion_due_at
    assert deleted.state_revision == 3
    assert (
        await store.latest(record.case_id, access_scope_digest=record.access_scope_digest)
        == deleted
    )
    assert (
        await store.mark_deleted(
            record.case_id,
            access_scope_digest=record.access_scope_digest,
            revision=record.revision,
            deleted_at=record.deletion_due_at,
        )
        == deleted
    )
    assert len(tuple(state.audit_entries)) == 3


async def test_state_store_pending_deletion_blocks_new_revision() -> None:
    store = StateStoreCaseHistoryMetadataStore(store=InMemoryStateStore())
    first = _record()
    await store.append_revision(first)
    await store.mark_deletion_started(
        first.case_id,
        access_scope_digest=first.access_scope_digest,
        revision=first.revision,
        storage_refs=(first.storage_ref or "",),
        started_at=first.deletion_due_at,
    )
    with pytest.raises(PermissionError, match="pending deletion"):
        await store.append_revision(_record(revision=2, parent=first.manifest_digest))


async def test_state_store_legal_hold_is_not_due_or_deletable() -> None:
    store = StateStoreCaseHistoryMetadataStore(store=InMemoryStateStore())
    held = replace(_record(), legal_hold=True, legal_hold_ref="hold-1")
    await store.append_revision(held)
    assert await store.list_due(now=held.deletion_due_at, limit=10) == ()
    with pytest.raises(PermissionError, match="legal hold"):
        await store.mark_deleted(
            held.case_id,
            access_scope_digest=held.access_scope_digest,
            revision=held.revision,
            deleted_at=held.deletion_due_at,
        )


async def test_state_store_pages_beyond_legacy_five_thousand_row_cap() -> None:
    state = InMemoryStateStore()
    oldest = replace(
        _record(),
        case_id="case-oldest",
        sealed_at=T0,
        deletion_due_at=T0 + timedelta(days=31),
    )
    records = [
        replace(
            _record(),
            case_id=f"case-{index:04d}",
            sealed_at=T0 + timedelta(seconds=index + 1),
            deletion_due_at=T0 + timedelta(days=32),
        )
        for index in range(5_000)
    ] + [oldest]
    for record in records:
        raw = asdict(record)
        raw["schema_version"] = "1.0.0"
        for field in (
            "event_time_cutoff",
            "sealed_at",
            "retention_until",
            "deletion_due_at",
        ):
            raw[field] = raw[field].isoformat()
        await state.write_state(f"case-history:latest:{record.case_id}", raw)

    store = StateStoreCaseHistoryMetadataStore(store=state)
    due = await store.list_due(now=T0 + timedelta(days=31), limit=1)
    assert due == (oldest,)
