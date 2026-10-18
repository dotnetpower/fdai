from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fdai.core.architecture_review import ArchitectureReviewObservation
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.state_store_architecture_review import (
    StateStoreArchitectureReviewStateStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _observation(*, change_digest: str = "digest-1") -> ArchitectureReviewObservation:
    return ArchitectureReviewObservation.hold(
        change_id="change-1",
        idempotency_key="change-key-1",
        correlation_id="correlation-1",
        target_ref="resource-1",
        change_digest=change_digest,
        reason="evidence_unavailable",
    )


async def test_observation_identity_and_projection_status_survive_restart() -> None:
    state_store = InMemoryStateStore()
    first = StateStoreArchitectureReviewStateStore(state_store)

    assert await first.put_if_absent("change-key-1", _observation()) is None
    assert await first.get_projection_status("change-key-1") == "pending"
    await first.mark_projection("change-key-1", "projected")

    restarted = StateStoreArchitectureReviewStateStore(state_store)
    restored = await restarted.get("change-key-1")

    assert restored is not None
    assert restored.change_digest == "digest-1"
    assert restored.recommendation == "hold"
    assert restored.reasons == ("evidence_unavailable",)
    assert await restarted.get_projection_status("change-key-1") == "projected"


async def test_incomplete_persisted_projection_downgrades_to_explicit_hold() -> None:
    adapter = StateStoreArchitectureReviewStateStore(InMemoryStateStore())
    await adapter.put_if_absent("change-key-1", _observation())

    restored = await adapter.get("change-key-1")

    assert restored is not None
    assert restored.recommendation == "hold"
    assert restored.reasons == (
        "evidence_unavailable",
        "persisted_projection_incomplete",
    )


async def test_first_observation_identity_wins_cross_replica_race() -> None:
    state_store = InMemoryStateStore()
    first = StateStoreArchitectureReviewStateStore(state_store)
    second = StateStoreArchitectureReviewStateStore(state_store)
    assert await first.put_if_absent("change-key-1", _observation()) is None

    existing = await second.put_if_absent(
        "change-key-1",
        _observation(change_digest="conflicting-digest"),
    )

    assert existing is not None
    assert existing.change_digest == "digest-1"


async def test_postgres_restart_preserves_projection_fence() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL")
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    config = PostgresStateStoreConfig(dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1))
    key = f"change-key-{uuid4().hex}"
    first = StateStoreArchitectureReviewStateStore(PostgresStateStore(config=config))

    assert await first.put_if_absent(key, _observation()) is None
    await first.mark_projection(key, "projected")

    restarted = StateStoreArchitectureReviewStateStore(PostgresStateStore(config=config))
    restored = await restarted.get(key)
    assert restored is not None
    assert restored.change_digest == "digest-1"
    assert await restarted.get_projection_status(key) == "projected"
