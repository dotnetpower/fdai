"""PostgreSQL Kubernetes lifecycle persistence and concurrency tests."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KUBERNETES_LIFECYCLE_KILLING,
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_lifecycle_collector import (
    KubernetesLifecycleAppendReceipt,
    KubernetesLifecycleCursorConflictError,
)
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleStore,
    PostgresKubernetesLifecycleStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_ROOT = REPO_ROOT / "service-migrations"
_SERVICE_ID = "core-control-plane"
_NOW = datetime(2026, 8, 28, 4, 0, tzinfo=UTC)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_legacy_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _bootstrap_core_control_plane(evidence_dir: Path) -> None:
    """Adopt (or advance to head) the `core-control-plane` service migration branch.

    The Kubernetes lifecycle tables are owned by the newer per-service migration
    branch at `service-migrations/branches/core-control-plane`, not the legacy
    `alembic/versions` tree that `_upgrade_legacy_head` applies. Bringing a fresh
    database up to date therefore requires the dedicated adoption/upgrade flow in
    `service_migrations.cli` rather than a plain `alembic upgrade head`; this mirrors
    the private-function precedent already used by
    `tests/integration/services/test_service_migration_inventory.py`.
    """

    if str(_MIGRATION_ROOT) not in sys.path:
        sys.path.insert(0, str(_MIGRATION_ROOT))
    import service_migrations.cli as service_cli

    inventory = service_cli.load_legacy_inventory(REPO_ROOT / "alembic" / "versions")
    ownership = service_cli.load_ownership_manifest(
        service_cli.MIGRATION_ROOT / "ownership.json", inventory
    )
    adoptions = service_cli.validate_service_branches(
        service_cli.MIGRATION_ROOT, inventory, ownership
    )
    schema_contract = service_cli.load_schema_contract(
        service_cli.MIGRATION_ROOT / "legacy-schema-contract.json",
        expected_legacy_head=inventory.heads[0],
        expected_legacy_revision_count=len(inventory.down_revisions),
    )
    adoption = adoptions[_SERVICE_ID]
    if service_cli._read_versions(adoption.service_version_table) is not None:
        service_cli._upgrade_service(
            _SERVICE_ID, revision="head", sql=False, ownership=ownership, adoptions=adoptions
        )
        return
    legacy_owned_tables = tuple(
        table
        for table, owner in ownership.table_migrators.items()
        if owner == _SERVICE_ID and table in inventory.table_sources
    )
    service_cli._bootstrap_service(
        _SERVICE_ID,
        adoption=adoption,
        expected_schema_fingerprint=schema_contract[_SERVICE_ID].digest,
        legacy_owned_tables=legacy_owned_tables,
        evidence_output=evidence_dir / "evidence.json",
        schema_output=evidence_dir / "schema.json",
        rollback_reference="test-harness",
        ownership=ownership,
        adoptions=adoptions,
    )


def _upgrade_head(evidence_dir: Path) -> None:
    _upgrade_legacy_head()
    _bootstrap_core_control_plane(evidence_dir)


def _observation(
    *,
    cluster_ref: str = "cluster-a",
    object_uid: str,
    reason: str = "Killing",
    category: str = KUBERNETES_LIFECYCLE_KILLING,
    evidence_ref: str | None = None,
) -> KubernetesLifecycleObservation:
    ref = evidence_ref or (
        f"kubernetes-lifecycle:{hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()}"
    )
    return KubernetesLifecycleObservation(
        cluster_ref=cluster_ref,
        namespace="default",
        object_uid=object_uid,
        owner_uid=None,
        reason=reason,
        category=category,
        event_type="Warning",
        event_time=_NOW,
        recorded_time=_NOW,
        source_revision="100",
        evidence_ref=ref,
    )


@pytest.mark.integration
async def test_cursor_and_observations_persist_across_a_restart(tmp_path: Path) -> None:
    dsn = _requires_live_db()
    _upgrade_head(tmp_path)
    cluster_ref = f"cluster-{uuid.uuid4().hex[:8]}"
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn))

    assert await store.read_cursor(cluster_ref) is None
    receipt = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=None,
        next_cursor="150",
        observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-1"),),
    )
    assert receipt == KubernetesLifecycleAppendReceipt(
        cluster_ref=cluster_ref, inserted_count=1, duplicate_count=0, cursor="150"
    )

    restarted = PostgresKubernetesLifecycleStore(
        config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn)
    )
    assert await restarted.read_cursor(cluster_ref) == "150"


@pytest.mark.integration
async def test_duplicate_evidence_ref_is_rejected_idempotently(tmp_path: Path) -> None:
    dsn = _requires_live_db()
    _upgrade_head(tmp_path)
    cluster_ref = f"cluster-{uuid.uuid4().hex[:8]}"
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn))
    observation = _observation(cluster_ref=cluster_ref, object_uid="pod-1")

    first = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=None,
        next_cursor="100",
        observations=(observation,),
    )
    assert first.inserted_count == 1 and first.duplicate_count == 0

    # A duplicate delivery of the same evidence_ref (retry, redelivery, or reordered
    # re-send) MUST be rejected without corrupting the cursor or double-counting.
    second = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor="100",
        next_cursor="100",
        observations=(observation,),
    )
    assert second.inserted_count == 0 and second.duplicate_count == 1
    assert await store.read_cursor(cluster_ref) == "100"


@pytest.mark.integration
async def test_stale_previous_cursor_raises_conflict_and_does_not_mutate(tmp_path: Path) -> None:
    dsn = _requires_live_db()
    _upgrade_head(tmp_path)
    cluster_ref = f"cluster-{uuid.uuid4().hex[:8]}"
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn))
    await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=None,
        next_cursor="100",
        observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-1"),),
    )

    with pytest.raises(KubernetesLifecycleCursorConflictError):
        await store.append(
            cluster_ref=cluster_ref,
            previous_cursor="1",
            next_cursor="200",
            observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-2"),),
        )

    # The rejected append MUST NOT have advanced the cursor or admitted its observation.
    assert await store.read_cursor(cluster_ref) == "100"


@pytest.mark.integration
async def test_expiry_gap_clears_the_durable_cursor(tmp_path: Path) -> None:
    dsn = _requires_live_db()
    _upgrade_head(tmp_path)
    cluster_ref = f"cluster-{uuid.uuid4().hex[:8]}"
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn))
    await store.append(
        cluster_ref=cluster_ref,
        previous_cursor=None,
        next_cursor="100",
        observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-1"),),
    )

    expired = await store.append(
        cluster_ref=cluster_ref,
        previous_cursor="100",
        next_cursor=None,
        observations=(),
    )
    assert expired.cursor is None
    assert await store.read_cursor(cluster_ref) is None


@pytest.mark.integration
async def test_concurrent_first_appends_serialize_on_an_absent_cursor_row(
    tmp_path: Path,
) -> None:
    """Guard the advisory lock that closes the absent-row race.

    `SELECT ... FOR UPDATE` cannot lock a cursor row that does not exist yet, so
    without a per-cluster advisory lock two concurrent first-ever (or post-expiry)
    collections could both observe `previous_cursor is None`, both believe they are
    the sole writer, and both attempt to advance the cursor -- corrupting the
    resumption point and admitting an inconsistent evidence set. With the lock in
    place exactly one writer must win and the other must observe the conflict.
    """

    dsn = _requires_live_db()
    _upgrade_head(tmp_path)
    cluster_ref = f"cluster-{uuid.uuid4().hex[:8]}"
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn))

    results = await asyncio.gather(
        store.append(
            cluster_ref=cluster_ref,
            previous_cursor=None,
            next_cursor="10",
            observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-a"),),
        ),
        store.append(
            cluster_ref=cluster_ref,
            previous_cursor=None,
            next_cursor="20",
            observations=(_observation(cluster_ref=cluster_ref, object_uid="pod-b"),),
        ),
        return_exceptions=True,
    )

    succeeded = [item for item in results if isinstance(item, KubernetesLifecycleAppendReceipt)]
    conflicted = [
        item for item in results if isinstance(item, KubernetesLifecycleCursorConflictError)
    ]
    assert len(succeeded) == 1, f"expected exactly one winner, observed {results!r}"
    assert len(conflicted) == 1, f"expected exactly one conflict, observed {results!r}"

    final_cursor = await store.read_cursor(cluster_ref)
    assert final_cursor == succeeded[0].cursor
    assert succeeded[0].inserted_count == 1
