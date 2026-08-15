"""Built-in generic ontology query handler tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform import (
    AggregateNodeHandler,
    FunctionInvocationContext,
    FunctionNodeHandler,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    OntologyFunctionRegistry,
    OrderNodeHandler,
    ProjectNodeHandler,
    QueryNodeResult,
    QueryRow,
    QueryTable,
    SecuredObjectSetNodeHandler,
    SetOperationNodeHandler,
    compile_interfaces,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _node(
    kind: QueryNodeKind,
    *,
    dependencies: tuple[str, ...],
    arguments: dict[str, object] | None = None,
) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=f"node.{kind.value}",
        kind=kind,
        depends_on=dependencies,
        arguments_json=canonical_json(arguments or {}),
        output_kind="query.table",
    )


def _table(*rows: tuple[str, dict[str, object]], complete: bool = True) -> QueryTable:
    return QueryTable(
        rows=tuple(QueryRow.from_values(row_id, values) for row_id, values in rows),
        complete=complete,
        truncation_reason=None if complete else "source_limit",
    )


async def test_set_operations_are_identity_stable_and_propagate_incompleteness() -> None:
    first = _table(("a", {"value": 1}), ("b", {"value": 2}))
    second = _table(("b", {"value": 2}), ("c", {"value": 3}), complete=False)
    dependencies = {
        "left": QueryNodeResult(first, ("evidence:left",)),
        "right": QueryNodeResult(second, ("evidence:right",)),
    }

    union = await SetOperationNodeHandler("union")(
        _node(QueryNodeKind.UNION, dependencies=("left", "right")), dependencies
    )
    intersection = await SetOperationNodeHandler("intersection")(
        _node(QueryNodeKind.INTERSECTION, dependencies=("left", "right")), dependencies
    )
    subtraction = await SetOperationNodeHandler("subtraction")(
        _node(QueryNodeKind.SUBTRACTION, dependencies=("left", "right")), dependencies
    )

    assert isinstance(union.value, QueryTable)
    assert [row.row_id for row in union.value.rows] == ["a", "b", "c"]
    assert union.value.complete is False
    assert union.value.truncation_reason == "source_limit"
    assert [row.row_id for row in intersection.value.rows] == ["b"]
    assert [row.row_id for row in subtraction.value.rows] == ["a"]
    assert union.evidence_refs[:2] == ("evidence:left", "evidence:right")


async def test_set_operation_rejects_conflicting_identity_payloads() -> None:
    dependencies = {
        "left": QueryNodeResult(_table(("same", {"value": 1}))),
        "right": QueryNodeResult(_table(("same", {"value": 2}))),
    }

    with pytest.raises(ValueError, match="conflicting payloads"):
        await SetOperationNodeHandler("union")(
            _node(QueryNodeKind.UNION, dependencies=("left", "right")), dependencies
        )


async def test_order_project_and_aggregate_preserve_typed_bounds() -> None:
    source = _table(
        ("a", {"team": "blue", "score": 2}),
        ("b", {"team": "red", "score": 3}),
        ("c", {"team": "blue", "score": 4}),
    )
    dependency = {"source": QueryNodeResult(source, ("evidence:source",))}

    ordered = await OrderNodeHandler()(
        _node(
            QueryNodeKind.ORDER,
            dependencies=("source",),
            arguments={
                "keys": [{"field": "score", "direction": "descending"}],
                "limit": 2,
            },
        ),
        dependency,
    )
    assert [row.row_id for row in ordered.value.rows] == ["c", "b"]
    assert ordered.value.complete is False
    assert ordered.value.truncation_reason == "result_limit"

    projected = await ProjectNodeHandler()(
        _node(
            QueryNodeKind.PROJECT,
            dependencies=("source",),
            arguments={"fields": ["team", "score"]},
        ),
        dependency,
    )
    assert projected.value.rows[0].values == {"score": 2, "team": "blue"}

    aggregated = await AggregateNodeHandler()(
        _node(
            QueryNodeKind.AGGREGATE,
            dependencies=("source",),
            arguments={"operation": "average", "field": "score", "group_by": ["team"]},
        ),
        dependency,
    )
    values = [row.values for row in aggregated.value.rows]
    assert values == [
        {"group": {"team": "blue"}, "operation": "average", "value": "3"},
        {"group": {"team": "red"}, "operation": "average", "value": "3"},
    ]


async def test_empty_global_count_is_complete_zero() -> None:
    dependency = {"source": QueryNodeResult(_table())}

    result = await AggregateNodeHandler()(
        _node(
            QueryNodeKind.AGGREGATE,
            dependencies=("source",),
            arguments={"operation": "count"},
        ),
        dependency,
    )

    assert result.value.complete is True
    assert result.value.rows[0].values == {
        "group": {},
        "operation": "count",
        "value": 0,
    }


async def test_function_handler_binds_dependencies_and_returns_exact_receipt() -> None:
    declaration = OntologyFunctionType(
        name="query.row_count",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + ("a" * 64),
        publisher="fdai",
        input_schema={
            "type": "object",
            "required": ["source"],
            "properties": {"source": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={"type": "integer"},
        purpose_bindings=["operations-review"],
    )
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)

    async def count_rows(arguments: dict[str, object]) -> int:
        source = arguments["source"]
        assert isinstance(source, dict)
        rows = source["rows"]
        assert isinstance(rows, list)
        return len(rows)

    registry.register(declaration, count_rows)
    handler = FunctionNodeHandler(
        registry,
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    dependency = {"source": QueryNodeResult(_table(("a", {"value": 1})), ("evidence:source",))}

    result = await handler(
        _node(
            QueryNodeKind.FUNCTION,
            dependencies=("source",),
            arguments={
                "function_name": "query.row_count",
                "arguments": {},
                "dependency_arguments": {"source": "source"},
            },
        ),
        dependency,
    )

    assert result.value == 1
    assert result.evidence_refs[0] == "evidence:source"
    assert result.evidence_refs[1].startswith("ontology-function:logic-invocation:")


async def test_function_handler_converts_query_table_output() -> None:
    declaration = OntologyFunctionType(
        name="query.table_source",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + ("b" * 64),
        publisher="fdai",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object"},
        purpose_bindings=["operations-review"],
    )
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)

    async def table_source(_arguments: dict[str, object]) -> dict[str, object]:
        return {
            "rows": [{"row_id": "row-a", "values": {"name": "Resource"}}],
            "complete": True,
            "truncation_reason": None,
        }

    registry.register(declaration, table_source)
    handler = FunctionNodeHandler(
        registry,
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    result = await handler(
        _node(
            QueryNodeKind.FUNCTION,
            dependencies=(),
            arguments={
                "function_name": "query.table_source",
                "arguments": {},
                "dependency_arguments": {},
            },
        ),
        {},
    )

    assert isinstance(result.value, QueryTable)
    assert result.value.rows[0].values == {"name": "Resource"}
    assert result.value.complete is True


async def test_secured_object_set_handler_applies_property_acl() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )
    release = build_ontology_release(object_types=(resource,))
    interfaces = compile_interfaces(
        interfaces=(),
        implementations=(),
        object_types=(resource,),
        release=release,
    )
    store = InMemoryOntologyInstanceStore(object_types=(resource,), link_types=())
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "secret": "redacted"},
        )
    )
    service = ObjectSetService(
        store=store,
        interfaces=interfaces,
        object_type_names=frozenset({"Resource"}),
    )
    gateway = SecuredObjectSetQueryGateway(
        service=service,
        object_types={"Resource": resource},
        ontology_release=release,
        evaluation_cutoff=lambda: NOW,
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    handler = SecuredObjectSetNodeHandler(
        gateway,
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )

    result = await handler(
        _node(
            QueryNodeKind.OBJECT_SET,
            dependencies=(),
            arguments={"definition": definition.model_dump(mode="json")},
        ),
        {},
    )

    assert isinstance(result.value, QueryTable)
    properties = result.value.rows[0].values["properties"]
    assert properties["id"] == "resource-a"
    assert properties["secret"] == "[redacted]"
    assert properties["__redactions__"]["secret"]["reason"] == "access_scope"
    assert result.evidence_refs[0].startswith("ontology-object-set:sha256:")
