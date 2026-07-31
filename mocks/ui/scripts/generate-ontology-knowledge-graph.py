"""Generate the static full ontology knowledge-graph snapshot for the UI mock."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from ontology_knowledge_layout import apply_centrality_layout

from fdai.agents import PANTHEON_SPECS
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"
MOCK_OUTPUT = REPO_ROOT / "mocks" / "ui" / "assets" / "ontology-knowledge-data.js"
CONSOLE_OUTPUT = REPO_ROOT / "console" / "src" / "generated" / "ontology-knowledge-graph.json"


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
        "schemaVersion": "1.1.0",
        "generatedFrom": "rule-catalog + PANTHEON_SPECS",
        "nodes": nodes,
        "edges": edges,
    }
    apply_centrality_layout(graph)
    return graph


def main() -> None:
    graph = build()
    payload = json.dumps(graph, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    MOCK_OUTPUT.write_text(
        "/* Generated by mocks/ui/scripts/generate-ontology-knowledge-graph.py. */\n"
        f"window.FDAI_ONTOLOGY_KNOWLEDGE_GRAPH = Object.freeze({payload});\n",
        encoding="utf-8",
    )
    CONSOLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    CONSOLE_OUTPUT.write_text(f"{payload}\n", encoding="utf-8")
    print(f"wrote {MOCK_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"wrote {CONSOLE_OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
