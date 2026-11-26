"""Deterministic cache and dependency-aware invalidation for owned analysis."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.security.code_findings.analysis_contracts import (
    GRAPH_SCHEMA_VERSION,
    CodeGraphArtifact,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    GraphEdgeKind,
    GraphNodeKind,
    PathEvidence,
)
from fdai.core.security.code_findings.analysis_graph_flow import materialize_graph_paths
from fdai.core.security.code_findings.python_analysis import (
    PythonAnalysisResult,
    analyze_python_repository,
)
from fdai.core.security.code_findings.python_graph import (
    FRONTEND,
    VERSION,
    PythonAnalysisLimits,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IncrementalSnapshot(_Strict):
    schema_version: Literal["1.1.0"]
    revision: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    graph_schema_version: Literal["1.1.0"]
    frontend_versions: dict[str, str]
    rule_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    build_context_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    framework_model_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    file_digests: dict[str, str]
    reverse_dependencies: dict[str, tuple[str, ...]]
    forward_dependencies: dict[str, tuple[str, ...]]
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]

    @model_validator(mode="after")
    def _identity_matches_result(self) -> IncrementalSnapshot:
        if self.graph.revision != self.revision:
            raise ValueError("incremental graph revision differs from snapshot")
        if self.graph.schema_version != self.graph_schema_version:
            raise ValueError("incremental graph schema differs from snapshot")
        if self.graph.frontend_versions != self.frontend_versions:
            raise ValueError("incremental frontend versions differ from snapshot")
        graph_digest = self.graph.digest()
        if any(path.graph_digest != graph_digest for path in self.paths):
            raise ValueError("incremental path graph digest differs from snapshot")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class IncrementalPlan:
    changed_files: tuple[str, ...]
    affected_files: tuple[str, ...]
    reusable_files: tuple[str, ...]
    reused_result: bool
    reason: str
    partial_recompute: bool = False


@dataclass(frozen=True, slots=True)
class IncrementalAnalysisResult:
    result: PythonAnalysisResult
    snapshot: IncrementalSnapshot
    plan: IncrementalPlan
    partial_recompute: bool = False


def analyze_python_incremental(
    root: Path,
    *,
    revision: str,
    build_context_digest: str,
    framework_model_digest: str,
    rule: CodeSecurityRuleSpec,
    previous: IncrementalSnapshot | None = None,
    limits: PythonAnalysisLimits | None = None,
) -> IncrementalAnalysisResult:
    """Reuse an exact result or recompute after dependency-aware invalidation."""
    selected_limits = limits or PythonAnalysisLimits()
    current_digests = _file_digests(root, selected_limits)
    rule_digest = rule.digest()
    plan = _plan(
        previous,
        revision=revision,
        rule_digest=rule_digest,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        frontend_versions={FRONTEND: VERSION},
        current_digests=current_digests,
    )
    if previous is not None and plan.reused_result:
        reused = PythonAnalysisResult(previous.graph, previous.paths)
        return IncrementalAnalysisResult(reused, previous, plan)
    partial_recompute = False
    result: PythonAnalysisResult | None = None
    if (
        previous is not None
        and plan.reason == "dependency_invalidation"
        and not previous.graph.coverage_limits
    ):
        recomputed_files = _dependency_closure(
            plan.affected_files,
            previous.forward_dependencies,
        )
        current_recomputed = frozenset(recomputed_files & set(current_digests))
        if current_recomputed and len(current_recomputed) < len(current_digests):
            partial = analyze_python_repository(
                root,
                revision=revision,
                build_context_digest=build_context_digest,
                framework_model_digest=framework_model_digest,
                rule=rule,
                limits=selected_limits,
                included_paths=current_recomputed,
            )
            if not partial.graph.coverage_limits:
                result = _merge_partial_result(
                    previous.graph,
                    partial.graph,
                    recomputed_files,
                    set(current_digests),
                    rule,
                )
                partial_recompute = True
    if result is None:
        result = analyze_python_repository(
            root,
            revision=revision,
            build_context_digest=build_context_digest,
            framework_model_digest=framework_model_digest,
            rule=rule,
            limits=selected_limits,
        )
    plan = replace(plan, partial_recompute=partial_recompute)
    reverse_dependencies, forward_dependencies = _dependencies(result.graph)
    snapshot = IncrementalSnapshot(
        schema_version="1.1.0",
        revision=revision,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        frontend_versions={FRONTEND: VERSION},
        rule_digest=rule_digest,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        file_digests=current_digests,
        reverse_dependencies=reverse_dependencies,
        forward_dependencies=forward_dependencies,
        graph=result.graph,
        paths=result.paths,
    )
    return IncrementalAnalysisResult(result, snapshot, plan, partial_recompute)


def save_incremental_snapshot(path: Path, snapshot: IncrementalSnapshot) -> None:
    """Atomically persist one owner-only validated cache record."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = path.parent.resolve(strict=True) / path.name
    if destination.exists() and destination.is_symlink():
        raise ValueError("incremental snapshot destination cannot be a symlink")
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(snapshot.canonical_bytes() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def load_incremental_snapshot(path: Path) -> IncrementalSnapshot:
    """Load one bounded cache record without following a final symlink."""
    content = _bounded_read(path, 50_000_000, "incremental snapshot")
    return IncrementalSnapshot.model_validate_json(content)


def _bounded_read(path: Path, limit: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable or linked") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError(f"{label} is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise ValueError(f"{label} exceeds the byte limit")
        return content
    finally:
        os.close(descriptor)


def _file_digests(root: Path, limits: PythonAnalysisLimits) -> dict[str, str]:
    base = root.resolve(strict=True)
    paths = sorted(path for path in base.rglob("*.py") if path.is_file())
    if len(paths) > limits.max_files:
        raise ValueError("incremental input exceeds the file limit")
    digests: dict[str, str] = {}
    for path in paths:
        content = _bounded_read(path, limits.max_file_bytes, "incremental input")
        relative = path.relative_to(base).as_posix()
        digests[relative] = f"sha256:{hashlib.sha256(content).hexdigest()}"
    return digests


def _dependencies(
    graph: CodeGraphArtifact,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    nodes = {node.node_id: node for node in graph.nodes}
    reverse: dict[str, set[str]] = {}
    forward: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind is not GraphEdgeKind.CALLS:
            continue
        source = nodes.get(edge.source_id)
        target = nodes.get(edge.target_id)
        if source is None or target is None or source.span is None or target.span is None:
            continue
        if source.span.path != target.span.path:
            reverse.setdefault(target.span.path, set()).add(source.span.path)
            forward.setdefault(source.span.path, set()).add(target.span.path)
    return (
        {key: tuple(sorted(value)) for key, value in sorted(reverse.items())},
        {key: tuple(sorted(value)) for key, value in sorted(forward.items())},
    )


def _dependency_closure(
    affected_files: tuple[str, ...],
    forward_dependencies: dict[str, tuple[str, ...]],
) -> set[str]:
    closure = set(affected_files)
    pending = list(affected_files)
    while pending:
        caller = pending.pop()
        for callee in forward_dependencies.get(caller, ()):
            if callee not in closure:
                closure.add(callee)
                pending.append(callee)
    return closure


def _node_path(node: CodeGraphNode) -> str | None:
    if node.kind is GraphNodeKind.FILE:
        return node.name
    return node.span.path if node.span is not None else None


def _merge_partial_result(
    previous: CodeGraphArtifact,
    partial: CodeGraphArtifact,
    recomputed_files: set[str],
    current_files: set[str],
    rule: CodeSecurityRuleSpec,
) -> PythonAnalysisResult:
    kept_nodes = {
        node.node_id: node
        for node in previous.nodes
        if (path := _node_path(node)) is not None
        and path in current_files
        and path not in recomputed_files
    }
    merged_nodes = {**kept_nodes, **{node.node_id: node for node in partial.nodes}}
    kept_node_ids = set(kept_nodes)
    merged_edges = {
        edge.edge_id: edge
        for edge in previous.edges
        if edge.source_id in kept_node_ids and edge.target_id in kept_node_ids
    }
    merged_edges.update({edge.edge_id: edge for edge in partial.edges})
    graph = CodeGraphArtifact(
        schema_version=GRAPH_SCHEMA_VERSION,
        revision=partial.revision,
        build_context_digest=partial.build_context_digest,
        framework_model_digest=partial.framework_model_digest,
        frontend_versions=partial.frontend_versions,
        nodes=tuple(sorted(merged_nodes.values(), key=lambda node: node.node_id)),
        edges=tuple(sorted(merged_edges.values(), key=lambda edge: edge.edge_id)),
        coverage_limits=partial.coverage_limits,
    )
    flow = materialize_graph_paths(graph, rule)
    return PythonAnalysisResult(flow.graph, flow.paths)


def _plan(
    previous: IncrementalSnapshot | None,
    *,
    revision: str,
    rule_digest: str,
    build_context_digest: str,
    framework_model_digest: str,
    graph_schema_version: str,
    frontend_versions: dict[str, str],
    current_digests: dict[str, str],
) -> IncrementalPlan:
    if previous is None:
        files = tuple(sorted(current_digests))
        return IncrementalPlan(files, files, (), False, "no_previous_snapshot")
    identity_matches = (
        previous.rule_digest == rule_digest
        and previous.build_context_digest == build_context_digest
        and previous.framework_model_digest == framework_model_digest
        and previous.graph_schema_version == graph_schema_version
        and previous.frontend_versions == frontend_versions
    )
    if not identity_matches:
        files = tuple(sorted(current_digests))
        return IncrementalPlan(files, files, (), False, "analysis_identity_changed")
    changed = {
        path
        for path in set(previous.file_digests) | set(current_digests)
        if previous.file_digests.get(path) != current_digests.get(path)
    }
    if not changed and previous.revision == revision:
        files = tuple(sorted(current_digests))
        return IncrementalPlan((), (), files, True, "inputs_unchanged")
    if not changed:
        files = tuple(sorted(current_digests))
        return IncrementalPlan((), files, (), False, "revision_changed")
    affected = set(changed)
    pending = list(changed)
    while pending:
        dependency = pending.pop()
        for caller in previous.reverse_dependencies.get(dependency, ()):
            if caller not in affected:
                affected.add(caller)
                pending.append(caller)
    reusable = set(current_digests) - affected
    return IncrementalPlan(
        tuple(sorted(changed)),
        tuple(sorted(affected)),
        tuple(sorted(reusable)),
        False,
        "dependency_invalidation",
    )


__all__ = [
    "IncrementalAnalysisResult",
    "IncrementalPlan",
    "IncrementalSnapshot",
    "analyze_python_incremental",
    "load_incremental_snapshot",
    "save_incremental_snapshot",
]
