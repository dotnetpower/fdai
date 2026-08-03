"""StateStore-backed ActionType precondition evidence tests."""

from __future__ import annotations

from fdai.delivery.persistence.state_store_preconditions import (
    StateStoreOpenActionEvidenceProvider,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def _write_run(
    store: InMemoryStateStore,
    *,
    correlation_id: str,
    target_ref: str,
    idempotency_key: str,
) -> None:
    await store.write_state(
        f"thor:run|{correlation_id}",
        {
            "correlation_id": correlation_id,
            "resource_id": target_ref,
            "idempotency_key": idempotency_key,
        },
    )


async def test_open_action_evidence_excludes_same_action_retry() -> None:
    store = InMemoryStateStore()
    await _write_run(
        store,
        correlation_id="run-1",
        target_ref="resource-1",
        idempotency_key="action-1",
    )
    await store.write_state("thor:active-index", {"ids": ["run-1"]})

    conflict = await StateStoreOpenActionEvidenceProvider(store).has_conflict(
        target_ref="resource-1",
        excluding_idempotency_key="action-1",
    )

    assert conflict is False


async def test_open_action_evidence_detects_other_action_on_target() -> None:
    store = InMemoryStateStore()
    await _write_run(
        store,
        correlation_id="run-1",
        target_ref="resource-1",
        idempotency_key="other-action",
    )
    await store.write_state("thor:active-index", {"ids": ["run-1"]})

    conflict = await StateStoreOpenActionEvidenceProvider(store).has_conflict(
        target_ref="resource-1",
        excluding_idempotency_key="action-1",
    )

    assert conflict is True


async def test_open_action_evidence_fails_closed_for_missing_run() -> None:
    store = InMemoryStateStore()
    await store.write_state("thor:active-index", {"ids": ["missing"]})

    conflict = await StateStoreOpenActionEvidenceProvider(store).has_conflict(
        target_ref="resource-1",
        excluding_idempotency_key="action-1",
    )

    assert conflict is True
