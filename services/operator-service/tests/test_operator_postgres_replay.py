"""Principal isolation tests for durable Operator operations replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from fdai_operator_service.families.operations.contracts import (
    ProjectionNotFoundError,
    ProjectionQuery,
    ReplayQuery,
)
from fdai_operator_service.family_adapters import PostgresOperationsAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts import OperatorRole


async def test_postgres_operations_selects_role_scoped_exact_declaration(
    monkeypatch: Any,
) -> None:
    operations: list[str] = []

    async def read_projection(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
    ) -> Mapping[str, object]:
        del self
        assert family == "operations"
        operations.append(operation)
        return {
            "purpose": "operations-review",
            "mutation_authority": False,
            "details": {
                "object-types": {
                    "Decision": {
                        "schema_version": "1.0.0",
                        "declaration_name": "Decision",
                        "mutation_authority": False,
                    }
                }
            },
        }

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )
    query = ProjectionQuery(
        operation="ontology.declaration.detail",
        principal_id="principal-a",
        path={"kind": "object-types", "name": "Decision"},
        params={},
        limit=100,
        cursor=None,
        roles=frozenset({OperatorRole.READER, OperatorRole.APPROVER}),
    )

    detail = await adapter.read(query)

    assert detail["declaration_name"] == "Decision"
    assert operations == ["ontology.declaration.detail.approver"]

    with pytest.raises(ProjectionNotFoundError):
        await adapter.read(replace(query, path={"kind": "object-types", "name": "Unknown"}))


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
        assert parameters == {"expected_role": "fdai_operator"}
        captured.append(statement)
        return [{"ready": True}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.probe_readiness() is True
    statement = captured[0]
    assert "current_user = %(expected_role)s" in statement
    assert "has_table_privilege(current_user, 'state_kv', 'SELECT')" in statement
    assert "has_table_privilege(current_user, 'state_kv', 'INSERT')" in statement
    assert "has_table_privilege(current_user, 'audit_log', 'SELECT')" in statement
