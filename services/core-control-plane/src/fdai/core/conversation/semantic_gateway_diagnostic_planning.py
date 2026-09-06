"""Compile exact gateway diagnostics from typed fields, never utterance keywords."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.gateway_diagnostics import (
    GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
    GATEWAY_DIAGNOSTIC_OUTPUT_SHAPE,
    MAX_GATEWAY_BACKENDS,
    MAX_REQUESTED_BACKEND_CANDIDATES,
    GatewayBackendFilter,
    GatewayDiagnosticWindows,
    gateway_diagnostic_windows,
)
from fdai.core.ontology_platform.resource_configuration_queries import (
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
)


def compile_gateway_diagnostic_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
    include_configuration: bool = True,
) -> OntologyQueryPlan | None:
    """Require an exact Resource identity and an optional exact Backend identity.

    The default comparison is two adjacent 15-minute windows. Explicit windows
    use four boundaries, or ``window_seconds`` selects equal adjacent windows.
    Configuration, when bound, is independent gateway/backend evidence, not causation.
    Backend.id/name/model_name are filters, not inferred relationships or authority.
    """
    if (
        frame.output_shape != GATEWAY_DIAGNOSTIC_OUTPUT_SHAPE
        or frame.operation
        not in {
            SemanticOperation.SELECT,
            SemanticOperation.COMPARE,
            SemanticOperation.EXPLAIN_CHANGE,
        }
        or frame.unresolved_terms
        or frame.investigation_intent_digest is not None
        or frame.measure_concepts
        or purpose != "operations-review"
        or evaluation_time.tzinfo is None
    ):
        return None
    functions = {
        item.get("name") for item in manifest.descriptors if item.get("kind") == "function"
    }
    if GATEWAY_DIAGNOSTIC_FUNCTION_NAME not in functions or not any(
        item.get("kind") == "link"
        and item.get("name") == "routes_to"
        and item.get("from_type") == item.get("to_type") == "Resource"
        for item in manifest.descriptors
    ):
        return None
    constraints = _target_predicate(frame.subject_constraints, manifest.descriptors)
    if constraints is None:
        return None
    predicate, requested_filter = constraints
    try:
        windows = gateway_diagnostic_windows(
            frame.temporal_scope,
            evaluation_time=evaluation_time,
        )
    except (ValueError, TypeError, OverflowError):
        return None
    known_at = evaluation_time.astimezone(UTC)
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(predicate,),
        as_of=known_at,
        purpose=purpose,
        limit=2,
        include_relationships=False,
    )
    root_id, backend_id, diagnostic_id = "gateway-target", "gateway-backends", "gateway-diagnostics"
    nodes = [
        _node(
            root_id,
            QueryNodeKind.OBJECT_SET,
            {"definition": definition.model_dump(mode="json")},
        ),
        _node(
            backend_id,
            QueryNodeKind.TYPED_PATH,
            {
                "steps": [
                    {
                        "link_type": "routes_to",
                        "direction": "outgoing",
                        "max_hops": 1,
                        "selector": {"kind": "object_type", "name": "Resource"},
                    }
                ],
                "as_of": known_at.isoformat(),
                "purpose": purpose,
                "limit": MAX_GATEWAY_BACKENDS + 2,
            },
            depends_on=(root_id,),
        ),
    ]
    arguments: dict[str, object] = dict(windows.arguments())
    bindings = {root_id: "query_result", backend_id: "backend_query_result"}
    if requested_filter is not None:
        requested_definition = _requested_backend_definition(
            requested_filter,
            manifest.descriptors,
            known_at=known_at,
            purpose=purpose,
        )
        if requested_definition is None:
            return None
        requested_id = "gateway-requested-backend"
        nodes.append(
            _node(
                requested_id,
                QueryNodeKind.OBJECT_SET,
                {"definition": requested_definition.model_dump(mode="json")},
            )
        )
        arguments["requested_backend_filter"] = requested_filter.arguments()
        bindings[requested_id] = "requested_backend_query_result"
    nodes.append(
        _function(
            diagnostic_id,
            GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
            arguments,
            bindings,
        )
    )
    outputs = [diagnostic_id]
    if (
        include_configuration
        and {
            RESOURCE_CONFIGURATION_FUNCTION_NAME,
            RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
        }
        <= functions
    ):
        configuration_scopes = [(root_id, "gateway")]
        # The diagnostic filters issued candidates internally. Do not expose their
        # unfiltered configuration as if it belonged to the selected backend.
        if requested_filter is None:
            configuration_scopes.append((backend_id, "backend"))
        for scope_id, prefix in configuration_scopes:
            configuration_nodes = _configuration_nodes(scope_id, windows, known_at, prefix=prefix)
            nodes.extend(configuration_nodes)
            outputs.append(configuration_nodes[-1].node_id)
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": outputs,
        "execution_authority": False,
    }
    return verifier.verify(
        OntologyQueryPlan(
            ontology_release_digest=manifest.release_digest,
            semantic_catalog_digest=manifest.manifest_digest,
            problem_frame_digest=frame.frame_digest,
            purpose=purpose,
            caller_role=manifest.principal_role.value,
            nodes=tuple(nodes),
            output_node_ids=tuple(outputs),
            plan_digest=content_digest(body),
        ),
        manifest=manifest,
    )


def _target_predicate(
    constraints: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[ObjectPredicate, GatewayBackendFilter | None] | None:
    if len(constraints) not in {2, 3} or constraints.count("Resource") != 1:
        return None
    roots = [value for value in constraints if value.startswith(("Resource.id=", "Resource.name="))]
    backend_constraints = [value for value in constraints if value.startswith("Backend.")]
    if len(roots) != 1 or len(backend_constraints) != len(constraints) - 2:
        return None
    requested_filter = None
    if backend_constraints:
        field, separator, value = backend_constraints[0].partition("=")
        if not separator:
            return None
        try:
            requested_filter = GatewayBackendFilter(field.removeprefix("Backend."), value)
        except ValueError:
            return None
    constraint = roots[0]
    field, separator, value = constraint.partition("=")
    if (
        field not in {"Resource.id", "Resource.name"}
        or not separator
        or not value.strip()
        or value != value.strip()
        or len(value) > 512
    ):
        return None
    name = field.removeprefix("Resource.")
    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == "Resource"
        ),
        None,
    )
    properties = resource.get("properties") if resource else None
    if not isinstance(properties, Mapping) or not {name, "type"} <= properties.keys():
        return None
    return (
        ObjectPredicate(property=name, operator=ObjectPredicateOperator.EQUALS, equals=value),
        requested_filter,
    )


def _requested_backend_definition(
    requested: GatewayBackendFilter,
    descriptors: tuple[dict[str, Any], ...],
    *,
    known_at: datetime,
    purpose: str,
) -> ObjectSetDefinition | None:
    field = "type" if requested.field == "model_name" else requested.field
    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == "Resource"
        ),
        None,
    )
    properties = resource.get("properties") if resource else None
    if not isinstance(properties, Mapping) or field not in properties:
        return None
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=field,
                operator=ObjectPredicateOperator.EQUALS,
                equals="llm-model-deployment"
                if requested.field == "model_name"
                else requested.value,
            ),
        ),
        as_of=known_at,
        purpose=purpose,
        include_relationships=False,
        limit=MAX_REQUESTED_BACKEND_CANDIDATES + 1 if requested.field == "model_name" else 2,
    )


def _configuration_nodes(
    root_id: str,
    windows: GatewayDiagnosticWindows,
    known_at: datetime,
    *,
    prefix: str,
) -> tuple[OntologyQueryNode, ...]:
    before_id, after_id = f"{prefix}-config-before", f"{prefix}-config-after"
    return (
        *(
            _function(
                node_id,
                RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
                {"as_of": as_of.isoformat(), "known_at": known_at.isoformat()},
                {root_id: "query_result"},
                output_kind="resource.configuration_snapshot",
            )
            for node_id, as_of in (
                (before_id, windows.baseline_end),
                (after_id, windows.current_end),
            )
        ),
        _function(
            f"{prefix}-configuration-changes",
            RESOURCE_CONFIGURATION_FUNCTION_NAME,
            {
                "before_as_of": windows.baseline_end.isoformat(),
                "after_as_of": windows.current_end.isoformat(),
                "known_at": known_at.isoformat(),
            },
            {root_id: "query_result", before_id: "before_snapshot", after_id: "after_snapshot"},
        ),
    )


def _node(
    node_id: str,
    kind: QueryNodeKind,
    arguments: Mapping[str, object],
    *,
    depends_on: tuple[str, ...] = (),
    output_kind: str = "query.table",
) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=node_id,
        kind=kind,
        depends_on=depends_on,
        arguments_json=canonical_json(dict(arguments)),
        output_kind=output_kind,
    )


def _function(
    node_id: str,
    name: str,
    arguments: Mapping[str, object],
    bindings: Mapping[str, str],
    *,
    output_kind: str = "query.table",
) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.FUNCTION,
        {
            "function_name": name,
            "arguments": dict(arguments),
            "dependency_arguments": dict(bindings),
        },
        depends_on=tuple(bindings),
        output_kind=output_kind,
    )


__all__ = ["compile_gateway_diagnostic_plan"]
