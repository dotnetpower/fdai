"""Secured source and typed-function handlers for ontology query plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass

from fdai_service_contracts.ontology_query import OntologyQueryNode

from fdai.shared.contracts.models import CeilingRole, OntologyFunctionKind
from fdai.shared.ontology.acl import ProjectionRequest

from .functions import FunctionInvocationContext, OntologyFunctionRegistry
from .graph_query_refresh import SecuredGraphEvidenceQueryRefresher
from .models import (
    ObjectSetDefinition,
    ObjectTraversal,
    RelationshipTraversalDefinition,
    TypedPathDefinition,
)
from .query_execution import QueryNodeHeldError, QueryNodeResult
from .query_gateway import SecuredObjectSetQueryGateway, SecuredObjectSetQueryResult
from .query_receipt_authority import SecuredQueryReceiptAuthority
from .query_values import QueryRow, QueryTable


class SecuredObjectSetNodeHandler:
    """Materialize one ACL- and purpose-scoped ObjectSet as a bounded table."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
        graph_refresher: SecuredGraphEvidenceQueryRefresher | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority
        self._graph_refresher = graph_refresher

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if dependencies:
            raise ValueError("object_set node MUST NOT consume dependency results")
        definition = ObjectSetDefinition.model_validate(node.arguments.get("definition"))
        secured = await self._gateway.materialize(
            definition,
            projection_request=self._request,
        )
        if self._graph_refresher is not None:
            secured = await self._graph_refresher.refresh(
                definition=definition,
                projection_request=self._request,
                secured=secured,
            )
        if self._receipt_authority is not None:
            self._receipt_authority.issue(secured)
        table = _secured_query_table(secured)
        return QueryNodeResult(
            value=table,
            evidence_refs=(
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                f"ontology-query-table:{table.digest}",
            ),
        )


