"""Principal-scoped Workflow definition catalog and its route-level availability contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest
from fdai_operator_service.families.workflow import (
    WorkflowOperation,
    WorkflowReadRequest,
    build_workflow_family_routes,
)
from fdai_operator_service.family_adapters import (
    PostgresWorkflowAdapters,
    UnavailableWorkflowAdapters,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreUnavailable
from fdai_operator_service.postgres_workflow_definitions import (
    MAX_PRINCIPAL_BINDINGS,
    MAX_VISIBLE_DEFINITIONS,
    PRINCIPAL_BINDINGS_SQL,
    VISIBLE_DEFINITIONS_SQL,
    WORKFLOW_DEFINITION_CATALOG_SOURCE,
    PostgresWorkflowDefinitionCatalog,
    project_workflow_definition_catalog,
)
from fdai_operator_service.python_task_capability import PYTHON_TASK_CAPABILITY_SOURCE
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient

PRINCIPAL = "operator-a"
OTHER = "operator-b"


def _definition(definition_id: str, **overrides: object) -> dict[str, object]:
    name = str(overrides.pop("workflow_name", f"workflow-{definition_id}"))
    row: dict[str, object] = {
        "definition_id": definition_id,
        "workflow_name": name,
        "workflow_version": "1.0.0",
        "schema_version": "1.0.0",
        "definition_hash": f"sha256:{definition_id}",
        "action_catalog_digest": "sha256:catalog",
        "resolved_action_versions": {"compute.restart": "1.0.0"},
        "workflow_document": {
            "name": name,
            "version": "1.0.0",
            "trigger": {"kind": "signal", "signal_type": "object.event"},
            "steps": [{"id": "restart", "action_type_ref": "compute.restart"}],
        },
        "origin": "upstream",
        "visibility": "global",
        "lifecycle": "shadow",
        "owner_ref": None,
        "derived_from": None,
    }
    row.update(overrides)
    return row


def _binding(binding_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "binding_id": binding_id,
        "definition_id": "upstream-1",
        "trigger": "deck_open",
        "enabled": False,
        "scope_ref": None,
        "cron_expression": None,
        "timezone": None,
        "signal_type": None,
        "parameters": {"region": "primary", "limit": 3},
        "revision": 1,
    }
    row.update(overrides)
    return row


class DefinitionStore:
    """Return principal-scoped rows the way the SQL predicates would, and record each read."""

    def __init__(
        self,
        definitions: list[dict[str, object]] | None = None,
        bindings: list[dict[str, object]] | None = None,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.definitions = definitions or []
        self.bindings = bindings or []
        self.failure = failure
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, dict(parameters)))
        if self.failure is not None:
            raise self.failure
        if statement == VISIBLE_DEFINITIONS_SQL:
            return list(self.definitions)
        if statement == PRINCIPAL_BINDINGS_SQL:
            return list(self.bindings)
        raise AssertionError(f"unexpected statement: {statement}")

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        raise AssertionError(f"workflow definitions must not read a projection: {operation}")


class Authorizer:
    def __init__(self, role: OperatorRole = OperatorRole.READER) -> None:
        self.principal = OperatorPrincipal(PRINCIPAL, frozenset({role}))

    async def __call__(self, request, required_roles):  # type: ignore[no-untyped-def]
        del request
        if self.principal.roles.isdisjoint(required_roles):
            raise HTTPException(status_code=403, detail="principal lacks required role")
        return self.principal


class NoProposals:
    async def submit(self, proposal):  # type: ignore[no-untyped-def]
        raise AssertionError(f"read routes must not submit proposals: {proposal}")


def _client(read_store: object) -> TestClient:
    routes = build_workflow_family_routes(
        authorize=Authorizer(),
        read_store=cast(Any, read_store),
        proposal_writer=NoProposals(),
    )
    return TestClient(Starlette(routes=list(routes)))


def _request(operation: WorkflowOperation, principal_id: str = PRINCIPAL) -> WorkflowReadRequest:
    return WorkflowReadRequest(
        operation=operation,
        principal_id=principal_id,
        query={},
        path_parameters={},
    )


def _ids(payload: Mapping[str, Any], group: str) -> list[str]:
    return [entry["definition_id"] for entry in payload["groups"][group]]


def _grouping_rows() -> list[dict[str, object]]:
    return [
        _definition("upstream-1"),
        _definition("tenant-unowned", origin="tenant"),
        _definition("tenant-team", origin="tenant", owner_ref="team-operations"),
        _definition("user-private", origin="user", visibility="private", owner_ref=PRINCIPAL),
        _definition("tenant-owned", origin="tenant", owner_ref=PRINCIPAL),
    ]


async def test_catalog_groups_built_in_shared_and_mine_for_the_requesting_principal() -> None:
    store = DefinitionStore(_grouping_rows(), [_binding("binding-1")])

    result = await PostgresWorkflowAdapters(cast(Any, store)).read(
        _request(WorkflowOperation.WORKFLOW_DEFINITION_LIST)
    )

    payload = cast(dict[str, Any], result.payload)
    assert _ids(payload, "built_in") == ["upstream-1"]
    assert _ids(payload, "shared") == ["tenant-unowned", "tenant-team"]
    assert _ids(payload, "mine") == ["user-private", "tenant-owned"]
    assert payload["counts"] == {"built_in": 1, "shared": 2, "mine": 2}
    owners = {
        entry["definition_id"]: entry["owner_ref"]
        for group in ("built_in", "shared", "mine")
        for entry in payload["groups"][group]
    }
    assert owners == {
        "upstream-1": None,
        "tenant-unowned": None,
        "tenant-team": None,
        "user-private": PRINCIPAL,
        "tenant-owned": PRINCIPAL,
    }
    assert payload["bindings"] == [
        {
            "binding_id": "binding-1",
            "definition_id": "upstream-1",
            "trigger": "deck_open",
            "enabled": False,
            "cron_expression": None,
            "timezone": None,
            "signal_type": None,
            "scope_ref": None,
            "parameters": {"region": "primary", "limit": 3},
            "revision": 1,
        }
    ]
    assert payload["groups"]["mine"][0]["workflow_document"]["steps"][0]["id"] == "restart"
    assert result.provenance.source_ref == WORKFLOW_DEFINITION_CATALOG_SOURCE
    assert len(result.provenance.revision) == 64


async def test_catalog_binds_every_statement_to_the_authenticated_principal() -> None:
    store = DefinitionStore()

    await PostgresWorkflowDefinitionCatalog(store._fetch_all).read(PRINCIPAL)

    assert store.calls == [
        (
            VISIBLE_DEFINITIONS_SQL,
            {"principal_id": PRINCIPAL, "limit": MAX_VISIBLE_DEFINITIONS + 1},
        ),
        (
            PRINCIPAL_BINDINGS_SQL,
            {"principal_id": PRINCIPAL, "limit": MAX_PRINCIPAL_BINDINGS + 1},
        ),
    ]
    assert (
        "WHERE visibility = 'global' OR (visibility = 'private' AND owner_ref = %(principal_id)s)"
        in VISIBLE_DEFINITIONS_SQL
    )
    assert "team" not in VISIBLE_DEFINITIONS_SQL
    assert "WHERE principal_id = %(principal_id)s" in PRINCIPAL_BINDINGS_SQL


@pytest.mark.parametrize(
    "leaked",
    [
        _definition("other-private", origin="user", visibility="private", owner_ref=OTHER),
        _definition("team-only", origin="tenant", visibility="team", owner_ref="team-operations"),
        _definition("team-own", origin="tenant", visibility="team", owner_ref=PRINCIPAL),
    ],
)
async def test_catalog_fails_closed_on_a_definition_outside_the_principal_scope(
    leaked: dict[str, object],
) -> None:
    store = DefinitionStore([_definition("upstream-1"), leaked])

    with pytest.raises(HTTPException) as caught:
        await PostgresWorkflowAdapters(cast(Any, store)).read(
            _request(WorkflowOperation.WORKFLOW_DEFINITION_LIST)
        )

    assert caught.value.status_code == 503
    assert "outside the principal scope" in str(caught.value.detail)


async def test_catalog_fails_closed_on_another_principals_binding() -> None:
    store = DefinitionStore(
        [_definition("upstream-1")],
        [_binding("binding-1"), _binding("binding-2", principal_id=OTHER)],
    )

    with pytest.raises(PostgresFamilyStoreUnavailable, match="outside the principal scope"):
        await PostgresWorkflowDefinitionCatalog(store._fetch_all).read(PRINCIPAL)


def test_the_same_store_rows_never_cross_principals() -> None:
    rows = [
        _definition("upstream-1"),
        _definition("a-private", origin="user", visibility="private", owner_ref=PRINCIPAL),
    ]

    mine = project_workflow_definition_catalog(rows, [], principal_id=PRINCIPAL)

    assert _ids(mine, "mine") == ["a-private"]
    with pytest.raises(PostgresFamilyStoreUnavailable, match="outside the principal scope"):
        project_workflow_definition_catalog(rows, [], principal_id=OTHER)


async def test_empty_store_is_an_authoritative_empty_catalog() -> None:
    result = await PostgresWorkflowAdapters(cast(Any, DefinitionStore())).read(
        _request(WorkflowOperation.WORKFLOW_DEFINITION_LIST)
    )

    assert result.payload == {
        "groups": {"built_in": [], "shared": [], "mine": []},
        "bindings": [],
        "counts": {"built_in": 0, "shared": 0, "mine": 0},
    }
    assert result.provenance.source_ref == WORKFLOW_DEFINITION_CATALOG_SOURCE


async def test_revision_tracks_catalog_content() -> None:
    first = await PostgresWorkflowDefinitionCatalog(
        DefinitionStore([_definition("upstream-1")])._fetch_all
    ).read(PRINCIPAL)
    repeated = await PostgresWorkflowDefinitionCatalog(
        DefinitionStore([_definition("upstream-1")])._fetch_all
    ).read(PRINCIPAL)
    changed = await PostgresWorkflowDefinitionCatalog(
        DefinitionStore([_definition("upstream-1", lifecycle="published")])._fetch_all
    ).read(PRINCIPAL)

    assert first.provenance.revision == repeated.provenance.revision
    assert first.provenance.revision != changed.provenance.revision


@pytest.mark.parametrize(
    ("definitions", "bindings"),
    [
        ([_definition("bad-origin", origin="vendor")], []),
        ([_definition("bad-lifecycle", lifecycle="enforced")], []),
        ([_definition("bad-name", workflow_document={"name": "other", "steps": []})], []),
        ([_definition("no-steps", workflow_document={"name": "workflow-no-steps"})], []),
        ([_definition("bad-versions", resolved_action_versions={"compute.restart": 1})], []),
        ([_definition("blank-owner", owner_ref=" ")], []),
        ([], [_binding("bad-enabled", enabled="yes")]),
        ([], [_binding("bad-revision", revision=0)]),
        ([], [_binding("bad-trigger", trigger="webhook")]),
        ([], [_binding("nested-parameter", parameters={"scope": {"id": "x"}})]),
    ],
)
async def test_malformed_records_fail_closed(
    definitions: list[dict[str, object]],
    bindings: list[dict[str, object]],
) -> None:
    store = DefinitionStore(definitions, bindings)

    with pytest.raises(PostgresFamilyStoreUnavailable, match="malformed"):
        await PostgresWorkflowDefinitionCatalog(store._fetch_all).read(PRINCIPAL)


async def test_exceeding_a_read_bound_fails_closed_instead_of_truncating() -> None:
    definitions = [_definition(f"upstream-{index}") for index in range(MAX_VISIBLE_DEFINITIONS + 1)]
    bindings = [_binding(f"binding-{index}") for index in range(MAX_PRINCIPAL_BINDINGS + 1)]

    with pytest.raises(PostgresFamilyStoreUnavailable, match="read bound"):
        await PostgresWorkflowDefinitionCatalog(DefinitionStore(definitions)._fetch_all).read(
            PRINCIPAL
        )
    with pytest.raises(PostgresFamilyStoreUnavailable, match="read bound"):
        await PostgresWorkflowDefinitionCatalog(DefinitionStore([], bindings)._fetch_all).read(
            PRINCIPAL
        )


def test_definition_route_returns_the_principal_catalog_with_provenance() -> None:
    store = DefinitionStore(_grouping_rows(), [_binding("binding-1")])

    response = _client(PostgresWorkflowAdapters(cast(Any, store))).get("/workflows/definitions")

    assert response.status_code == 200
    assert response.headers["x-fdai-provenance"] == WORKFLOW_DEFINITION_CATALOG_SOURCE
    assert len(response.headers["x-fdai-revision"]) == 64
    body = response.json()
    assert body["counts"] == {"built_in": 1, "shared": 2, "mine": 2}
    assert [binding["binding_id"] for binding in body["bindings"]] == ["binding-1"]
    assert {call[1]["principal_id"] for call in store.calls} == {PRINCIPAL}


def test_definition_route_is_explicitly_unavailable_when_the_store_is() -> None:
    store = DefinitionStore(
        failure=PostgresFamilyStoreUnavailable(
            "authoritative PostgreSQL family store is unavailable"
        )
    )

    response = _client(PostgresWorkflowAdapters(cast(Any, store))).get("/workflows/definitions")

    assert response.status_code == 503
    assert "authoritative PostgreSQL family store is unavailable" in response.text


def test_unconfigured_store_keeps_both_routes_explicitly_unavailable() -> None:
    client = _client(UnavailableWorkflowAdapters())

    for path in ("/workflows/definitions", "/python-tasks/capabilities"):
        response = client.get(path)
        assert response.status_code == 503
        assert "authoritative workflow store is unavailable" in response.text


def test_capability_route_reports_an_explicit_unbound_state() -> None:
    response = _client(PostgresWorkflowAdapters(cast(Any, DefinitionStore()))).get(
        "/python-tasks/capabilities"
    )

    assert response.status_code == 200
    assert response.headers["x-fdai-provenance"] == PYTHON_TASK_CAPABILITY_SOURCE
    assert response.json() == {
        "schema_version": "1.0.0",
        "available": False,
        "unavailable_reasons": [
            "python_task_validator_not_bound",
            "python_task_vm_runner_not_bound",
        ],
        "operations": {
            "generate": False,
            "validate": False,
            "stage": False,
            "test": False,
            "request_run": False,
            "schedule": False,
        },
        "vm_task_runner": {"bound": False},
        "execution_authority": False,
    }
