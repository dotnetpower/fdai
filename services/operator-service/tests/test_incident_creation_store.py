"""Focused persistence checks for semantic Incident confirmations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)

NOW = datetime(2026, 9, 16, 2, 5, tzinfo=UTC)


async def test_store_resolves_one_principal_owned_draft_by_browser_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    parameters: list[object] = []
    source = {"status": "action_draft", "idempotency_key": "draft-one"}

    async def fetch_all(
        _self: PostgresFamilyStore,
        statement: str,
        values: object,
    ) -> list[dict[str, object]]:
        statements.append(statement)
        parameters.append(values)
        return [{"data": source}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    resolved = await store.read_semantic_action_draft_by_key(
        principal_id="operator-one",
        idempotency_key="draft-one",
    )

    assert resolved == source
    assert "request.value ->> 'principal_id' = %(principal_id)s" in statements[0]
    assert "result.value #>> '{data,idempotency_key}' = %(idempotency_key)s" in statements[0]
    assert parameters == [{"principal_id": "operator-one", "idempotency_key": "draft-one"}]


async def test_store_reads_an_existing_confirmation_without_recreating_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "proposal_id": "operator-proposal-one",
        "accepted_at": NOW.isoformat(),
        "dispatch_status": "pending",
    }

    async def fetch_all(
        _self: PostgresFamilyStore,
        statement: str,
        values: object,
    ) -> list[dict[str, object]]:
        assert "SELECT value FROM state_kv" in statement
        digest = hashlib.sha256(b"draft-one").hexdigest()
        assert values == {"key": f"operator-proposal:conversation:{digest}"}
        return [{"value": record}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    stored = await store.read_proposal(
        family="conversation",
        idempotency_key="draft-one",
    )

    assert stored is not None
    assert stored.duplicate is True
    assert stored.record == record