class SecuredRelationshipTraversalNodeHandler:
    """Traverse from one unambiguous secured entity-resolution result."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if len(node.depends_on) != 1 or set(dependencies) != set(node.depends_on):
            raise ValueError("relationship traversal requires one declared dependency")
        dependency = dependencies[node.depends_on[0]].value
        if not isinstance(dependency, QueryTable):
            raise TypeError("relationship traversal dependency MUST be a QueryTable")
        if not dependency.complete:
            raise QueryNodeHeldError("entity_resolution_incomplete")
        if not dependency.rows:
            raise QueryNodeHeldError("entity_resolution_empty")
        if len(dependency.rows) != 1:
            raise QueryNodeHeldError("entity_resolution_ambiguous")
        traversal = RelationshipTraversalDefinition.model_validate(node.arguments)
        definition = ObjectSetDefinition(
            selector=traversal.selector,
            traversal=ObjectTraversal(
                link_types=traversal.link_types,
                direction=traversal.direction,
                max_depth=traversal.max_depth,
            ),
            root_ids=(dependency.rows[0].row_id,),
            as_of=traversal.as_of,
            purpose=traversal.purpose,
            limit=traversal.limit,
        )
        secured = await self._gateway.materialize(
            definition,
            projection_request=self._request,
        )
        if self._receipt_authority is not None:
            self._receipt_authority.issue(secured)
        table = _relationship_traversal_table(
            secured,
            root_ids=(dependency.rows[0].row_id,),
            link_type=traversal.link_types[0],
            direction=traversal.direction,
        )
        return QueryNodeResult(
            value=table,
            evidence_refs=_evidence_refs(dependencies)
            + (
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                f"ontology-object-set-output:{secured.receipt.projected_result_digest}",
                f"ontology-query-table:{table.digest}",
            ),
        )


def _relationship_traversal_table(
    secured: SecuredObjectSetQueryResult,
    *,
    root_ids: tuple[str, ...],
    link_type: str,
    direction: str,
) -> QueryTable:
    """Return only endpoints reached from the dependency roots."""

    roots = set(root_ids)
    reached: set[str] = set()
    for link in secured.materialization.graph.links:
        if link.link_type != link_type:
            continue
        if direction == "outgoing" and link.from_id in roots:
            reached.add(link.to_id)
        elif direction == "incoming" and link.to_id in roots:
            reached.add(link.from_id)
    raw_table = _secured_query_table(secured)
    if not reached:
        reached = {row.row_id for row in raw_table.rows if row.row_id not in roots}
    return QueryTable(
        rows=tuple(row for row in raw_table.rows if row.row_id in reached),
        complete=raw_table.complete,
        truncation_reason=raw_table.truncation_reason,
    )


class SecuredTypedPathNodeHandler:
    """Execute an ordered path as independently secured single-hop reads."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if len(node.depends_on) != 1 or set(dependencies) != set(node.depends_on):
            raise ValueError("typed path requires one declared dependency")
        dependency = dependencies[node.depends_on[0]].value
        if not isinstance(dependency, QueryTable):
            raise TypeError("typed path dependency MUST be a QueryTable")
        if not dependency.complete:
            raise QueryNodeHeldError("entity_resolution_incomplete")
        if not dependency.rows:
            raise QueryNodeHeldError("entity_resolution_empty")
        if len(dependency.rows) != 1:
            raise QueryNodeHeldError("entity_resolution_ambiguous")
        path = TypedPathDefinition.model_validate(node.arguments)
        current = dependency
        evidence_refs = list(_evidence_refs(dependencies))
        for index, step in enumerate(path.steps):
            root_ids = tuple(row.row_id for row in current.rows)
            definition = ObjectSetDefinition(
                selector=step.selector,
                traversal=ObjectTraversal(
                    link_types=(step.link_type,),
                    direction=step.direction,
                    max_depth=step.max_hops,
                ),
                root_ids=root_ids,
                as_of=path.as_of,
                purpose=path.purpose,
                limit=path.limit,
            )
            secured = await self._gateway.materialize(
                definition,
                projection_request=self._request,
            )
            if self._receipt_authority is not None:
                self._receipt_authority.issue(secured)
            current = _typed_path_step_table(
                secured,
                root_ids=root_ids,
                link_type=step.link_type,
                direction=step.direction,
                max_hops=step.max_hops,
            )
            evidence_refs.extend(
                (
                    f"ontology-object-set:{secured.receipt.projected_result_digest}",
                    f"ontology-query-table:{current.digest}",
                )
            )
            if not current.complete and index < len(path.steps) - 1:
                raise QueryNodeHeldError("typed_path_step_incomplete")
            if not current.rows:
                break
        return QueryNodeResult(
            value=current,
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        )


def _typed_path_step_table(
    secured: SecuredObjectSetQueryResult,
    *,
    root_ids: tuple[str, ...],
    link_type: str,
    direction: str,
    max_hops: int,
) -> QueryTable:
    """Return only endpoints reached by one typed step, excluding carried roots."""

    roots = set(root_ids)
    reached: set[str] = set()
    for link in secured.materialization.graph.links:
        if link.link_type != link_type:
            continue
        if direction == "outgoing" and link.from_id in roots:
            reached.add(link.to_id)
        elif direction == "incoming" and link.to_id in roots:
            reached.add(link.from_id)
    raw_table = _secured_query_table(secured)
    if max_hops > 1:
        reached = {row.row_id for row in raw_table.rows if row.row_id not in roots}
    if not reached:
        reached = {row.row_id for row in raw_table.rows if row.row_id not in roots}
    return QueryTable(
        rows=tuple(row for row in raw_table.rows if row.row_id in reached),
        complete=raw_table.complete,
        truncation_reason=raw_table.truncation_reason,
    )


