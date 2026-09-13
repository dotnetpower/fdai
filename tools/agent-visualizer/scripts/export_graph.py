"""Export source-backed agent function topology; never execute application code or contact Azure."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path

from source_events import arg_metadata, event_metadata
from source_index import SourceIndex


def pantheon_records(index: SourceIndex) -> list[dict]:
    tree = index.modules["fdai.agents._framework.pantheon"]
    records = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id != "AgentSpec"
        ):
            continue
        fields = {keyword.arg: keyword.value for keyword in node.keywords}
        records.append(
            {
                "id": ast.literal_eval(fields["name"]),
                "files": list(ast.literal_eval(fields["owns_code_paths"])),
                "subscribes": list(ast.literal_eval(fields["subscribes"])),
                "owns": list(ast.literal_eval(fields["owns"])),
                "declaration_line": node.lineno,
            }
        )
    if len(records) != 15:
        raise ValueError("Expected the fixed 15-agent pantheon.")
    return records


def export(root: Path) -> dict:
    """Include every owned agent definition and all conservatively resolved transitive callees."""
    files = sorted(
        [
            *root.glob("services/*/src/**/*.py"),
            *root.glob("packages/*/src/**/*.py"),
        ]
    )
    index = SourceIndex(root, files)
    records = pantheon_records(index)
    all_edges, unresolved = index.calls()
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in all_edges:
        outgoing[edge["source"]].append(edge["target"])
    owners: dict[str, set[str]] = defaultdict(set)
    direct: dict[str, set[str]] = defaultdict(set)
    for record in records:
        seeds = [
            definition.identifier
            for definition in index.functions.values()
            if definition.path in record["files"]
        ]
        handler = index.class_method(
            f"fdai.agents.{record['id'].lower()}.{record['id']}", "on_typed_message"
        )
        record["handler"] = handler
        if handler:
            seeds.append(handler)
        queue = deque(seeds)
        visited = set()
        for identifier in seeds:
            if index.functions[identifier].path in record["files"]:
                direct[identifier].add(record["id"])
        while queue:
            identifier = queue.popleft()
            if identifier in visited:
                continue
            visited.add(identifier)
            owners[identifier].add(record["id"])
            queue.extend(outgoing[identifier])
    # Azure provider entry points are real definitions but are not assigned agent ownership.
    azure_functions = [
        definition.identifier
        for definition in index.functions.values()
        if definition.module
        in {
            "fdai.delivery.azure.arg_query",
            "fdai.delivery.azure.arg_transport",
            "fdai.delivery.azure.arg_resource_changes",
            "fdai.delivery.azure.inventory",
            "fdai.delivery.inventory_change_acceleration",
        }
    ]
    pending = deque(azure_functions)
    azure_reachable = set()
    while pending:
        identifier = pending.popleft()
        if identifier in azure_reachable:
            continue
        azure_reachable.add(identifier)
        owners.setdefault(identifier, set())
        pending.extend(outgoing[identifier])
    topics = event_metadata(index, records, owners)
    functions = []
    for identifier in sorted(owners):
        definition = index.functions[identifier]
        functions.append(
            {
                "id": identifier,
                "name": definition.node.name,
                "file": definition.path,
                "line": definition.node.lineno,
                "end_line": definition.node.end_lineno,
                "async": isinstance(definition.node, ast.AsyncFunctionDef),
                "owners": sorted(owners[identifier]),
                "direct_owners": sorted(direct[identifier]),
                "unresolved": unresolved.get(identifier, []),
            }
        )
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return {
        "schema_version": 1,
        "source": "python-ast",
        "input_digest": digest.hexdigest(),
        "scope": (
            "Agent-owned Python definitions, resolved transitive callees, "
            "and Azure Resource Graph provider definitions."
        ),
        "limitations": [
            "Static definition references, not observed execution or complete dynamic dispatch.",
            "Declared receiver types do not prove injected runtime implementations.",
            "Unknown receivers, builtins and external SDK calls remain unresolved.",
            "Multiple possible inherited implementations are not guessed.",
        ],
        "agents": records,
        "functions": functions,
        "calls": [
            edge for edge in all_edges if edge["source"] in owners and edge["target"] in owners
        ],
        "azure_functions": azure_functions,
        "topics": topics,
        "arg": arg_metadata(index),
        "subscription_scope": (
            "Canonical agent subscriptions only. Optional worker commands "
            "and non-agent consumer groups are not depicted."
        ),
        "indexed_files": len(files),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src/generated/code-graph.json",
    )
    args = parser.parse_args()
    graph = export(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        f"Source graph: {len(graph['functions'])} Python functions, "
        f"{len(graph['calls'])} resolved calls, {graph['indexed_files']} files."
    )


if __name__ == "__main__":
    main()
