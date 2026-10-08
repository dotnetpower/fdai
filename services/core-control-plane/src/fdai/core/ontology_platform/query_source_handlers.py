"""Secured source and typed-function handlers for ontology query plans."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass, replace
from functools import partial

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    content_digest,
)

from fdai.shared.contracts.models import CeilingRole, OntologyFunctionKind
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider

from .functions import FunctionInvocationContext, OntologyFunctionRegistry
from .graph_query_refresh import SecuredGraphEvidenceQueryRefresher
from .models import (
    ObjectSetDefinition,
    ObjectTraversal,
    OntologyInstancePathDefinition,
    RelationshipTraversalDefinition,
    TypedPathDefinition,
)
from .pending_state_coverage import PendingStateCoverageLedger, PendingStateRefresher
from .query_execution import QueryNodeHeldError, QueryNodeResult
from .query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryResult,
    SecuredOntologyInstancePathGraph,
    SecuredOntologyInstancePathReceipt,
)
from .query_handler_values import argument_name, evidence_refs
from .query_instance_paths import instance_path_row, instance_paths
from .query_lineage_batches import (
    LINEAGE_READ_BUDGET,
    LINEAGE_ROOT_BATCH,
    batched_lineage_result,
    root_names,
)
from .query_receipt_authority import SecuredQueryReceiptAuthority, secured_query_scope_digest
from .query_traversal_population import traversal_population_count
from .query_traversal_tables import (
    relationship_lineage_table,
    relationship_traversal_table,
    secured_query_table,
    traversal_endpoints,
    with_root_coverage,
)
from .query_values import QueryRow, QueryTable

_LOGGER = logging.getLogger(__name__)


class SecuredObjectSetNodeHandler:
    """Materialize one ACL- and purpose-scoped ObjectSet as a bounded table."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        principal_scope_digest: str | None = None,
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
        graph_refresher: SecuredGraphEvidenceQueryRefresher | None = None,
        pending_state_refresher: PendingStateRefresher | None = None,
    ) -> None:
        self._gateway = gateway
        self._pending_state_refresher = pending_state_refresher
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
            principal_scope_digest=principal_scope_digest,
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
        started = time.perf_counter()
        try:
            secured = await self._gateway.materialize(
                definition,
                projection_request=self._request,
            )
        except ValueError:
            _LOGGER.warning("secured_object_set_failed", extra={"stage": "materialize"})
            raise
        materialized = time.perf_counter()
        if self._graph_refresher is not None:
            try:
                secured = await self._graph_refresher.refresh(
                    definition=definition,
                    projection_request=self._request,
                    secured=secured,
                )
            except ValueError:
                _LOGGER.warning("secured_object_set_failed", extra={"stage": "refresh"})
                raise
        live_refs: tuple[str, ...] = ()
        if self._pending_state_refresher is not None:
            secured, live_refs = await self._pending_state_refresher.cover(
                node_id=node.node_id,
                definition=definition,
                projection_request=self._request,
                secured=secured,
            )
        refreshed = time.perf_counter()
        if self._receipt_authority is not None:
            try:
                await _issue_secured_result(
                    self._receipt_authority,
                    secured,
                    provider=self._decision_evidence,
                )
            except ValueError:
                _LOGGER.warning("secured_object_set_failed", extra={"stage": "receipt"})
                raise
        issued = time.perf_counter()
        _LOGGER.info(
            "ontology_object_set_stages_timed",
            extra={
                "materialize_ms": round((materialized - started) * 1000),
                "refresh_ms": round((refreshed - materialized) * 1000),
                "receipt_ms": round((issued - refreshed) * 1000),
                "object_count": len(secured.materialization.graph.objects),
                # Why a scope is partial, as closed codes, so a partial answer is diagnosable.
                "scope_complete": secured.receipt.complete,
                "source_incomplete_reason": secured.materialization.graph.source_incomplete_reason
                or "none",
                "truncation_reason": str(secured.receipt.truncation_reason or "none"),
            },
        )
        table = secured_query_table(secured)
        return QueryNodeResult(
            value=table,
            evidence_refs=(
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                f"ontology-query-table:{table.digest}",
                *live_refs,
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
        principal_scope_digest: str | None = None,
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
        graph_refresher: SecuredGraphEvidenceQueryRefresher | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
            principal_scope_digest=principal_scope_digest,
        )
        self._receipt_authority = receipt_authority
        self._decision_evidence = decision_evidence
        self._graph_refresher = graph_refresher

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
        traversal = RelationshipTraversalDefinition.model_validate(node.arguments)
        if not traversal.emit_lineage and len(dependency.rows) != 1:
            reason = ("entity_resolution_ambiguous", "entity_resolution_empty")[not dependency.rows]
            raise QueryNodeHeldError(reason)
        elif not dependency.rows:
            table = QueryTable(
                rows=(), complete=True, source_generation=dependency.source_generation
            )
            return QueryNodeResult(
                value=table,
                evidence_refs=evidence_refs(dependencies)
                + (f"ontology-query-table:{table.digest}",),
                authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
            )
        root_ids = tuple(row.row_id for row in dependency.rows)
        if traversal.emit_lineage and len(root_ids) > LINEAGE_ROOT_BATCH:
            return await batched_lineage_result(
                traversal,
                root_ids,
                dependency=dependency,
                base_evidence_refs=evidence_refs(dependencies),
                gateway=self._gateway,
                request=self._request,
                receipt_authority=self._receipt_authority,
                decision_evidence=self._decision_evidence,
                graph_refresher=self._graph_refresher,
                root_batch=LINEAGE_ROOT_BATCH,
                read_budget=LINEAGE_READ_BUDGET,
            )
        definition = ObjectSetDefinition(
            selector=traversal.selector,
            traversal=ObjectTraversal(
                link_types=traversal.link_types,
                direction=traversal.direction,
                max_depth=traversal.max_depth,
            ),
            root_ids=root_ids,
            as_of=traversal.as_of,
            purpose=traversal.purpose,
            limit=traversal.limit,
            freshness_seconds=traversal.freshness_seconds,
        )
        secured = await self._gateway.materialize(
            definition,
            projection_request=self._request,
        )
        secured = await _refresh_traversal_result(
            secured,
            definition=definition,
            request=self._request,
            refresher=self._graph_refresher,
            expected_generation=dependency.source_generation,
        )
        if self._receipt_authority is not None:
            await _issue_secured_result(
                self._receipt_authority,
                secured,
                provider=self._decision_evidence,
            )
        if traversal.emit_lineage:
            table = relationship_lineage_table(
                secured,
                root_ids=root_ids,
                link_type=traversal.link_types[0],
                direction=traversal.direction,
                max_depth=traversal.max_depth,
                endpoint_predicates=traversal.endpoint_predicates,
            )
            if traversal.emit_coverage:
                table = with_root_coverage(table, root_ids=root_ids, names=root_names(dependency))
            output_refs: tuple[str, ...] = ()
        else:
            table, output_refs = await traversal_endpoints(
                relationship_traversal_table(
                    secured,
                    root_ids=root_ids,
                    link_type=traversal.link_types[0],
                    direction=traversal.direction,
                    max_depth=traversal.max_depth,
                ),
                traversal,
                secured,
                gateway=self._gateway,
                request=self._request,
                issue=(
                    partial(
                        _issue_secured_result,
                        self._receipt_authority,
                        provider=self._decision_evidence,
                    )
                    if self._receipt_authority is not None
                    else None
                ),
            )
        if (
            traversal.read_population
            and secured.receipt.truncated
            and secured.receipt.source_complete
        ):
            count = await traversal_population_count(
                self._gateway,
                traversal,
                root_ids=root_ids,
                request=self._request,
                expected_generation=secured.receipt.source_generation,
            )
            if count is not None and count > len(table.rows):
                table = replace(table, total_rows=count)
        return QueryNodeResult(
            value=table,
            evidence_refs=evidence_refs(dependencies)
            + (
                f"ontology-object-set:{secured.receipt.projected_result_digest}",
                *output_refs,
                f"ontology-query-table:{table.digest}",
            ),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )


class SecuredTypedPathNodeHandler:
    """Execute an ordered path as independently secured single-hop reads."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        caller_role: CeilingRole,
        purposes: Sequence[str],
        principal_scope_digest: str | None = None,
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
        decision_evidence: DecisionEvidenceAdmissionProvider | None = None,
        graph_refresher: SecuredGraphEvidenceQueryRefresher | None = None,
    ) -> None:
        self._gateway = gateway
        self._request = ProjectionRequest(
            caller_role=caller_role,
            declared_purposes=frozenset(purposes),
            principal_scope_digest=principal_scope_digest,
        )
        self._receipt_authority = receipt_authority
        self._decision_evidence = decision_evidence
        self._graph_refresher = graph_refresher

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
        collected_refs = list(evidence_refs(dependencies))
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
                freshness_seconds=path.freshness_seconds,
            )
            secured = await self._gateway.materialize(
                definition,
                projection_request=self._request,
            )
            secured = await _refresh_traversal_result(
                secured,
                definition=definition,
                request=self._request,
                refresher=self._graph_refresher,
                expected_generation=current.source_generation,
            )
            if self._receipt_authority is not None:
                await _issue_secured_result(
                    self._receipt_authority,
                    secured,
                    provider=self._decision_evidence,
                )
            current = relationship_traversal_table(
                secured,
                root_ids=root_ids,
                link_type=step.link_type,
                direction=step.direction,
                max_depth=step.max_hops,
            )
            collected_refs.extend(
                (
                    f"ontology-object-set:{secured.receipt.projected_result_digest}",
                    f"ontology-query-table:{current.digest}",
                )
            )
            if not current.complete and index < len(path.steps) - 1:
                raise QueryNodeHeldError("typed_path_step_incomplete")
            if not current.rows:
                break
        if self._receipt_authority is not None and current.complete:
            # A downstream query_result must identify path endpoints, not its carried root.
            endpoint_ids = tuple(row.row_id for row in current.rows)
            output = await self._gateway.materialize(
                ObjectSetDefinition(
                    selector=path.steps[-1].selector,
                    object_ids=endpoint_ids,
                    as_of=path.as_of,
                    purpose=path.purpose,
                    limit=path.limit,
                    include_relationships=False,
                ),
                projection_request=self._request,
            )
            if (
                current.source_generation is not None
                and output.receipt.source_generation != current.source_generation
            ):
                raise QueryNodeHeldError("query_source_generation_conflict")
            if not output.receipt.complete or {
                item.id for item in output.materialization.graph.objects
            } != set(endpoint_ids):
                raise QueryNodeHeldError("typed_path_endpoint_projection_changed")
            await _issue_secured_result(
                self._receipt_authority, output, provider=self._decision_evidence
            )
            collected_refs = [
                ref for ref in collected_refs if not ref.startswith("ontology-object-set-output:")
            ]
            collected_refs.append(
                f"ontology-object-set-output:{output.receipt.projected_result_digest}"
            )
        elif self._receipt_authority is not None:
            # Retaining a root's output marker would turn an incomplete traversal into a root read.
            raise QueryNodeHeldError("typed_path_endpoint_projection_incomplete")
        return QueryNodeResult(
            value=current,
            evidence_refs=tuple(dict.fromkeys(collected_refs)),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )


async def _refresh_traversal_result(
    secured: SecuredObjectSetQueryResult,
    *,
    definition: ObjectSetDefinition,
    request: ProjectionRequest,
    refresher: SecuredGraphEvidenceQueryRefresher | None,
    expected_generation: str | None,
) -> SecuredObjectSetQueryResult:
    if definition.freshness_seconds is not None:
        if refresher is None:
            raise QueryNodeHeldError("graph_freshness_unavailable")
        secured = await refresher.refresh(
            definition=definition, projection_request=request, secured=secured
        )
    if expected_generation is not None and secured.receipt.source_generation != expected_generation:
        raise QueryNodeHeldError("query_source_generation_conflict")
    return secured


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
        paths, empty_at_step = instance_paths(secured.graph, definition=definition)
        if not paths:
            raise QueryNodeHeldError("ontology_instance_path_empty")
        rows = tuple(instance_path_row(path) for path in paths)
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
            evidence_refs=evidence_refs(dependencies)
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


class FunctionNodeHandler:
    """Invoke one exact-release query, derive, or validate function with a receipt."""

    def __init__(
        self,
        registry: OntologyFunctionRegistry,
        *,
        context: FunctionInvocationContext,
        receipt_authority: SecuredQueryReceiptAuthority | None = None,
        allow_presentation_read_dependencies: bool = False,
        pending_state_ledger: PendingStateCoverageLedger | None = None,
    ) -> None:
        self._registry = registry
        self._context = context
        self._receipt_authority = receipt_authority
        self._pending_state_ledger = pending_state_ledger
        self._allow_presentation_read_dependencies = allow_presentation_read_dependencies

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
            bound_name = argument_name(argument_name_raw)
            # Only the ledger may supply pending-state coverage; a plan can never bind it.
            if bound_name in arguments or bound_name == "pending_state_coverage":
                raise ValueError("function dependency argument collides with a reserved argument")
            dependency = dependencies[dependency_id]
            if bound_name.endswith("query_result") and self._receipt_authority is not None:
                if (
                    self._allow_presentation_read_dependencies
                    and declaration.kind is OntologyFunctionKind.QUERY
                    and self._context.caller_agent == "Bragi"
                    and self._context.purposes == ("operations-review",)
                ):
                    secured = self._receipt_authority.resolve_presentation_read(
                        dependency.evidence_refs,
                        invocation_context=self._context,
                        expected_release=self._registry.release_ref,
                        expected_purpose="operations-review",
                    )
                else:
                    secured = self._receipt_authority.resolve(dependency.evidence_refs)
                arguments[bound_name] = secured.model_dump(mode="json")
                secured_digests.append(secured.receipt.projected_result_digest)
                if self._pending_state_ledger is not None and (
                    coverage := await self._pending_state_ledger.coverage_argument(
                        function_name, dependency.evidence_refs
                    )
                ):
                    arguments["pending_state_coverage"] = coverage
            else:
                arguments[bound_name] = _function_value(dependency.value)
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
        scoped_authority_inputs = {
            "query.resource_health_inventory": (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
            "query.resource_metric_inventory": (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
            "query.resource_state_transitions": (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        }.get(function_name, ())
        exact_document_refs = _exact_document_evidence(
            function_name=function_name,
            value=value,
            expected=invocation_context.document_refs,
        )
        return QueryNodeResult(
            value=value,
            evidence_refs=evidence_refs(dependencies)
            + (f"ontology-function:{receipt.invocation_id}",)
            + exact_document_refs,
            authority=receipt.authority,
            authority_inputs=scoped_authority_inputs,
        )


def _exact_document_evidence(
    *,
    function_name: str,
    value: object,
    expected: tuple[str, ...],
) -> tuple[str, ...]:
    if function_name != "query.governed_documents" or not expected:
        return ()
    if not isinstance(value, QueryTable):
        raise RuntimeError("exact governed document function returned an invalid table")
    citations: list[str] = []
    for row in value.rows:
        citation = row.values.get("document_citation")
        if citation is None:
            continue
        if not isinstance(citation, str) or citation not in expected:
            raise RuntimeError("exact governed document function widened its citation set")
        if citation not in citations:
            citations.append(citation)
    return tuple(citations)


def _function_value(value: object) -> object:
    if isinstance(value, QueryTable):
        return json.loads(value.canonical_json())
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _query_table(value: object) -> QueryTable:
    required = {
        "rows",
        "complete",
        "truncation_reason",
    }
    if (
        not isinstance(value, Mapping)
        or not required <= set(value)
        or set(value) - required - {"numeric_fields", "source_generation", "total_rows"}
    ):
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
    numeric_fields = value.get("numeric_fields", [])
    if not isinstance(numeric_fields, list) or not all(
        isinstance(field, str) for field in numeric_fields
    ):
        raise ValueError("query.table numeric fields MUST be a list of identifiers")
    source_generation = value.get("source_generation")
    if source_generation is not None and not isinstance(source_generation, str):
        raise ValueError("query.table source generation MUST be a string")
    total_rows = value.get("total_rows")
    if total_rows is not None and (isinstance(total_rows, bool) or not isinstance(total_rows, int)):
        raise ValueError("query.table total rows MUST be an integer")
    return QueryTable(
        rows=tuple(rows),
        complete=complete,
        truncation_reason=truncation_reason,
        numeric_fields=tuple(numeric_fields),
        source_generation=source_generation,
        total_rows=total_rows,
    )


__all__ = [
    "FunctionNodeHandler",
    "SecuredObjectSetNodeHandler",
    "SecuredOntologyInstancePathNodeHandler",
    "SecuredRelationshipTraversalNodeHandler",
    "SecuredTypedPathNodeHandler",
]