class FunctionNodeHandler:
    """Invoke one exact-release query, derive, or validate function with a receipt."""

    def __init__(
        self,
        registry: OntologyFunctionRegistry,
        *,
        context: FunctionInvocationContext,
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
    ) -> None:
        self._registry = registry
        self._context = context
        self._receipt_authority = receipt_authority

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        function_name = node.arguments.get("function_name")
        if not isinstance(function_name, str):
            raise ValueError("function node requires function_name")
        declaration = self._registry.declaration(function_name)
        if declaration.kind is OntologyFunctionKind.PLAN:
            raise PermissionError("query plan MUST NOT invoke plan functions")
        raw_arguments = node.arguments.get("arguments", {})
        if not isinstance(raw_arguments, dict):
            raise ValueError("function arguments MUST be an object")
        arguments = dict(raw_arguments)
        raw_bindings = node.arguments.get("dependency_arguments", {})
        if not isinstance(raw_bindings, dict):
            raise ValueError("function dependency_arguments MUST be an object")
        if set(raw_bindings) != set(node.depends_on):
            raise ValueError("function dependency arguments MUST bind every dependency")
        invocation_context = self._context
        secured_digests: list[str] = []
        for dependency_id, argument_name_raw in raw_bindings.items():
            argument_name = _argument_name(argument_name_raw)
            if argument_name in arguments:
                raise ValueError("function dependency argument collides with static argument")
            dependency = dependencies[dependency_id]
            if argument_name.endswith("query_result") and self._receipt_authority is not None:
                secured = self._receipt_authority.resolve(dependency.evidence_refs)
                arguments[argument_name] = secured.model_dump(mode="json")
                secured_digests.append(secured.receipt.projected_result_digest)
            else:
                arguments[argument_name] = _function_value(dependency.value)
        if secured_digests:
            invocation_context = self._context.model_copy(
                update={"evidence_refs": tuple(sorted(secured_digests))}
            )
        result, receipt = await self._registry.invoke_with_receipt(
            function_name,
            arguments,
            context=invocation_context,
        )
        value = (
            _query_table(result)
            if node.output_kind == "query.table" and isinstance(result, Mapping)
            else result
        )
        return QueryNodeResult(
            value=value,
            evidence_refs=_evidence_refs(dependencies)
            + (f"ontology-function:{receipt.invocation_id}",),
        )


def _argument_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("function argument name MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(not part or not part.replace("_", "").replace("-", "").isalnum() for part in parts):
        raise ValueError("function argument name MUST be a dot-separated identifier")
    return value


def _function_value(value: object) -> object:
    if isinstance(value, QueryTable):
        return json.loads(value.canonical_json())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _query_table(value: object) -> QueryTable:
    if not isinstance(value, Mapping) or set(value) != {
        "rows",
        "complete",
        "truncation_reason",
    }:
        raise ValueError("query.table function output is malformed")
    raw_rows = value["rows"]
    if not isinstance(raw_rows, list):
        raise ValueError("query.table function rows MUST be a list")
    rows: list[QueryRow] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or set(raw_row) != {"row_id", "values"}:
            raise ValueError("query.table function row is malformed")
        row_id = raw_row["row_id"]
        if not isinstance(row_id, str):
            raise ValueError("query.table function row_id MUST be a string")
        rows.append(QueryRow.from_values(row_id, raw_row["values"]))
    complete = value["complete"]
    truncation_reason = value["truncation_reason"]
    if not isinstance(complete, bool) or (
        truncation_reason is not None and not isinstance(truncation_reason, str)
    ):
        raise ValueError("query.table function completeness is malformed")
    return QueryTable(
        rows=tuple(rows),
        complete=complete,
        truncation_reason=truncation_reason,
    )


def _secured_query_table(secured: SecuredObjectSetQueryResult) -> QueryTable:
    limitation = (
        secured.receipt.truncation_reason.value
        if secured.receipt.truncation_reason is not None
        else None
        if secured.receipt.complete
        else "source_incomplete"
    )
    return QueryTable(
        rows=tuple(
            QueryRow.from_values(
                record.id,
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": record.properties,
                },
            )
            for record in secured.materialization.graph.objects
        ),
        complete=secured.receipt.complete,
        truncation_reason=limitation,
    )


def _evidence_refs(dependencies: Mapping[str, QueryNodeResult]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence_ref
            for result in dependencies.values()
            for evidence_ref in result.evidence_refs
            if not evidence_ref.startswith("ontology-object-set-output:")
        )
    )


__all__ = [
    "FunctionNodeHandler",
    "SecuredObjectSetNodeHandler",
    "SecuredRelationshipTraversalNodeHandler",
    "SecuredTypedPathNodeHandler",
]
