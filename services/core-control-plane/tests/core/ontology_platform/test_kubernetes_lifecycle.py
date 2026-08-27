"""Pure Kubernetes lifecycle cursor and identity tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleBatch,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
    advance_lifecycle_cursor,
)

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
CLUSTER = "scope-example/resource-group/example/providers/containerservice/example"


def _cursor(
    *,
    sequence: int = 4,
    resume_token: str | None = None,
) -> KubernetesLifecycleCursor:
    return KubernetesLifecycleCursor(
        cluster_ref=CLUSTER,
        sequence=sequence,
        resume_token=resume_token,
        coverage_started_at=NOW - timedelta(minutes=10),
        coverage_through_at=NOW,
        retention_floor_at=NOW - timedelta(minutes=10),
        limitation=None,
    )


def _observation(*, object_uid: str = "uid-a", source_revision: str = "opaque-9"):
    return KubernetesLifecycleObservation(
        observation_id=f"sha256:{'a' * 64}",
        cluster_ref=CLUSTER,
        event_uid="event-a",
        object_uid=object_uid,
        object_kind="Pod",
        namespace="default",
        owner_uid="owner-a",
        reason="BackOff",
        event_type="Warning",
        lifecycle_kind="backoff",
        action="modified",
        occurred_at=NOW,
        recorded_at=NOW,
        source_revision=source_revision,
        occurrence_count=17,
        evidence_ref=f"kubernetes-lifecycle:{'a' * 64}",
    )


def test_cursor_advances_local_sequence_without_ordering_opaque_token() -> None:
    cursor = _cursor()
    batch = KubernetesLifecycleBatch(
        cluster_ref=CLUSTER,
        expected_sequence=4,
        next_resume_token="opaque-lower-looking-token",
        coverage_started_at=cursor.coverage_started_at,
        coverage_through_at=NOW + timedelta(seconds=20),
        observations=(_observation(),),
        limitation=None,
    )

    advanced = advance_lifecycle_cursor(cursor, batch)

    assert advanced is not None
    assert advanced.sequence == 5
    assert advanced.resume_token == "opaque-lower-looking-token"
    assert advanced.coverage_through_at == NOW + timedelta(seconds=20)


def test_stale_or_reordered_batch_cannot_move_cursor() -> None:
    cursor = _cursor()
    stale_sequence = KubernetesLifecycleBatch(
        cluster_ref=CLUSTER,
        expected_sequence=3,
        next_resume_token="opaque-stale",
        coverage_started_at=cursor.coverage_started_at,
        coverage_through_at=NOW + timedelta(seconds=1),
        observations=(),
        limitation=None,
    )
    stale_time = KubernetesLifecycleBatch(
        cluster_ref=CLUSTER,
        expected_sequence=4,
        next_resume_token="opaque-stale",
        coverage_started_at=cursor.coverage_started_at,
        coverage_through_at=NOW - timedelta(seconds=1),
        observations=(),
        limitation=None,
    )

    assert advance_lifecycle_cursor(cursor, stale_sequence) is None
    assert advance_lifecycle_cursor(cursor, stale_time) is None


def test_delete_recreate_uids_remain_distinct() -> None:
    deleted = _observation(object_uid="old-uid")
    recreated = _observation(object_uid="new-uid")

    assert deleted.object_uid != recreated.object_uid
    assert deleted.owner_uid == recreated.owner_uid
