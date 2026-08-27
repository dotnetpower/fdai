"""Kubernetes lifecycle collector orchestration tests (fake source and store)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_lifecycle_collector import (
    KubernetesLifecycleAppendReceipt,
    KubernetesLifecycleCursorConflictError,
    collect_kubernetes_lifecycle_once,
)
from fdai.delivery.kubernetes_lifecycle_source import KubernetesLifecyclePoll

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)
CLUSTER_REF = "cluster-a"


def _observation(
    *,
    object_uid: str = "pod-uid-a",
    reason: str = "Killing",
    category: str = "killing",
    source_revision: str = "1000",
    evidence_ref: str | None = None,
) -> KubernetesLifecycleObservation:
    return KubernetesLifecycleObservation(
        cluster_ref=CLUSTER_REF,
        namespace="example-namespace",
        object_uid=object_uid,
        owner_uid=None,
        reason=reason,
        category=category,
        event_type="Normal",
        event_time=NOW,
        recorded_time=NOW,
        source_revision=source_revision,
        evidence_ref=evidence_ref or f"kubernetes-lifecycle:{object_uid}-{source_revision}",
    )


@dataclass
class _FakeStore:
    """In-memory store enforcing the same single-writer cursor-conflict contract."""

    cursor: str | None = None
    observations: dict[str, KubernetesLifecycleObservation] = field(default_factory=dict)
    mutation_attempts: int = 0

    async def read_cursor(self, cluster_ref: str) -> str | None:
        assert cluster_ref == CLUSTER_REF
        return self.cursor

    async def append(
        self,
        *,
        cluster_ref: str,
        previous_cursor: str | None,
        next_cursor: str | None,
        observations: tuple[KubernetesLifecycleObservation, ...],
    ) -> KubernetesLifecycleAppendReceipt:
        assert cluster_ref == CLUSTER_REF
        if previous_cursor != self.cursor:
            raise KubernetesLifecycleCursorConflictError("cursor moved concurrently")
        inserted = 0
        duplicate = 0
        for observation in observations:
            if observation.evidence_ref in self.observations:
                duplicate += 1
                continue
            self.observations[observation.evidence_ref] = observation
            inserted += 1
        self.cursor = next_cursor
        return KubernetesLifecycleAppendReceipt(
            cluster_ref=cluster_ref,
            inserted_count=inserted,
            duplicate_count=duplicate,
            cursor=next_cursor,
        )


class _FakeSource:
    def __init__(self, polls: list[KubernetesLifecyclePoll]) -> None:
        self._polls = list(polls)
        self.calls: list[str | None] = []

    async def poll(self, *, cluster_ref: str, cursor: str | None) -> KubernetesLifecyclePoll:
        assert cluster_ref == CLUSTER_REF
        self.calls.append(cursor)
        return self._polls.pop(0)


def _poll(
    *,
    observations: tuple[KubernetesLifecycleObservation, ...] = (),
    next_cursor: str | None,
    complete: bool = True,
    limitation: str | None = None,
) -> KubernetesLifecyclePoll:
    return KubernetesLifecyclePoll(
        cluster_ref=CLUSTER_REF,
        observations=observations,
        next_cursor=next_cursor,
        complete=complete,
        limitation=limitation,
        attempt_ref=f"kubernetes-lifecycle:test-{next_cursor}-{limitation}",
    )


async def test_first_collection_persists_observations_and_advances_the_cursor() -> None:
    store = _FakeStore()
    observation = _observation()
    source = _FakeSource([_poll(observations=(observation,), next_cursor="1000")])

    receipt = await collect_kubernetes_lifecycle_once(
        source=source, store=store, cluster_ref=CLUSTER_REF
    )

    assert receipt.inserted_count == 1
    assert receipt.duplicate_count == 0
    assert receipt.cursor == "1000"
    assert store.cursor == "1000"
    assert observation.evidence_ref in store.observations


async def test_restart_continuity_resumes_from_the_durable_cursor() -> None:
    store = _FakeStore(cursor="1000", observations={_observation().evidence_ref: _observation()})
    next_observation = _observation(object_uid="pod-uid-b", source_revision="1001")
    source = _FakeSource([_poll(observations=(next_observation,), next_cursor="1001")])

    receipt = await collect_kubernetes_lifecycle_once(
        source=source, store=store, cluster_ref=CLUSTER_REF
    )

    assert source.calls == ["1000"]
    assert receipt.inserted_count == 1
    assert store.cursor == "1001"
    assert len(store.observations) == 2


async def test_delete_recreate_keeps_both_uids_distinct_and_never_merges() -> None:
    store = _FakeStore()
    original = _observation(object_uid="pod-uid-a", reason="Killing", category="killing")
    source = _FakeSource([_poll(observations=(original,), next_cursor="1000")])
    await collect_kubernetes_lifecycle_once(source=source, store=store, cluster_ref=CLUSTER_REF)

    recreated = _observation(
        object_uid="pod-uid-a-recreated",
        reason="SuccessfulCreate",
        category="successful_create",
        source_revision="1001",
    )
    source_two = _FakeSource([_poll(observations=(recreated,), next_cursor="1001")])
    await collect_kubernetes_lifecycle_once(source=source_two, store=store, cluster_ref=CLUSTER_REF)

    assert len(store.observations) == 2
    uids = {item.object_uid for item in store.observations.values()}
    assert uids == {"pod-uid-a", "pod-uid-a-recreated"}


async def test_duplicate_delivery_is_idempotent_and_never_double_inserts() -> None:
    store = _FakeStore()
    observation = _observation()
    source = _FakeSource([_poll(observations=(observation,), next_cursor="1000")])
    await collect_kubernetes_lifecycle_once(source=source, store=store, cluster_ref=CLUSTER_REF)

    # Redeliver the exact same observation at the exact same cursor (e.g. an
    # overlapping watch window after a restart before the cursor advanced further).
    duplicate_source = _FakeSource([_poll(observations=(observation,), next_cursor="1000")])
    store.cursor = "1000"
    receipt = await collect_kubernetes_lifecycle_once(
        source=duplicate_source, store=store, cluster_ref=CLUSTER_REF
    )

    assert receipt.inserted_count == 0
    assert receipt.duplicate_count == 1
    assert len(store.observations) == 1


async def test_reordered_duplicate_delivery_does_not_double_insert() -> None:
    store = _FakeStore()
    first = _observation(object_uid="pod-uid-a", source_revision="1000")
    second = _observation(object_uid="pod-uid-b", source_revision="1001")
    source = _FakeSource([_poll(observations=(first, second), next_cursor="1001")])
    await collect_kubernetes_lifecycle_once(source=source, store=store, cluster_ref=CLUSTER_REF)
    assert len(store.observations) == 2

    # Re-deliver the same pair in reverse order at the same durable cursor value.
    store.cursor = "1001"
    reordered_source = _FakeSource([_poll(observations=(second, first), next_cursor="1001")])
    receipt = await collect_kubernetes_lifecycle_once(
        source=reordered_source, store=store, cluster_ref=CLUSTER_REF
    )

    assert receipt.inserted_count == 0
    assert receipt.duplicate_count == 2
    assert len(store.observations) == 2


async def test_cursor_expiry_gap_is_surfaced_explicitly_and_resets_the_cursor() -> None:
    store = _FakeStore(cursor="1000")
    source = _FakeSource(
        [_poll(observations=(), next_cursor=None, complete=False, limitation="cursor_expired")]
    )

    receipt = await collect_kubernetes_lifecycle_once(
        source=source, store=store, cluster_ref=CLUSTER_REF
    )

    assert receipt.complete is False
    assert receipt.limitation == "cursor_expired"
    assert receipt.cursor is None
    assert store.cursor is None


async def test_provider_outage_is_surfaced_explicitly_and_never_mutates_the_store() -> None:
    store = _FakeStore(cursor="1000")
    source = _FakeSource(
        [
            _poll(
                observations=(),
                next_cursor="1000",
                complete=False,
                limitation="source_unavailable",
            )
        ]
    )

    receipt = await collect_kubernetes_lifecycle_once(
        source=source, store=store, cluster_ref=CLUSTER_REF
    )

    assert receipt.complete is False
    assert receipt.limitation == "source_unavailable"
    # The store MUST NOT be touched at all when nothing changed and no observations
    # arrived: append() is not invoked, so the cursor row is left durable and intact.
    assert store.cursor == "1000"
    assert store.observations == {}


async def test_never_mutates_or_deletes_a_previously_persisted_observation() -> None:
    store = _FakeStore()
    original = _observation()
    source = _FakeSource([_poll(observations=(original,), next_cursor="1000")])
    await collect_kubernetes_lifecycle_once(source=source, store=store, cluster_ref=CLUSTER_REF)
    persisted_before = dict(store.observations)

    # A second, unrelated pass MUST only append; it must never alter or remove what a
    # prior pass already durably recorded.
    other = _observation(object_uid="pod-uid-b", source_revision="1001")
    source_two = _FakeSource([_poll(observations=(other,), next_cursor="1001")])
    await collect_kubernetes_lifecycle_once(source=source_two, store=store, cluster_ref=CLUSTER_REF)

    for evidence_ref, observation in persisted_before.items():
        assert store.observations[evidence_ref] == observation


async def test_foreign_cluster_ref_from_the_source_is_rejected() -> None:
    store = _FakeStore()
    mismatched_poll = KubernetesLifecyclePoll(
        cluster_ref="cluster-other",
        observations=(),
        next_cursor="1000",
        complete=True,
        limitation=None,
        attempt_ref="kubernetes-lifecycle:test-mismatch",
    )

    class _MismatchedSource:
        async def poll(self, *, cluster_ref: str, cursor: str | None) -> KubernetesLifecyclePoll:
            return mismatched_poll

    with pytest.raises(ValueError, match="foreign cluster_ref"):
        await collect_kubernetes_lifecycle_once(
            source=_MismatchedSource(), store=store, cluster_ref=CLUSTER_REF
        )
