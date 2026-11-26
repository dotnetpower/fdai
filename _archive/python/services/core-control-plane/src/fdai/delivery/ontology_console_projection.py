"""Build read-only Console projections from one reviewed ontology release."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog

from .ontology_topology_layout import apply_centrality_layout

_SEMANTIC_BANDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "operating_scope",
        "Operating scope",
        ("BusinessCapability", "BusinessService", "Workload", "Resource", "Environment"),
    ),
    (
        "operating_intent",
        "Operating intent",
        (
            "ServiceObjective",
            "RecoveryObjective",
            "CostObjective",
            "ArchitectureConstraint",
            "Ownership",
            "ChangeWindow",
        ),
    ),
    (
        "operating_reality",
        "Operating reality",
        ("Signal", "Finding", "Incident", "Observation", "Change", "Forecast", "Experiment"),
    ),
    (
        "decision_and_learning",
        "Decision and learning",
        (
            "DecisionCase",
            "ActionOption",
            "ExpectedEffect",
            "ActionRun",
            "ObservedOutcome",
            "Pattern",
        ),
    ),
)


def semantic_model_profile(ontology: OntologyCatalog) -> dict[str, object]:
    """Project the reviewed operating layers without creating declaration kinds."""

    available = {object_type.name for object_type in ontology.object_types}
    bands = [
        {
            "id": identifier,
            "label": label,
            "object_types": [name for name in object_types if name in available],
        }
        for identifier, label, object_types in _SEMANTIC_BANDS
    ]
    return {
        "schema_version": "1.0.0",
        "bands": bands,
        "lenses": ["object", "relationship", "state", "context", "action"],
        "mutation_authority": False,
    }


def build_catalog_topology(
    *,
    ontology: OntologyCatalog,
    resource_types: Sequence[Mapping[str, object]],
    rules: Sequence[Mapping[str, object]],
    workflows: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Build one deterministic reference topology pinned to the ontology release."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    object_names = {object_type.name for object_type in ontology.object_types}
    action_names = {action_type.name for action_type in ontology.action_types}

    for object_type in ontology.object_types:
        nodes.append(
            _node(
                f"ot:{object_type.name}",
                object_type.name,
                "object_type",
                "ObjectTypes",
                object_type.description or "Registered ObjectType declaration.",
            )
        )
    for link_type in ontology.link_types:
        edges.append(
            _edge(
                f"link:{link_type.name}",
                f"ot:{link_type.from_type}",
                f"ot:{link_type.to_type}",
                "link_type",
                link_type.name,
            )
        )

    for interface_type in ontology.interface_types:
        nodes.append(
            _node(
                f"it:{interface_type.name}",
                interface_type.name,
                "interface_type",
                "InterfaceTypes",
                interface_type.description or "Registered InterfaceType declaration.",
            )
        )
        if "InterfaceType" in object_names:
            edges.append(
                _edge(
                    f"instance:it:{interface_type.name}",
                    f"it:{interface_type.name}",
                    "ot:InterfaceType",
                    "instance_of",
                    "instance_of",
                )
            )
        for extended in interface_type.extends:
            edges.append(
                _edge(
                    f"interface:{interface_type.name}:extends:{extended}",
                    f"it:{interface_type.name}",
                    f"it:{extended}",
                    "interface",
                    "extends",
                )
            )
    for implementation in ontology.interface_implementations:
        for interface_name in implementation.interfaces:
            edges.append(
                _edge(
                    f"interface:{implementation.object_type}:implements:{interface_name}",
                    f"ot:{implementation.object_type}",
                    f"it:{interface_name}",
                    "interface",
                    "implements",
                )
            )

    for function_type in ontology.function_types:
        nodes.append(
            _node(
                f"ft:{function_type.name}",
                function_type.name,
                "function_type",
                "FunctionTypes",
                f"{function_type.kind.value} function / {function_type.execution_class.value}.",
            )
        )

    for resource_type_record in resource_types:
        identifier = str(resource_type_record["id"])
        nodes.append(
            _node(
                f"rt:{identifier}",
                identifier,
                "resource_type",
                "ResourceTypes",
                str(resource_type_record["description"]),
            )
        )
        edges.append(
            _edge(
                f"instance:rt:{identifier}",
                f"rt:{identifier}",
                "ot:ResourceType",
                "instance_of",
                "instance_of",
            )
        )

    signal_values = sorted(
        {value for rule_record in rules for value in _string_sequence(rule_record, "triggered_by")}
    )
    property_values = sorted(
        {value for rule_record in rules for value in _string_sequence(rule_record, "evaluates")}
    )
    for value in signal_values:
        nodes.append(
            _node(
                f"signal:{value}",
                value,
                "signal_type",
                "Dispatch concepts",
                "Rule trigger selector.",
            )
        )
        edges.append(
            _edge(
                f"instance:signal:{value}",
                f"signal:{value}",
                "ot:SignalType",
                "instance_of",
                "instance_of",
            )
        )
    for value in property_values:
        nodes.append(
            _node(
                f"property:{value}",
                value,
                "property",
                "Dispatch concepts",
                "Rule evaluation selector.",
            )
        )
        edges.append(
            _edge(
                f"instance:property:{value}",
                f"property:{value}",
                "ot:Property",
                "instance_of",
                "instance_of",
            )
        )

    for rule_record in rules:
        rule_id = str(rule_record["id"])
        nodes.append(
            _node(
                f"rule:{rule_id}",
                rule_id,
                "rule",
                "Rules",
                f"{rule_record['severity']} {rule_record['category']} rule from "
                f"{rule_record['source']}.",
            )
        )
        edges.append(
            _edge(
                f"instance:rule:{rule_id}",
                f"rule:{rule_id}",
                "ot:Rule",
                "instance_of",
                "instance_of",
            )
        )
        for resource_type_name in _string_sequence(rule_record, "applies_to"):
            edges.append(
                _edge(
                    f"rule:{rule_id}:applies:{resource_type_name}",
                    f"rule:{rule_id}",
                    f"rt:{resource_type_name}",
                    "rule_dispatch",
                    "applies_to",
                )
            )
        for signal_type_name in _string_sequence(rule_record, "triggered_by"):
            edges.append(
                _edge(
                    f"rule:{rule_id}:trigger:{signal_type_name}",
                    f"rule:{rule_id}",
                    f"signal:{signal_type_name}",
                    "rule_dispatch",
                    "triggered_by",
                )
            )
        for property_name in _string_sequence(rule_record, "evaluates"):
            edges.append(
                _edge(
                    f"rule:{rule_id}:evaluates:{property_name}",
                    f"rule:{rule_id}",
                    f"property:{property_name}",
                    "rule_dispatch",
                    "evaluates",
                )
            )
        edges.append(
            _edge(
                f"rule:{rule_id}:remediates",
                f"rule:{rule_id}",
                f"at:{rule_record['remediates']}",
                "rule_dispatch",
                "remediates",
            )
        )

    for action_type in ontology.action_types:
        category = action_type.category.value if action_type.category is not None else "unspecified"
        execution_path = (
            action_type.execution_path.value
            if action_type.execution_path is not None
            else "unspecified"
        )
        nodes.append(
            _node(
                f"at:{action_type.name}",
                action_type.name,
                "action_type",
                "ActionTypes",
                f"{category} / {action_type.operation.value} / {execution_path}.",
            )
        )
        edges.append(
            _edge(
                f"instance:at:{action_type.name}",
                f"at:{action_type.name}",
                "ot:ActionType",
                "instance_of",
                "instance_of",
            )
        )

    for workflow_record in workflows:
        name = str(workflow_record["name"])
        nodes.append(
            _node(
                f"wf:{name}",
                name,
                "workflow",
                "Workflows",
                str(workflow_record["description"]),
            )
        )
        edges.append(
            _edge(
                f"instance:wf:{name}",
                f"wf:{name}",
                "ot:WorkflowDefinition",
                "instance_of",
                "instance_of",
            )
        )
        for step in _mapping_sequence(workflow_record, "steps"):
            action_ref = step.get("action_type_ref")
            if action_ref:
                edges.append(
                    _edge(
                        f"wf:{name}:step:{step['id']}",
                        f"wf:{name}",
                        f"at:{action_ref}",
                        "workflow",
                        "invokes",
                    )
                )
            compensation = step.get("compensated_by")
            if compensation:
                edges.append(
                    _edge(
                        f"wf:{name}:compensates:{step['id']}",
                        f"wf:{name}",
                        f"at:{compensation}",
                        "workflow",
                        "compensates",
                    )
                )

    for agent_record in agents:
        name = str(agent_record["name"])
        nodes.append(
            _node(
                f"agent:{name}",
                name,
                "agent",
                "Agents",
                f"{agent_record['layer']} agent.",
            )
        )
        edges.append(
            _edge(
                f"instance:agent:{name}",
                f"agent:{name}",
                "ot:Agent",
                "instance_of",
                "instance_of",
            )
        )
        reports_to = agent_record.get("reports_to")
        if reports_to:
            edges.append(
                _edge(
                    f"agent:{name}:reports",
                    f"agent:{name}",
                    f"agent:{reports_to}",
                    "agent",
                    "reports_to",
                )
            )
        for owned in sorted(set(_string_sequence(agent_record, "owns")) & object_names):
            edges.append(
                _edge(
                    f"agent:{name}:owns:{owned}",
                    f"agent:{name}",
                    f"ot:{owned}",
                    "agent",
                    "owns_type",
                )
            )
        for action_ref in sorted(set(_string_sequence(agent_record, "actions")) & action_names):
            edges.append(
                _edge(
                    f"agent:{name}:action:{action_ref}",
                    f"agent:{name}",
                    f"at:{action_ref}",
                    "agent",
                    "authorized_for",
                )
            )

    for function_type in ontology.function_types:
        for agent_name in sorted(function_type.allowed_agents):
            edges.append(
                _edge(
                    f"function:{function_type.name}:agent:{agent_name}",
                    f"agent:{agent_name}",
                    f"ft:{function_type.name}",
                    "agent",
                    "may_invoke",
                )
            )

    graph: dict[str, Any] = {
        "schemaVersion": "2.0.0",
        "generatedFrom": "operator ontology projection",
        "ontologyReleaseDigest": ontology.build_release().digest,
        "mutationAuthority": False,
        "nodes": nodes,
        "edges": edges,
    }
    apply_centrality_layout(graph)
    return graph


def _node(identifier: str, label: str, kind: str, group: str, detail: str) -> dict[str, Any]:
    return {"id": identifier, "label": label, "kind": kind, "group": group, "detail": detail}


def _edge(
    identifier: str,
    source: str,
    target: str,
    kind: str,
    label: str,
) -> dict[str, Any]:
    return {"id": identifier, "source": source, "target": target, "kind": kind, "label": label}


def _string_sequence(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = record.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"ontology topology {key} MUST be a sequence")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"ontology topology {key} values MUST be non-empty strings")
    return tuple(value)


def _mapping_sequence(
    record: Mapping[str, object],
    key: str,
) -> tuple[Mapping[str, object], ...]:
    value = record.get(key, ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"ontology topology {key} MUST be a sequence")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"ontology topology {key} values MUST be mappings")
    return tuple(value)


__all__ = ["build_catalog_topology", "semantic_model_profile"]
