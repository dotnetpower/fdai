"""Bulk recorded-state paging stays on one authorized immutable Resource generation."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryInstanceResource,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.families.operations.instance_states import (
    STATE_DIRECTORY_EXCLUDED_TYPES,
    InventoryGenerationChangedError,
    InventoryOntologyContext,
    InventoryStatePage,
    OntologyGenerationChangedError,
    _encode,
    _validate_page,
    project_inventory_states,
)
from fdai_operator_service.family_adapters import PostgresOperationsAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts import OperatorRole

NOW = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
ONTOLOGY: Mapping[str, object] = {
    "ontology_release_digest": f"sha256:{'a' * 64}",
    "link_types": ["contains"],
}
ONTOLOGY_CONTEXT = InventoryOntologyContext(
    generation="generation-1",
    ontology_release_digest=f"sha256:{'a' * 64}",
    manifest_digest=f"sha256:{'c' * 64}",
)
QUERY = ProjectionQuery(
    operation="ontology.instance.states",
    principal_id="example-reader",
    roles=frozenset({OperatorRole.READER}),
    path={},
    params={},
    limit=2,
    cursor=None,
)


class _Reader:
    def __init__(self) -> None:
        self.context: InventoryImpactContext | None = InventoryImpactContext("generation-1", NOW)
        self.next_context: InventoryImpactContext | None = self.context
        self.ontology_context: InventoryOntologyContext | None = ONTOLOGY_CONTEXT
        self.next_ontology_context: InventoryOntologyContext | None = self.ontology_context
        self.calls: list[tuple[str, str | None, int, int]] = []
        self.resources = tuple(
            InventoryInstanceResource(
                resource_id=f"example-{index}",
                resource_type="compute.container-app",
                properties={"name": f"example-{index}", "properties": {"runningStatus": "Running"}},
                last_seen=NOW,
            )
            for index in range(3)
        )

    async def read_inventory_impact_context(self) -> InventoryImpactContext | None:
        return self.context

    async def read_inventory_ontology_context(self) -> InventoryOntologyContext | None:
        return self.ontology_context

    async def read_inventory_state_page(
        self, *, snapshot_id: str, search: str | None, offset: int, limit: int
    ) -> InventoryStatePage:
        self.calls.append((snapshot_id, search, offset, limit))
        self.context = self.next_context
        self.ontology_context = self.next_ontology_context
        resources = tuple(
            resource
            for resource in self.resources
            if resource.resource_type not in STATE_DIRECTORY_EXCLUDED_TYPES
            and (
                search is None
                or search.casefold()
                in f"{resource.resource_id} {resource.properties.get('name')} "
                f"{resource.resource_type}".casefold()
            )
        )
        return InventoryStatePage(resources[offset : offset + limit], len(resources))


async def _read(reader: _Reader, query: ProjectionQuery = QUERY) -> dict[str, object]:
    return await project_inventory_states(
        query=query, reader=reader, ontology_projection=ONTOLOGY, now=lambda: NOW
    )


async def _cursor(reader: _Reader) -> str:
    first = await _read(reader)
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)
    return cursor


def _decode(cursor: str) -> dict[str, object]:
    value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert isinstance(value, dict)
    return value


async def test_page_contract_and_last_page_completeness_with_one_read_per_page() -> None:
    reader = _Reader()
    first = await _read(reader)
    assert set(first) == {
        "schema_version",
        "ontology_release_digest",
        "ontology_generation",
        "ontology_manifest_digest",
        "source_kind",
        "source_generation",
        "source_cutoff",
        "resources",
        "total_count",
        "next_cursor",
        "complete",
        "execution_authority",
        "mutation_authority",
    }
    assert first["schema_version"] == "1.0.0"
    assert first["source_generation"] == "generation-1"
    assert first["ontology_generation"] == "generation-1"
    assert first["ontology_manifest_digest"] == f"sha256:{'c' * 64}"
    assert first["source_kind"] == "inventory_snapshot_resource"
    assert first["source_cutoff"] == NOW.isoformat()
    assert first["total_count"] == 3
    assert first["complete"] is False
    assert first["execution_authority"] is False
    assert first["mutation_authority"] is False
    assert reader.calls == [("generation-1", None, 0, 2)]
    assert first["resources"][0]["states"]["operational"]["freshness"] == "fresh"
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)
    assert len(cursor) <= 1024
    last = await _read(reader, replace(QUERY, cursor=cursor))
    assert last["total_count"] == 3
    assert last["complete"] is True
    assert last["next_cursor"] is None
    assert reader.calls[-1] == ("generation-1", None, 2, 2)
    rows = last["resources"]
    assert isinstance(rows, list)
    assert [row["id"] for row in rows] == ["example-2"]
    assert rows[0]["selected"] is False


async def test_29_resources_are_projected_with_one_bulk_reader_call() -> None:
    reader = _Reader()
    reader.resources = tuple(
        replace(
            reader.resources[0],
            resource_id=f"example-{index:02d}",
            properties={
                "properties": (
                    {"runningStatus": "Running"}
                    if index < 28
                    else {"powerState": {"code": "Running"}}
                )
            },
        )
        for index in range(29)
    )
    page = await _read(reader, replace(QUERY, limit=500))
    assert page["total_count"] == 29
    assert page["complete"] is True
    assert len(reader.calls) == 1
    rows = page["resources"]
    assert isinstance(rows, list)
    assert all(row["states"]["operational"]["value"] == "Running" for row in rows)


@pytest.mark.parametrize(
    "query",
    [
        replace(QUERY, principal_id="another-reader"),
        replace(QUERY, roles=frozenset({OperatorRole.OWNER})),
        replace(QUERY, roles=frozenset({OperatorRole.READER, OperatorRole.CONTRIBUTOR})),
        replace(QUERY, purpose="another-purpose"),
        replace(QUERY, params={"search": ("another",)}),
        replace(QUERY, limit=3),
    ],
)
async def test_cursor_rejects_principal_roles_purpose_search_and_limit_mismatch(
    query: ProjectionQuery,
) -> None:
    reader = _Reader()
    cursor = await _cursor(reader)
    with pytest.raises(ValueError, match="current query or principal"):
        await _read(reader, replace(query, cursor=cursor))
    assert len(reader.calls) == 1


async def test_release_change_rejects_cursor_before_source_page_read() -> None:
    reader = _Reader()
    cursor = await _cursor(reader)
    with pytest.raises(OntologyGenerationChangedError):
        await project_inventory_states(
            query=replace(QUERY, cursor=cursor),
            reader=reader,
            ontology_projection={**ONTOLOGY, "ontology_release_digest": f"sha256:{'b' * 64}"},
        )
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "active",
    [
        InventoryImpactContext("generation-2", NOW),
        InventoryImpactContext("generation-1", datetime(2026, 9, 6, tzinfo=UTC)),
    ],
)
async def test_cursor_rejects_generation_or_cutoff_change(active: InventoryImpactContext) -> None:
    reader = _Reader()
    cursor = await _cursor(reader)
    reader.context = active
    if active.snapshot_id != ONTOLOGY_CONTEXT.generation:
        reader.ontology_context = replace(ONTOLOGY_CONTEXT, generation=active.snapshot_id)
    with pytest.raises(InventoryGenerationChangedError):
        await _read(reader, replace(QUERY, cursor=cursor))
    assert len(reader.calls) == 1


@pytest.mark.parametrize("active", [None, InventoryImpactContext("generation-2", NOW)])
async def test_active_generation_is_rechecked_after_each_page(
    active: InventoryImpactContext | None,
) -> None:
    reader = _Reader()
    reader.next_context = active
    with pytest.raises(InventoryGenerationChangedError):
        await _read(reader)
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "ontology_context",
    [
        None,
        replace(ONTOLOGY_CONTEXT, generation="generation-2"),
        replace(ONTOLOGY_CONTEXT, ontology_release_digest=f"sha256:{'b' * 64}"),
    ],
)
async def test_inventory_and_ontology_generation_must_match_before_read(
    ontology_context: InventoryOntologyContext | None,
) -> None:
    reader = _Reader()
    reader.ontology_context = ontology_context
    with pytest.raises(OntologyGenerationChangedError):
        await _read(reader)
    assert reader.calls == []


async def test_malformed_ontology_manifest_identity_fails_before_source_read() -> None:
    reader = _Reader()
    reader.ontology_context = replace(ONTOLOGY_CONTEXT, manifest_digest="invalid")
    with pytest.raises(ProjectionUnavailableError, match="manifest identity"):
        await _read(reader)
    assert reader.calls == []


async def test_cursor_rejects_replaced_ontology_manifest_before_source_read() -> None:
    reader = _Reader()
    cursor = await _cursor(reader)
    reader.ontology_context = replace(
        ONTOLOGY_CONTEXT,
        manifest_digest=f"sha256:{'d' * 64}",
    )
    with pytest.raises(InventoryGenerationChangedError):
        await _read(reader, replace(QUERY, cursor=cursor))
    assert len(reader.calls) == 1


async def test_ontology_manifest_is_rechecked_after_each_page() -> None:
    reader = _Reader()
    reader.next_ontology_context = replace(
        ONTOLOGY_CONTEXT,
        manifest_digest=f"sha256:{'d' * 64}",
    )
    with pytest.raises(InventoryGenerationChangedError):
        await _read(reader)
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "payload_update",
    [
        {"schema_version": "2.0.0"},
        {"offset": True},
        {"offset": 0},
        {"offset": -1},
        {"offset": 1_000_000_001},
        {"offset": "2"},
        {"scope": "unbounded"},
        {"generation": []},
    ],
)
async def test_cursor_schema_cannot_supply_authority_or_unbounded_offsets(
    payload_update: dict[str, object],
) -> None:
    reader = _Reader()
    cursor = _encode({**_decode(await _cursor(reader)), **payload_update})
    with pytest.raises(ValueError, match="cursor"):
        await _read(reader, replace(QUERY, cursor=cursor))
    assert len(reader.calls) == 1


@pytest.mark.parametrize("cursor", ["", "!", "a", "a" * 1025, "e30", "W10", "bnVsbA"])
async def test_malformed_cursor_fails_without_a_source_page_read(cursor: str) -> None:
    reader = _Reader()
    with pytest.raises(ValueError, match="cursor"):
        await _read(reader, replace(QUERY, cursor=cursor))
    assert not reader.calls


@pytest.mark.parametrize(
    "params",
    [
        {"scope": ("another-scope",)},
        {"search": ("a", "b")},
        {"limit": ("2", "2")},
        {"cursor": ("a", "b")},
        {"search": ("x" * 257,)},
    ],
)
async def test_query_shape_is_closed_and_bounded(params: dict[str, tuple[str, ...]]) -> None:
    reader = _Reader()
    with pytest.raises(ValueError):
        await _read(reader, replace(QUERY, params=params))
    assert not reader.calls


async def test_empty_and_search_pages_report_exact_total_and_explicit_cursor() -> None:
    reader = _Reader()
    page = await _read(reader, replace(QUERY, params={"search": ("example-2",)}))
    assert page["total_count"] == 1
    assert page["complete"] is True
    assert page["next_cursor"] is None
    assert reader.calls == [("generation-1", "example-2", 0, 2)]
    page = await _read(reader, replace(QUERY, params={"search": ("not-present",)}))
    assert page["total_count"] == 0
    assert page["resources"] == []
    assert page["complete"] is True
    assert page["next_cursor"] is None


async def test_role_assignment_and_scope_containers_are_omitted() -> None:
    reader = _Reader()
    reader.resources += tuple(
        replace(reader.resources[0], resource_id=f"excluded-{index}", resource_type=resource_type)
        for index, resource_type in enumerate(STATE_DIRECTORY_EXCLUDED_TYPES)
    )
    page = await _read(reader, replace(QUERY, limit=500))
    assert page["total_count"] == 3
    assert "excluded-" not in repr(page)


async def test_missing_active_source_is_not_a_fabricated_empty_page() -> None:
    reader = _Reader()
    reader.context = None
    with pytest.raises(ProjectionUnavailableError):
        await _read(reader)
    assert not reader.calls


async def test_disappeared_active_source_invalidates_continuation() -> None:
    reader = _Reader()
    cursor = await _cursor(reader)
    reader.context = None
    with pytest.raises(InventoryGenerationChangedError):
        await _read(reader, replace(QUERY, cursor=cursor))
    assert len(reader.calls) == 1


@pytest.mark.parametrize("limit", [0, 501, True])
async def test_page_limit_is_bounded_before_source_read(limit: int) -> None:
    reader = _Reader()
    with pytest.raises(ValueError, match="limit"):
        await _read(reader, replace(QUERY, limit=limit))
    assert not reader.calls


def test_inconsistent_source_page_is_not_claimed_complete() -> None:
    resource = _Reader().resources[0]
    for page in (
        InventoryStatePage((), 1),
        InventoryStatePage((resource, resource), 2),
        InventoryStatePage((resource,), -1),
        InventoryStatePage((replace(resource, resource_type="authorization.role-assignment"),), 1),
    ):
        with pytest.raises(ProjectionUnavailableError, match="malformed"):
            _validate_page(page, offset=0, limit=2)


async def test_postgres_page_count_and_rows_use_one_bounded_parameterized_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore, statement: str, parameters: Mapping[str, object]
    ) -> list[dict[str, object]]:
        del self
        calls.append((statement, parameters))
        return [
            {
                "resource_id": "example-1",
                "resource_type": "compute.container-app",
                "props": {"properties": {"runningStatus": "Running"}},
                "last_seen": NOW,
                "total_count": 29,
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    page = await store.read_inventory_state_page(
        snapshot_id="generation-1", search="example_%", offset=10, limit=500
    )
    assert page.total_count == 29
    assert len(page.resources) == 1
    assert len(calls) == 1
    statement, params = calls[0]
    assert "inventory_snapshot_resource" in statement
    assert "inventory_realtime" not in statement
    assert "COUNT(*)" in statement
    assert 'ORDER BY resource_id COLLATE "C" LIMIT %(limit)s OFFSET %(offset)s' in statement
    assert "LEFT JOIN LATERAL" in statement
    assert params == {
        "snapshot_id": "generation-1",
        "pattern": "%example\\_\\%%",
        "excluded_types": list(STATE_DIRECTORY_EXCLUDED_TYPES),
        "offset": 10,
        "limit": 500,
    }
    assert "example_%" not in statement


async def test_postgres_reads_the_committed_inventory_ontology_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore, statement: str, parameters: Mapping[str, object]
    ) -> list[dict[str, object]]:
        del self
        calls.append((statement, parameters))
        return [
            {
                "value": {
                    "schema_version": "1.3.0",
                    "generation": "generation-1",
                    "ontology_release_digest": f"sha256:{'a' * 64}",
                    "manifest_digest": f"sha256:{'c' * 64}",
                    "complete": True,
                }
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    assert await store.read_inventory_ontology_context() == ONTOLOGY_CONTEXT
    assert calls == [
        (
            "SELECT value FROM state_kv WHERE key = %(key)s",
            {"key": "inventory-ontology:manifest"},
        )
    ]


async def test_postgres_empty_page_retains_zero_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore, statement: str, parameters: Mapping[str, object]
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            {
                "resource_id": None,
                "resource_type": None,
                "props": None,
                "last_seen": None,
                "total_count": 0,
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    page = await store.read_inventory_state_page(
        snapshot_id="generation-1", search=None, offset=0, limit=500
    )
    assert page == InventoryStatePage((), 0)


async def test_postgres_operations_adapter_dispatches_to_shared_bulk_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader()
    projection_calls: list[str] = []

    async def projection(
        self: PostgresFamilyStore, *, family: str, operation: str, **kwargs: object
    ) -> Mapping[str, object]:
        del self, kwargs
        assert family == "operations"
        projection_calls.append(operation)
        return ONTOLOGY

    async def context(self: PostgresFamilyStore) -> InventoryImpactContext | None:
        del self
        return await reader.read_inventory_impact_context()

    async def ontology_context(
        self: PostgresFamilyStore,
    ) -> InventoryOntologyContext | None:
        del self
        return await reader.read_inventory_ontology_context()

    async def page(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        search: str | None,
        offset: int,
        limit: int,
    ) -> InventoryStatePage:
        del self
        return await reader.read_inventory_state_page(
            snapshot_id=snapshot_id, search=search, offset=offset, limit=limit
        )

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", projection)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_impact_context", context)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_ontology_context", ontology_context)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_state_page", page)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    result = await PostgresOperationsAdapters(store).read(QUERY)
    assert result["total_count"] == 3
    assert projection_calls == ["ontology.graph"]
    assert len(reader.calls) == 1
