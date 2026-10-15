"""Language-neutral traversal from code-graph flow edges to path evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.security.code_findings.analysis_contracts import (
    PATH_SCHEMA_VERSION,
    CodeGraphArtifact,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    GraphEdgeKind,
    GraphNodeKind,
    PathEvidence,
    PathEvidenceStep,
    PathStepRole,
)


@dataclass(frozen=True, slots=True)
class GraphFlowLimits:
    max_paths: int = 5_000
    max_steps: int = 256


def _containing_function(source: CodeGraphNode, functions: tuple[CodeGraphNode, ...]) -> str | None:
    if source.span is None:
        return None
    candidates = [
        function
        for function in functions
        if function.span is not None
        and function.span.path == source.span.path
        and (function.span.start_line, function.span.start_column)
        <= (source.span.start_line, source.span.start_column)
        <= (function.span.end_line, function.span.end_column)
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda function: (
            function.span.end_line - function.span.start_line,  # type: ignore[union-attr]
            function.node_id,
        ),
    )
    return selected.node_id


def _path_id(
    graph: CodeGraphArtifact,
    rule: CodeSecurityRuleSpec,
    steps: tuple[PathEvidenceStep, ...],
) -> str:
    nodes = {node.node_id: node for node in graph.nodes}
    semantic_steps = []
    for step in steps:
        node = nodes[step.node_id]
        semantic_steps.append(
            {
                "kind": node.kind.value,
                "name": node.name,
                "path": step.span.path,
                "role": step.role.value,
                "context": step.call_context,
            }
        )
    canonical = json.dumps(
        [rule.rule_id, rule.version, semantic_steps],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"path:{hashlib.sha256(canonical).hexdigest()}"


def derive_graph_paths(
    graph: CodeGraphArtifact,
    rule: CodeSecurityRuleSpec,
    *,
    limits: GraphFlowLimits | None = None,
) -> tuple[PathEvidence, ...]:
    """Traverse only common graph contracts and return deterministic source-to-sink paths."""
    selected_limits = limits or GraphFlowLimits()
    nodes = {node.node_id: node for node in graph.nodes}
    functions = tuple(node for node in graph.nodes if node.kind is GraphNodeKind.FUNCTION)
    adjacency: dict[
        tuple[str, PathStepRole, tuple[str, ...]],
        list[tuple[str, PathStepRole, tuple[str, ...]]],
    ] = {}
    for edge in graph.edges:
        if edge.kind is GraphEdgeKind.FLOWS_TO:
            if edge.source_role is None or edge.target_role is None:
                raise ValueError("flow edge lacks contextual occurrence metadata")
            source_occurrence = (edge.source_id, edge.source_role, edge.source_context)
            target_occurrence = (edge.target_id, edge.target_role, edge.target_context)
            adjacency.setdefault(source_occurrence, []).append(target_occurrence)
    for targets in adjacency.values():
        targets.sort()

    candidates: list[tuple[PathEvidenceStep, ...]] = []

    def walk(
        occurrence: tuple[str, PathStepRole, tuple[str, ...]],
        steps: tuple[PathEvidenceStep, ...],
        visited: frozenset[
            tuple[
                tuple[str, PathStepRole, tuple[str, ...]],
                tuple[str, PathStepRole, tuple[str, ...]],
            ]
        ],
    ) -> None:
        if len(candidates) >= selected_limits.max_paths or len(steps) >= selected_limits.max_steps:
            return
        for target_occurrence in adjacency.get(occurrence, ()):
            edge = (occurrence, target_occurrence)
            target_id, role, context = target_occurrence
            target = nodes[target_id]
            if edge in visited or target.span is None:
                continue
            next_steps = steps + (
                PathEvidenceStep(
                    node_id=target_id,
                    role=role,
                    span=target.span,
                    call_context=context,
                ),
            )
            if role is PathStepRole.SINK:
                candidates.append(next_steps)
            else:
                walk(
                    target_occurrence,
                    next_steps,
                    visited | {edge},
                )

    for source in sorted(
        (node for node in graph.nodes if node.kind is GraphNodeKind.SOURCE),
        key=lambda node: node.node_id,
    ):
        if source.span is None:
            continue
        owner = _containing_function(source, functions)
        fallback_context = (owner,) if owner is not None else ()
        occurrences = sorted(
            occurrence
            for occurrence in adjacency
            if occurrence[0] == source.node_id and occurrence[1] is PathStepRole.SOURCE
        )
        for occurrence in occurrences:
            context = occurrence[2] or fallback_context
            first = PathEvidenceStep(
                node_id=source.node_id,
                role=PathStepRole.SOURCE,
                span=source.span,
                call_context=context,
            )
            walk(occurrence, (first,), frozenset())

    sanitizer_contexts = tuple(
        sorted(
            selector.security_context
            for selector in rule.selectors
            if selector.role == "sanitizer" and selector.security_context is not None
        )
    )
    unique: dict[str, PathEvidence] = {}
    for steps in candidates:
        path_id = _path_id(graph, rule, steps)
        unique[path_id] = PathEvidence(
            schema_version=PATH_SCHEMA_VERSION,
            path_id=path_id,
            revision=graph.revision,
            graph_digest=graph.digest(),
            rule_id=rule.rule_id,
            rule_version=rule.version,
            steps=steps,
            sanitizers_considered=sanitizer_contexts,
            coverage_limits=graph.coverage_limits,
        )
    return tuple(unique[path_id] for path_id in sorted(unique))


__all__ = ["GraphFlowLimits", "derive_graph_paths"]
