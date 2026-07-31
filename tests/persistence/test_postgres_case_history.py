from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from uuid import uuid4

import pytest

from fdai.delivery.persistence.postgres_case_history import (
    PostgresCaseHistoryMetadataStore,
    PostgresCaseHistoryMetadataStoreConfig,
)
from tests.persistence.test_state_store_case_history import _record


def test_config_rejects_empty_dsn_and_invalid_timeouts() -> None:
    with pytest.raises(ValueError, match="DSN"):
        PostgresCaseHistoryMetadataStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresCaseHistoryMetadataStoreConfig(dsn="postgresql://example", connect_timeout_s=0)


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_relational_store_append_filter_and_deletion_lifecycle() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    store = PostgresCaseHistoryMetadataStore(config=PostgresCaseHistoryMetadataStoreConfig(dsn=dsn))
    suffix = uuid4().hex
    first_digest = hashlib.sha256(f"first:{suffix}".encode()).hexdigest()
    second_digest = hashlib.sha256(f"second:{suffix}".encode()).hexdigest()
    first_source = hashlib.sha256(f"source-first:{suffix}".encode()).hexdigest()
    second_source = hashlib.sha256(f"source-second:{suffix}".encode()).hexdigest()
    first = replace(
        _record(),
        case_id=f"case-{suffix}",
        manifest_digest=first_digest,
        source_set_digest=first_source,
    )
    second = replace(
        _record(revision=2, parent=first_digest),
        case_id=first.case_id,
        manifest_digest=second_digest,
        source_set_digest=second_source,
    )
    try:
        assert await store.append_revision(first) is True
        assert await store.append_revision(first) is False
        assert await store.append_revision(second) is True
        assert (
            await store.latest(first.case_id, access_scope_digest=first.access_scope_digest)
            == second
        )
        listed = await store.list_closed(
            access_scope_digest=first.access_scope_digest,
            purpose=first.purpose,
            outcome_labels=(first.outcome_label,),
            detector_id=first.detector_id,
            metric=first.metric,
            limit=100,
        )
        assert second in listed
        pending = await store.mark_deletion_started(
            first.case_id,
            access_scope_digest=first.access_scope_digest,
            revision=second.revision,
            storage_refs=(first.storage_ref or "", second.storage_ref or ""),
            started_at=second.deletion_due_at,
        )
        assert pending.deletion_started_at == second.deletion_due_at
        deleted = await store.mark_deleted(
            first.case_id,
            access_scope_digest=first.access_scope_digest,
            revision=second.revision,
            deleted_at=second.deletion_due_at,
        )
        assert deleted.deleted_at == second.deletion_due_at
        assert deleted.storage_ref is None
    finally:
        import psycopg

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM case_history_chunk WHERE case_id = %s", (first.case_id,)
            )
            await connection.execute(
                "DELETE FROM case_history_revision WHERE case_id = %s", (first.case_id,)
            )
            await connection.execute(
                "DELETE FROM case_history WHERE case_id = %s", (first.case_id,)
            )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_relational_store_backfills_deleted_tombstone() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    store = PostgresCaseHistoryMetadataStore(config=PostgresCaseHistoryMetadataStoreConfig(dsn=dsn))
    suffix = uuid4().hex
    active = replace(
        _record(),
        case_id=f"case-tombstone-{suffix}",
        manifest_digest=hashlib.sha256(f"tombstone:{suffix}".encode()).hexdigest(),
        source_set_digest=hashlib.sha256(f"source:{suffix}".encode()).hexdigest(),
    )
    tombstone = replace(
        active,
        storage_ref=None,
        artifact_size=0,
        deletion_started_at=active.deletion_due_at,
        deleted_at=active.deletion_due_at,
        state_revision=3,
    )
    try:
        assert await store.backfill_tombstone(tombstone) is True
        assert await store.backfill_tombstone(tombstone) is False
        assert (
            await store.latest(
                tombstone.case_id,
                access_scope_digest=tombstone.access_scope_digest,
            )
            == tombstone
        )
    finally:
        import psycopg

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM case_history_revision WHERE case_id = %s", (tombstone.case_id,)
            )
            await connection.execute(
                "DELETE FROM case_history WHERE case_id = %s", (tombstone.case_id,)
            )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_relational_store_round_trips_operational_metadata() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    store = PostgresCaseHistoryMetadataStore(config=PostgresCaseHistoryMetadataStoreConfig(dsn=dsn))
    suffix = uuid4().hex
    operational = replace(
        _record(),
        case_id=f"case-operational-{suffix}",
        kind="incident",
        manifest_digest=hashlib.sha256(f"operational:{suffix}".encode()).hexdigest(),
        source_set_digest=hashlib.sha256(f"operational-source:{suffix}".encode()).hexdigest(),
        outcome_label="recurrence",
        detector_id=None,
        detector_version=None,
        metric=None,
        metadata=(
            ("action_type", "ops.restart-service"),
            ("failure_fingerprint", "f" * 64),
            ("operational_outcome", "recurrence"),
            ("resource_type", "kubernetes.service"),
        ),
    )
    try:
        assert await store.append_revision(operational) is True
        assert await store.append_revision(operational) is False
        assert (
            await store.latest(
                operational.case_id,
                access_scope_digest=operational.access_scope_digest,
            )
            == operational
        )
    finally:
        import psycopg

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM case_history_revision WHERE case_id = %s", (operational.case_id,)
            )
            await connection.execute(
                "DELETE FROM case_history WHERE case_id = %s", (operational.case_id,)
            )
