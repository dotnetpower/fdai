"""Secured source and typed-function handlers for ontology query plans."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    content_digest,
)

from fdai.shared.contracts.models import CeilingRole, OntologyFunctionKind
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

from .functions import FunctionInvocationContext, OntologyFunctionRegistry
from .graph_query_refresh import SecuredGraphEvidenceQueryRefresher
from .models import (
    ObjectSetDefinition,
    ObjectTraversal,
    OntologyInstancePathDefinition,
    RelationshipTraversalDefinition,
    TypedPathDefinition,
)
from .query_execution import QueryNodeHeldError, QueryNodeResult
from .query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryResult,
    SecuredOntologyInstancePathGraph,
    SecuredOntologyInstancePathReceipt,
)
from .query_receipt_authority import SecuredQueryReceiptAuthority, secured_query_scope_digest
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
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
        graph_refresher: SecuredGraphEvidenceQueryRefresher | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority
        self._decision_evidence = decision_evidence
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
            await _issue_secured_result(
                self._receipt_authority,
                secured,
                provider=self._decision_evidence,
            )
        table = _secured_query_table(secured)
        return QueryNodeResult(
            value=table,
            evidence_refs=(
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                f"ontology-query-table:{table.digest}",
            ),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
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
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority
        self._decision_evidence = decision_evidence

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
            await _issue_secured_result(
                self._receipt_authority,
                secured,
                provider=self._decision_evidence,
            )
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
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
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
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
        )
        self._receipt_authority = receipt_authority
        self._decision_evidence = decision_evidence

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
                await _issue_secured_result(
                    self._receipt_authority,
                    secured,
                    provider=self._decision_evidence,
                )
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
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )


class SecuredOntologyInstancePathNodeHandler:
    """Return concrete multi-root instance paths under one composite read authority."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        principal_scope_digest: str,
    ) -> None:
        if not principal_scope_digest:
            raise ValueError("ontology instance path requires a principal scope digest")
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
            principal_scope_digest=principal_scope_digest,
        )

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if set(dependencies) != set(node.depends_on):
            raise ValueError("ontology instance path dependencies do not match the plan")
        definition = OntologyInstancePathDefinition.model_validate(node.arguments)
        secured = await self._gateway.materialize_instance_path(
            definition,
            projection_request=self._request,
        )
        _verify_instance_path_schema(
            dependencies,
            node=node,
            definition=definition,
            ontology_release_digest=secured.ontology_release.digest,
        )
        _verify_instance_path_graph(secured)
        paths, empty_at_step = _instance_paths(secured.graph, definition=definition)
        if not paths:
            raise QueryNodeHeldError("ontology_instance_path_empty")
        rows = tuple(_instance_path_row(path) for path in paths)
        table = QueryTable(rows=rows, complete=True)
        receipt = SecuredOntologyInstancePathReceipt(
            ontology_release=secured.ontology_release,
            principal_scope_digest=secured.principal_scope_digest,
            purpose=secured.purpose,
            caller_role=secured.caller_role,
            definition_digest=content_digest(definition.model_dump(mode="json")),
            projected_graph_digest=secured.projected_graph_digest,
            result_digest=table.digest,
            component_authorities=(
                EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
            ),
            source_generation=secured.graph.source_generation,
            observation_cutoff=secured.observation_cutoff,
            path_count=len(rows),
            empty_at_step=empty_at_step,
        )
        return QueryNodeResult(
            value=table,
            evidence_refs=_evidence_refs(dependencies)
            + (
                f"ontology-instance-path:{receipt.receipt_digest}",
                f"ontology-query-table:{table.digest}",
            ),
            authority=EvidenceAuthority.SERVER_ONTOLOGY_INSTANCE_PATH,
            authority_inputs=receipt.component_authorities,
        )


