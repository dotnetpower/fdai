"""Deterministic verification for exact-manifest ontology query plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)
from jsonschema import Draft202012Validator

from .models import ObjectSelectorKind, ObjectSetDefinition
from .query_manifest import QueryManifest

_TABLE_KINDS = {
    QueryNodeKind.OBJECT_SET,
    QueryNodeKind.UNION,
    QueryNodeKind.INTERSECTION,
    QueryNodeKind.SUBTRACTION,
    QueryNodeKind.ORDER,
    QueryNodeKind.PROJECT,
    QueryNodeKind.AGGREGATE,
}
_SET_KINDS = {
    QueryNodeKind.UNION,
    QueryNodeKind.INTERSECTION,
    QueryNodeKind.SUBTRACTION,
}


class OntologyQueryPlanVerifier:
    """Verify a no-authority plan against one principal-scoped manifest.

    Extension node kinds must provide an explicit JSON Schema. Missing handlers,
    unknown declarations, hidden properties, and raw untyped arguments fail before
    provider or ontology-store I/O.
    """

    def __init__(
        self,
        *,
        available_kinds: Sequence[QueryNodeKind],
        extension_argument_schemas: Mapping[QueryNodeKind, Mapping[str, object]] | None = None,
    ) -> None:
        self._available_kinds = frozenset(available_kinds)
        self._extension_schemas = dict(extension_argument_schemas or {})
        if not set(self._extension_schemas) <= self._available_kinds:
            raise ValueError("query extension schemas MUST name available node kinds")
        if set(self._extension_schemas) & _TABLE_KINDS:
            raise ValueError("built-in query node schemas cannot be replaced")
        for schema in self._extension_schemas.values():
            Draft202012Validator.check_schema(dict(schema))

    def verify(self, plan: OntologyQueryPlan, *, manifest: QueryManifest) -> OntologyQueryPlan:
        """Return the unchanged plan only after complete deterministic validation."""

        if plan.ontology_release_digest != manifest.release_digest:
            raise ValueError("ontology query plan targets a stale release")
        if plan.semantic_catalog_digest != manifest.manifest_digest:
            raise ValueError("ontology query plan targets a stale query manifest")
        if plan.caller_role != manifest.principal_role.value:
            raise PermissionError("ontology query plan caller role does not match manifest")
        if plan.purpose not in manifest.purposes:
            raise PermissionError("ontology query plan purpose is absent from manifest")

        descriptors = {
            (str(item["kind"]), str(item["name"])): item for item in manifest.descriptors
        }
        nodes_by_id: dict[str, OntologyQueryNode] = {}
        for node in plan.nodes:
            if node.kind not in self._available_kinds:
                raise ValueError(f"query node kind {node.kind.value!r} is unavailable")
            self._verify_node(node, nodes_by_id=nodes_by_id, descriptors=descriptors)
            nodes_by_id[node.node_id] = node
        missing_outputs = set(plan.output_node_ids) - nodes_by_id.keys()
        if missing_outputs:
            raise ValueError("query plan output_node_ids MUST reference declared nodes")
        return plan

    def _verify_node(
        self,
        node: OntologyQueryNode,
        *,
        nodes_by_id: Mapping[str, OntologyQueryNode],
        descriptors: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> None:
        arguments = node.arguments
        if node.kind in _TABLE_KINDS and node.output_kind != "query.table":
            raise ValueError(f"{node.kind.value} node output_kind MUST be query.table")
        if node.kind is QueryNodeKind.OBJECT_SET:
            if node.depends_on or set(arguments) != {"definition"}:
                raise ValueError("object_set node requires only definition and no dependencies")
            self._verify_object_set(arguments["definition"], descriptors=descriptors)
            return
        if node.kind in _SET_KINDS:
            if arguments:
                raise ValueError("set operation nodes do not accept arguments")
            expected = 2 if node.kind is QueryNodeKind.SUBTRACTION else None
            self._verify_table_dependencies(
                node,
                nodes_by_id=nodes_by_id,
                minimum=2,
                expected=expected,
            )
            return
        if node.kind is QueryNodeKind.ORDER:
            self._verify_table_dependencies(node, nodes_by_id=nodes_by_id, minimum=1, expected=1)
            _verify_keys(arguments, allowed={"keys", "limit"}, required={"keys"})
            keys = arguments["keys"]
            if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
                raise ValueError("order keys MUST contain 1 to 4 entries")
            for item in keys:
                if not isinstance(item, dict) or set(item) != {"field", "direction"}:
                    raise ValueError("order key MUST contain field and direction")
                _field(item["field"])
                if item["direction"] not in {"ascending", "descending"}:
                    raise ValueError("order direction is unsupported")
            _optional_limit(arguments)
            return
        if node.kind is QueryNodeKind.PROJECT:
            self._verify_table_dependencies(node, nodes_by_id=nodes_by_id, minimum=1, expected=1)
            _verify_keys(arguments, allowed={"fields"}, required={"fields"})
            fields = arguments["fields"]
            if not isinstance(fields, list) or not 1 <= len(fields) <= 64:
                raise ValueError("project fields MUST contain 1 to 64 entries")
            normalized = tuple(_field(item) for item in fields)
            if len(normalized) != len(set(normalized)):
                raise ValueError("project fields MUST be unique")
            return
        if node.kind is QueryNodeKind.AGGREGATE:
            self._verify_table_dependencies(node, nodes_by_id=nodes_by_id, minimum=1, expected=1)
            _verify_keys(
                arguments,
                allowed={"operation", "field", "group_by", "limit"},
                required={"operation"},
            )
            operation = arguments["operation"]
            if operation not in {"count", "sum", "minimum", "maximum", "average"}:
                raise ValueError("aggregate operation is unsupported")
            if operation == "count":
                if "field" in arguments:
                    raise ValueError("count aggregate MUST NOT declare field")
                aggregate_fields: tuple[str, ...] = ()
            elif "field" not in arguments:
                raise ValueError("numeric aggregate requires field")
            else:
                aggregate_fields = (_field(arguments["field"]),)
            group_by = arguments.get("group_by", [])
            if not isinstance(group_by, list) or len(group_by) > 4:
                raise ValueError("aggregate group_by exceeds 4 fields")
            normalized_group = tuple(_field(item) for item in group_by)
            if len(normalized_group) != len(set(normalized_group)):
                raise ValueError("aggregate group_by fields MUST be unique")
            self._verify_dependency_fields(
                node,
                fields=aggregate_fields + normalized_group,
                nodes_by_id=nodes_by_id,
                descriptors=descriptors,
            )
            _optional_limit(arguments)
            return
        if node.kind is QueryNodeKind.FUNCTION:
            self._verify_function(node, arguments=arguments, descriptors=descriptors)
            return
        self._verify_temporal_dependencies(node, nodes_by_id=nodes_by_id)
        schema = self._extension_schemas.get(node.kind)
        if schema is None:
            raise ValueError(f"query node kind {node.kind.value!r} has no verifier schema")
        errors = list(Draft202012Validator(dict(schema)).iter_errors(arguments))
        if errors:
            raise ValueError("query extension arguments violate their registered schema")

    @staticmethod
    def _verify_temporal_dependencies(
        node: OntologyQueryNode,
        *,
        nodes_by_id: Mapping[str, OntologyQueryNode],
    ) -> None:
        if node.kind is QueryNodeKind.TOPOLOGY_AT:
            if node.depends_on or node.output_kind != "topology.graph":
                raise ValueError("topology_at MUST be a topology.graph source")
        elif node.kind is QueryNodeKind.TOPOLOGY_DIFF:
            if len(node.depends_on) != 2 or node.output_kind != "topology.diff":
                raise ValueError("topology_diff MUST join two topology.graph nodes")
            if any(nodes_by_id[item].output_kind != "topology.graph" for item in node.depends_on):
                raise ValueError("topology_diff dependencies MUST output topology.graph")
        elif node.kind is QueryNodeKind.METRIC_SERIES:
            if node.depends_on or node.output_kind != "metric.window":
                raise ValueError("metric_series MUST be a metric.window source")
        elif node.kind is QueryNodeKind.EVIDENCE_JOIN:
            if len(node.depends_on) not in {2, 3} or node.output_kind != "causal.join":
                raise ValueError("evidence_join MUST join two metrics and optional topology")
            first, second, *remaining = node.depends_on
            if nodes_by_id[first].output_kind != "metric.window":
                raise ValueError("evidence_join cause MUST output metric.window")
            if nodes_by_id[second].output_kind != "metric.window":
                raise ValueError("evidence_join effect MUST output metric.window")
            if remaining and nodes_by_id[remaining[0]].output_kind != "topology.diff":
                raise ValueError("evidence_join third dependency MUST output topology.diff")

    def _verify_object_set(
        self,
        raw: object,
        *,
        descriptors: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> None:
        definition = ObjectSetDefinition.model_validate(raw)
        selector_kind = (
            "object" if definition.selector.kind is ObjectSelectorKind.OBJECT_TYPE else "interface"
        )
        descriptor = descriptors.get((selector_kind, definition.selector.name))
        if descriptor is None:
            raise ValueError("object-set selector is absent from the principal manifest")
        readable_properties = set(cast_mapping(descriptor.get("properties")))
        for predicate in definition.predicates:
            if predicate.property not in readable_properties:
                raise PermissionError("object-set predicate property is not readable")
        if definition.traversal is not None:
            for link_type in definition.traversal.link_types:
                if ("link", link_type) not in descriptors:
                    raise ValueError("object-set traversal LinkType is absent from manifest")

    def _verify_function(
        self,
        node: OntologyQueryNode,
        *,
        arguments: Mapping[str, Any],
        descriptors: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> None:
        _verify_keys(
            arguments,
            allowed={"function_name", "arguments", "dependency_arguments"},
            required={"function_name", "arguments", "dependency_arguments"},
        )
        function_name = arguments["function_name"]
        if not isinstance(function_name, str):
            raise ValueError("function_name MUST be a string")
        descriptor = descriptors.get(("function", function_name))
        if descriptor is None:
            raise PermissionError("ontology function is absent from the principal manifest")
        if descriptor.get("function_kind") == "plan":
            raise PermissionError("query plan MUST NOT invoke plan functions")
        static_arguments = arguments["arguments"]
        bindings = arguments["dependency_arguments"]
        if not isinstance(static_arguments, dict) or not isinstance(bindings, dict):
            raise ValueError("function arguments and dependency_arguments MUST be objects")
        if set(bindings) != set(node.depends_on):
            raise ValueError("function dependencies MUST all have argument bindings")
        argument_names = tuple(_field(item) for item in bindings.values())
        if len(argument_names) != len(set(argument_names)):
            raise ValueError("function dependency argument names MUST be unique")
        if set(static_arguments) & set(argument_names):
            raise ValueError("function static and dependency arguments collide")
        input_schema = descriptor.get("input_schema")
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValueError("ontology function input_schema MUST be an object schema")
        properties = input_schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("ontology function input_schema properties MUST be an object")
        supplied_names = set(static_arguments) | set(argument_names)
        required = input_schema.get("required", [])
        if not isinstance(required, list) or not set(required) <= supplied_names:
            raise ValueError("function node omits required arguments")
        if input_schema.get("additionalProperties") is False and not supplied_names <= set(
            properties
        ):
            raise ValueError("function node supplies unknown arguments")
        for name, value in static_arguments.items():
            property_schema = properties.get(name)
            if isinstance(property_schema, dict):
                errors = list(Draft202012Validator(property_schema).iter_errors(value))
                if errors:
                    raise ValueError("function static argument violates input_schema")

    @staticmethod
    def _verify_dependency_fields(
        node: OntologyQueryNode,
        *,
        fields: tuple[str, ...],
        nodes_by_id: Mapping[str, OntologyQueryNode],
        descriptors: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> None:
        dependency = nodes_by_id[node.depends_on[0]]
        available_fields = OntologyQueryPlanVerifier._table_fields(
            dependency,
            nodes_by_id=nodes_by_id,
            descriptors=descriptors,
        )
        if available_fields is None:
            return
        if any(field not in available_fields for field in fields):
            raise ValueError("aggregate field is absent from dependency output schema")

    @staticmethod
    def _table_fields(
        node: OntologyQueryNode,
        *,
        nodes_by_id: Mapping[str, OntologyQueryNode],
        descriptors: Mapping[tuple[str, str], Mapping[str, Any]],
    ) -> frozenset[str] | None:
        if node.kind is QueryNodeKind.PROJECT:
            return frozenset(_field(item) for item in node.arguments["fields"])
        if node.kind is QueryNodeKind.ORDER:
            return OntologyQueryPlanVerifier._table_fields(
                nodes_by_id[node.depends_on[0]],
                nodes_by_id=nodes_by_id,
                descriptors=descriptors,
            )
        if node.kind in _SET_KINDS:
            dependency_fields = tuple(
                OntologyQueryPlanVerifier._table_fields(
                    nodes_by_id[dependency],
                    nodes_by_id=nodes_by_id,
                    descriptors=descriptors,
                )
                for dependency in node.depends_on
            )
            if any(fields is None for fields in dependency_fields):
                return None
            known_fields = tuple(fields for fields in dependency_fields if fields is not None)
            if node.kind is QueryNodeKind.SUBTRACTION:
                return known_fields[0]
            return frozenset.intersection(*known_fields)
        if node.kind is not QueryNodeKind.OBJECT_SET:
            return None
        definition = ObjectSetDefinition.model_validate(node.arguments["definition"])
        selector_kind = (
            "object" if definition.selector.kind is ObjectSelectorKind.OBJECT_TYPE else "interface"
        )
        descriptor = descriptors[(selector_kind, definition.selector.name)]
        readable_properties = cast_mapping(descriptor.get("properties"))
        return frozenset(
            {"id", "object_type"} | {f"properties.{name}" for name in readable_properties}
        )

    @staticmethod
    def _verify_table_dependencies(
        node: OntologyQueryNode,
        *,
        nodes_by_id: Mapping[str, OntologyQueryNode],
        minimum: int,
        expected: int | None,
    ) -> None:
        if len(node.depends_on) < minimum or (
            expected is not None and len(node.depends_on) != expected
        ):
            raise ValueError("query table node has an invalid dependency count")
        if any(nodes_by_id[item].output_kind != "query.table" for item in node.depends_on):
            raise ValueError("query table node dependencies MUST output query.table")


def _verify_keys(
    arguments: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
) -> None:
    if not required <= set(arguments) or not set(arguments) <= allowed:
        raise ValueError("query node arguments do not match the closed schema")


def _field(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("query field MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(not part or not part.replace("_", "").replace("-", "").isalnum() for part in parts):
        raise ValueError("query field MUST be a dot-separated identifier")
    return value


def _optional_limit(arguments: Mapping[str, Any]) -> None:
    value = arguments.get("limit", 1_000)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000:
        raise ValueError("query limit MUST be in [1, 1000]")


def cast_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {str(item): None for item in value}
    raise ValueError("manifest properties descriptor is invalid")


__all__ = ["OntologyQueryPlanVerifier"]
