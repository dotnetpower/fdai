"""Principal isolation tests for durable Operator operations replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactLinkPage,
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


async def test_postgres_operations_builds_dynamic_impact_instead_of_reading_static_key(
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
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "mutation_authority": False,
            "link_types": ["contains"],
        }

    async def read_context(self: PostgresFamilyStore) -> InventoryImpactContext:
        del self
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    async def resource_exists(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        resource_id: str,
    ) -> bool:
        del self
        return snapshot_id == "generation-1" and resource_id == "root"

    async def read_links(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        source_ids: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactLinkPage:
        del self, snapshot_id, link_types, limit
        edges = (
            (InventoryImpactEdge("root", "child", "contains"),) if source_ids == ("root",) else ()
        )
        return InventoryImpactLinkPage(edges=edges, truncated=False)

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_impact_context", read_context)
    monkeypatch.setattr(PostgresFamilyStore, "inventory_resource_exists", resource_exists)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_outgoing_links", read_links)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    result = await adapter.read(
        ProjectionQuery(
            operation="blast_radius.simulate",
            principal_id="reader",
            path={},
            params={"target": ("root",), "depth": ("1",), "link": ("contains",)},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        )
    )

    assert operations == ["ontology.graph"]
    assert result["affected_count"] == 1
    assert result["mutation_authority"] is False


async def test_postgres_inventory_impact_reads_only_active_snapshot_identity_and_links(
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
        if "JOIN inventory_snapshot AS snapshot" in statement:
            return [{"id": "generation-1", "completed_at": datetime(2026, 8, 19, tzinfo=UTC)}]
        if "SELECT 1 AS present" in statement:
            return [{"present": 1}]
        return [
            {"from_id": "root", "link_type": "contains", "to_id": "child"},
            {"from_id": "root", "link_type": "contains", "to_id": "extra"},
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    context = await store.read_inventory_impact_context()
    exists = await store.inventory_resource_exists(
        snapshot_id="generation-1",
        resource_id="root",
    )
    page = await store.read_inventory_outgoing_links(
        snapshot_id="generation-1",
        source_ids=("root",),
        link_types=("contains",),
        limit=1,
    )

    assert context == InventoryImpactContext(
        snapshot_id="generation-1",
        observed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    assert exists is True
    assert [(edge.source, edge.link_type, edge.target) for edge in page.edges] == [
        ("root", "contains", "child")
    ]
    assert page.truncated is True
    assert captured[-1][1] == {
        "snapshot_id": "generation-1",
        "source_ids": ["root"],
        "link_types": ["contains"],
        "probe": 2,
    }


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
    assert "has_table_privilege(current_user, 'inventory_active', 'SELECT')" in statement
