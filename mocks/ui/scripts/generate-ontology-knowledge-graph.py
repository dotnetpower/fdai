"""Generate the static full ontology knowledge-graph snapshot for the UI mock."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml

from fdai.agents import PANTHEON_SPECS
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"
OUTPUT = REPO_ROOT / "mocks" / "ui" / "assets" / "ontology-knowledge-data.js"


def node(identifier: str, label: str, kind: str, group: str, detail: str) -> dict[str, Any]:
    return {"id": identifier, "label": label, "kind": kind, "group": group, "detail": detail}


def edge(
    identifier: str,
    source: str,
    target: str,
    kind: str,
    label: str,
) -> dict[str, Any]:
    return {"id": identifier, "source": source, "target": target, "kind": kind, "label": label}


def load_yaml_files(root: Path) -> list[dict[str, Any]]:
    return [
        yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.yaml"))
    ]


def build() -> dict[str, Any]:
    catalog = load_ontology_catalog(
        CATALOG_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=CATALOG_ROOT / "probes",
    )
    rules = load_yaml_files(CATALOG_ROOT / "catalog")
    workflows = load_yaml_files(CATALOG_ROOT / "workflows")
    resource_types = yaml.safe_load(
        (CATALOG_ROOT / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
    )["types"]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    object_names = {item.name for item in catalog.object_types}
    action_names = {item.name for item in catalog.action_types}

    for item in catalog.object_types:
        nodes.append(
            node(
                f"ot:{item.name}",
                item.name,
                "object_type",
                "ObjectTypes",
                item.description or "Registered ObjectType declaration.",
            )
        )
    for item in catalog.link_types:
        edges.append(
            edge(
                f"link:{item.name}",
                f"ot:{item.from_type}",
                f"ot:{item.to_type}",
                "link_type",
                item.name,
            )
        )

    for item in resource_types:
        identifier = str(item["id"])
        nodes.append(
            node(
                f"rt:{identifier}",
                identifier,
                "resource_type",
                "ResourceTypes",
                str(item["description"]),
            )
        )
        edges.append(
            edge(
                f"instance:rt:{identifier}",
                f"rt:{identifier}",
                "ot:ResourceType",
                "instance_of",
                "instance_of",
            )
        )

    signal_values = sorted({value for rule in rules for value in rule["triggered_by"]})
    property_values = sorted({value for rule in rules for value in rule["evaluates"]})
    for value in signal_values:
        nodes.append(
            node(
                f"signal:{value}",
                value,
                "signal_type",
                "Dispatch concepts",
                "Rule trigger selector.",
            )
        )
        edges.append(
            edge(
                f"instance:signal:{value}",
                f"signal:{value}",
                "ot:SignalType",
                "instance_of",
                "instance_of",
            )
        )
    for value in property_values:
        nodes.append(
            node(
                f"property:{value}",
                value,
                "property",
                "Dispatch concepts",
                "Rule evaluation selector.",
            )
        )
        edges.append(
            edge(
                f"instance:property:{value}",
                f"property:{value}",
                "ot:Property",
                "instance_of",
                "instance_of",
            )
        )

    for rule in rules:
        rule_id = str(rule["id"])
        nodes.append(
            node(
                f"rule:{rule_id}",
                rule_id,
                "rule",
                "Rules",
                f"{rule['severity']} {rule['category']} rule from {rule['source']}.",
            )
        )
        edges.append(
            edge(
                f"instance:rule:{rule_id}",
                f"rule:{rule_id}",
                "ot:Rule",
                "instance_of",
                "instance_of",
            )
        )
        for resource_type in rule["applies_to"]:
            edges.append(
                edge(
                    f"rule:{rule_id}:applies:{resource_type}",
                    f"rule:{rule_id}",
                    f"rt:{resource_type}",
                    "rule_dispatch",
                    "applies_to",
                )
            )
        for signal_type in rule["triggered_by"]:
            edges.append(
                edge(
                    f"rule:{rule_id}:trigger:{signal_type}",
                    f"rule:{rule_id}",
                    f"signal:{signal_type}",
                    "rule_dispatch",
                    "triggered_by",
                )
            )
        for property_name in rule["evaluates"]:
            edges.append(
                edge(
                    f"rule:{rule_id}:evaluates:{property_name}",
                    f"rule:{rule_id}",
                    f"property:{property_name}",
                    "rule_dispatch",
                    "evaluates",
                )
            )
        edges.append(
            edge(
                f"rule:{rule_id}:remediates",
                f"rule:{rule_id}",
                f"at:{rule['remediates']}",
                "rule_dispatch",
                "remediates",
            )
        )

    for item in catalog.action_types:
        nodes.append(
            node(
                f"at:{item.name}",
                item.name,
                "action_type",
                "ActionTypes",
                f"{item.category.value} / {item.operation.value} / {item.execution_path.value}.",
            )
        )
        edges.append(
            edge(
                f"instance:at:{item.name}",
                f"at:{item.name}",
                "ot:ActionType",
                "instance_of",
                "instance_of",
            )
        )

    for workflow in workflows:
        name = str(workflow["name"])
        nodes.append(
            node(f"wf:{name}", name, "workflow", "Workflows", str(workflow["description"]))
        )
        edges.append(
            edge(
                f"instance:wf:{name}",
                f"wf:{name}",
                "ot:WorkflowDefinition",
                "instance_of",
                "instance_of",
            )
        )
        for step in workflow.get("steps", []):
            action_ref = step.get("action_type_ref")
            if action_ref:
                edges.append(
                    edge(
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
                    edge(
                        f"wf:{name}:compensates:{step['id']}",
                        f"wf:{name}",
                        f"at:{compensation}",
                        "workflow",
                        "compensates",
                    )
                )

    for spec in PANTHEON_SPECS:
        nodes.append(
            node(f"agent:{spec.name}", spec.name, "agent", "Agents", f"{spec.layer.value} agent.")
        )
        edges.append(
            edge(
                f"instance:agent:{spec.name}",
                f"agent:{spec.name}",
                "ot:Agent",
                "instance_of",
                "instance_of",
            )
        )
        if spec.reports_to:
            edges.append(
                edge(
                    f"agent:{spec.name}:reports",
                    f"agent:{spec.name}",
                    f"agent:{spec.reports_to}",
                    "agent",
                    "reports_to",
                )
            )
        for owned in sorted(set(spec.owns) & object_names):
            edges.append(
                edge(
                    f"agent:{spec.name}:owns:{owned}",
                    f"agent:{spec.name}",
                    f"ot:{owned}",
                    "agent",
                    "owns_type",
                )
            )
        for action_ref in sorted((set(spec.executes) | set(spec.initiates)) & action_names):
            edges.append(
                edge(
                    f"agent:{spec.name}:action:{action_ref}",
                    f"agent:{spec.name}",
                    f"at:{action_ref}",
                    "agent",
                    "authorized_for",
                )
            )

    graph = {
        "schemaVersion": "1.0.0",
        "generatedFrom": "rule-catalog + PANTHEON_SPECS",
        "nodes": nodes,
        "edges": edges,
    }
    apply_centrality_layout(graph)
    return graph


def apply_centrality_layout(graph: dict[str, Any]) -> None:
    """Place high-degree nodes centrally, then relax edges deterministically."""

    nodes: list[dict[str, Any]] = graph["nodes"]
    edges: list[dict[str, Any]] = graph["edges"]
    index = {item["id"]: position for position, item in enumerate(nodes)}
    degree = [0] * len(nodes)
    indexed_edges: list[tuple[int, int]] = []
    for item in edges:
        source = index[item["source"]]
        target = index[item["target"]]
        degree[source] += 1
        degree[target] += 1
        indexed_edges.append((source, target))

    order = sorted(range(len(nodes)), key=lambda item: (-degree[item], nodes[item]["id"]))
    rank = {node_index: position for position, node_index in enumerate(order)}
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    x = [0.0] * len(nodes)
    y = [0.0] * len(nodes)
    target_x = [0.0] * len(nodes)
    target_y = [0.0] * len(nodes)
    for node_index in range(len(nodes)):
        node_rank = rank[node_index]
        radius = 18.0 * math.sqrt(node_rank)
        angle = node_rank * golden_angle
        target_x[node_index] = radius * math.cos(angle)
        target_y[node_index] = radius * math.sin(angle) * 0.72
        x[node_index] = target_x[node_index]
        y[node_index] = target_y[node_index]

    velocity_x = [0.0] * len(nodes)
    velocity_y = [0.0] * len(nodes)
    for iteration in range(220):
        force_x = [0.0] * len(nodes)
        force_y = [0.0] * len(nodes)
        for left in range(len(nodes)):
            for right in range(left + 1, len(nodes)):
                delta_x = x[left] - x[right]
                delta_y = y[left] - y[right]
                distance_sq = max(36.0, delta_x * delta_x + delta_y * delta_y)
                distance = math.sqrt(distance_sq)
                magnitude = 520.0 / distance_sq
                push_x = delta_x / distance * magnitude
                push_y = delta_y / distance * magnitude
                force_x[left] += push_x
                force_y[left] += push_y
                force_x[right] -= push_x
                force_y[right] -= push_y
        for source, target in indexed_edges:
            delta_x = x[target] - x[source]
            delta_y = y[target] - y[source]
            distance = max(1.0, math.hypot(delta_x, delta_y))
            desired = 42.0 + 7.0 * math.log1p(max(degree[source], degree[target]))
            magnitude = (distance - desired) * 0.006
            pull_x = delta_x / distance * magnitude
            pull_y = delta_y / distance * magnitude
            force_x[source] += pull_x
            force_y[source] += pull_y
            force_x[target] -= pull_x
            force_y[target] -= pull_y
        temperature = 0.28 * (1.0 - iteration / 260.0)
        for node_index in range(len(nodes)):
            anchor = 0.015 + min(degree[node_index], 70) * 0.00015
            force_x[node_index] += (target_x[node_index] - x[node_index]) * anchor
            force_y[node_index] += (target_y[node_index] - y[node_index]) * anchor
            velocity_x[node_index] = (velocity_x[node_index] + force_x[node_index]) * 0.78
            velocity_y[node_index] = (velocity_y[node_index] + force_y[node_index]) * 0.78
            x[node_index] += max(-8.0, min(8.0, velocity_x[node_index])) * temperature
            y[node_index] += max(-8.0, min(8.0, velocity_y[node_index])) * temperature

    min_x, max_x = min(x), max(x)
    min_y, max_y = min(y), max(y)
    scale = min(1900.0 / max(1.0, max_x - min_x), 1120.0 / max(1.0, max_y - min_y))
    for node_index, item in enumerate(nodes):
        item["degree"] = degree[node_index]
        item["x"] = round((x[node_index] - min_x) * scale + 110.0, 2)
        item["y"] = round((y[node_index] - min_y) * scale + 90.0, 2)


def main() -> None:
    payload = json.dumps(build(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    OUTPUT.write_text(
        "/* Generated by mocks/ui/scripts/generate-ontology-knowledge-graph.py. */\n"
        f"window.FDAI_ONTOLOGY_KNOWLEDGE_GRAPH = Object.freeze({payload});\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
