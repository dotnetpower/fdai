"""Principal isolation tests for durable Operator operations replay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_operator_service.families.operations.contracts import ReplayQuery
from fdai_operator_service.family_adapters import PostgresOperationsAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)


async def test_postgres_operations_replay_scopes_sql_to_authenticated_principal(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        return [
            {
                "seq": 8,
                "action_kind": "provision.progress",
                "entry": {"principal_id": "principal-a", "status": "running"},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    batch = await adapter.replay(ReplayQuery("provision", "principal-a", 7, 100))

    assert batch.events[0].sequence == 8
    statement, parameters = captured[0]
    assert "entry ->> 'principal_id' = %(principal_id)s" in statement
    assert parameters == {
        "after_sequence": 7,
        "stream": "provision",
        "principal_id": "principal-a",
        "limit": 100,
    }


async def test_postgres_replay_rejects_empty_principal_before_query(monkeypatch: Any) -> None:
    called = False

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    try:
        await store.replay(stream="provision", principal_id="", after_sequence=None, limit=100)
    except ValueError as exc:
        assert "principal_id" in str(exc)
    else:
        raise AssertionError("empty replay principal did not fail closed")
    assert called is False


async def test_postgres_readiness_references_required_projection_schema(monkeypatch: Any) -> None:
    captured: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        assert parameters == {}
        captured.append(statement)
        return [{"ready": 1}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.probe_readiness() is True
    statement = captured[0]
    assert "key, value, updated_at" in statement
    assert "FROM state_kv" in statement
    assert "seq, event_id, correlation_id, actor, action_kind, mode" in statement
    assert "entry, previous_hash, entry_hash, created_at" in statement
    assert "FROM audit_log" in statement