def _verify_instance_path_schema(
    dependencies: Mapping[str, QueryNodeResult],
    *,
    node: OntologyQueryNode,
    definition: OntologyInstancePathDefinition,
    ontology_release_digest: str,
) -> None:
    current_type = definition.root_selector.name
    for dependency_id, step in zip(node.depends_on, definition.steps, strict=True):
        value = dependencies[dependency_id].value
        expected_source = current_type if step.direction == "outgoing" else step.selector.name
        expected_target = step.selector.name if step.direction == "outgoing" else current_type
        relationships = value.get("relationships") if isinstance(value, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or value.get("authority") != "ontology_release"
            or value.get("ontology_release_digest") != ontology_release_digest
            or value.get("execution_authority") is not False
            or value.get("complete") is not True
            or not isinstance(relationships, list)
            or not any(
                isinstance(relationship, Mapping)
                and relationship.get("link_type") == step.link_type
                and relationship.get("from_type") == expected_source
                and relationship.get("to_type") == expected_target
                for relationship in relationships
            )
        ):
            raise QueryNodeHeldError("ontology_instance_path_schema_unverified")
        current_type = step.selector.name


def _verify_instance_path_graph(secured: SecuredOntologyInstancePathGraph) -> None:
    if not secured.principal_scope_digest:
        raise QueryNodeHeldError("ontology_instance_path_scope_missing")
    if secured.graph.truncated or not secured.graph.source_complete:
        raise QueryNodeHeldError("ontology_instance_path_incomplete")
    if (
        secured.redactions.redacted_identity_count
        or secured.redactions.removed_link_count
        or secured.redactions.links_with_redactions
    ):
        raise QueryNodeHeldError("ontology_instance_path_identity_redacted")


def _instance_paths(
    graph: OntologyGraphSnapshot,
    *,
    definition: OntologyInstancePathDefinition,
) -> tuple[tuple[tuple[OntologyObjectRecord, ...], ...], int | None]:
    objects = {record.id: record for record in graph.objects}
    paths: tuple[tuple[OntologyObjectRecord, ...], ...] = tuple(
        (record,) for record in graph.objects if record.object_type == definition.root_selector.name
    )
    if not paths:
        return (), 0
    for index, step in enumerate(definition.steps, start=1):
        expanded: list[tuple[OntologyObjectRecord, ...]] = []
        for path in paths:
            root_id = path[-1].id
            for link in graph.links:
                target_id = None
                if (
                    link.link_type == step.link_type
                    and step.direction == "outgoing"
                    and link.from_id == root_id
                ):
                    target_id = link.to_id
                elif (
                    link.link_type == step.link_type
                    and step.direction == "incoming"
                    and link.to_id == root_id
                ):
                    target_id = link.from_id
                target = objects.get(target_id) if target_id is not None else None
                if target is None or target.object_type != step.selector.name:
                    continue
                expanded.append((*path, target))
                if len(expanded) > definition.limit:
                    raise QueryNodeHeldError("ontology_instance_path_limit_exceeded")
        paths = tuple(expanded)
        if not paths:
            return (), index
    if graph.source_generation is None:
        raise QueryNodeHeldError("ontology_instance_path_generation_unavailable")
    return paths, None


def _instance_path_row(path: tuple[OntologyObjectRecord, ...]) -> QueryRow:
    values: dict[str, object] = {
        "root_id": path[0].id,
        "root_type": path[0].object_type,
        "target_id": path[-1].id,
        "target_type": path[-1].object_type,
        "execution_authority": False,
    }
    for index, record in enumerate(path[1:], start=1):
        values[f"step_{index}_id"] = record.id
        values[f"step_{index}_type"] = record.object_type
    return QueryRow.from_values(
        content_digest({"path": [record.id for record in path]}),
        values,
    )


async def _issue_secured_result(
    authority: SecuredQueryReceiptAuthority,
    result: SecuredObjectSetQueryResult,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> None:
    admission = None
    if provider is not None:
        receipt = result.receipt
        admission = await provider.admit(
            evidence_digest=receipt.projected_result_digest,
            scope_digest=secured_query_scope_digest(receipt),
            purpose_id=receipt.purpose,
            source_revision=receipt.ontology_release.digest,
        )
    authority.issue(result, admission)


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
            authority=receipt.authority,
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
    "SecuredOntologyInstancePathNodeHandler",
    "SecuredRelationshipTraversalNodeHandler",
    "SecuredTypedPathNodeHandler",
]
