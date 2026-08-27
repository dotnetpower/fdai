"""PostgreSQL Kubernetes lifecycle lease and idempotency tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleObservation,
)
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleConfig,
    PostgresKubernetesLifecycleStore,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value


def _observation(cluster_ref: str) -> KubernetesLifecycleObservation:
    digest = uuid4().hex.ljust(64, "0")
    return KubernetesLifecycleObservation(
        observation_id=f"sha256:{digest}",
        cluster_ref=cluster_ref,
        event_uid="event-uid",
        object_uid="pod-uid",
        object_kind="Pod",
        namespace="default",
        owner_uid="replica-set-uid",
        reason="BackOff",
        event_type="Warning",
        lifecycle_kind="backoff",
        action="modified",
        occurred_at=NOW,
        recorded_at=NOW,
        source_revision="opaque-revision",
        occurrence_count=17,
        evidence_ref=f"kubernetes-lifecycle:{digest}",
    )


async def test_lease_reacquire_duplicate_and_reorder_are_safe() -> None:
    dsn = _dsn()
    store = PostgresKubernetesLifecycleStore(config=PostgresKubernetesLifecycleConfig(dsn=dsn))
    cluster_ref = f"test-cluster:{uuid4()}"
    observation = _observation(cluster_ref)
    try:
        first = await store.acquire(
            cluster_ref=cluster_ref,
            holder="collector-a",
            now=NOW,
            lease_until=NOW + timedelta(seconds=30),
        )
        assert first is not None
        assert await store.append(
            KubernetesLifecycleBatch(
                cluster_ref=cluster_ref,
                expected_sequence=first.sequence,
                next_resume_token="opaque-seed",
                coverage_started_at=NOW,
                coverage_through_at=NOW,
                observations=(),
                limitation=None,
            ),
            holder="collector-a",
            now=NOW,
        )

        second = await store.acquire(
            cluster_ref=cluster_ref,
            holder="collector-b",
            now=NOW + timedelta(seconds=1),
            lease_until=NOW + timedelta(seconds=31),
        )
        assert second is not None
        assert second.sequence == 1
        observed_batch = KubernetesLifecycleBatch(
            cluster_ref=cluster_ref,
            expected_sequence=second.sequence,
            next_resume_token="opaque-observed",
            coverage_started_at=NOW,
            coverage_through_at=NOW + timedelta(seconds=20),
            observations=(observation,),
            limitation=None,
        )
        assert await store.append(
            observed_batch,
            holder="collector-b",
            now=NOW + timedelta(seconds=20),
        )

        third = await store.acquire(
            cluster_ref=cluster_ref,
            holder="collector-c",
            now=NOW + timedelta(seconds=21),
            lease_until=NOW + timedelta(seconds=51),
        )
        assert third is not None
        assert third.sequence == 2
        assert await store.append(
            KubernetesLifecycleBatch(
                cluster_ref=cluster_ref,
                expected_sequence=third.sequence,
                next_resume_token="opaque-duplicate",
                coverage_started_at=NOW,
                coverage_through_at=NOW + timedelta(seconds=40),
                observations=(observation,),
                limitation=None,
            ),
            holder="collector-c",
            now=NOW + timedelta(seconds=40),
        )

        fourth = await store.acquire(
            cluster_ref=cluster_ref,
            holder="collector-d",
            now=NOW + timedelta(seconds=41),
            lease_until=NOW + timedelta(seconds=71),
        )
        assert fourth is not None
        assert fourth.sequence == 3
        assert (
            await store.acquire(
                cluster_ref=cluster_ref,
                holder="collector-e",
                now=NOW + timedelta(seconds=42),
                lease_until=NOW + timedelta(seconds=72),
            )
            is None
        )
        assert not await store.append(
            KubernetesLifecycleBatch(
                cluster_ref=cluster_ref,
                expected_sequence=fourth.sequence,
                next_resume_token="opaque-reordered",
                coverage_started_at=NOW,
                coverage_through_at=NOW + timedelta(seconds=30),
                observations=(),
                limitation=None,
            ),
            holder="collector-d",
            now=NOW + timedelta(seconds=43),
        )

        current = await store.read_cursor(cluster_ref)
        retained = await store.read_observations(
            cluster_ref=cluster_ref,
            object_uid=None,
            since=NOW - timedelta(seconds=1),
        )
        assert current is not None
        assert current.sequence == 3
        assert len(retained) == 1
        assert retained[0].occurrence_count == 17
    finally:
        plain = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        async with await psycopg.AsyncConnection.connect(plain) as connection:
            await connection.execute(
                "DELETE FROM kubernetes_lifecycle_observation WHERE cluster_ref = %s",
                (cluster_ref,),
            )
            await connection.execute(
                "DELETE FROM kubernetes_lifecycle_cursor WHERE cluster_ref = %s",
                (cluster_ref,),
            )
