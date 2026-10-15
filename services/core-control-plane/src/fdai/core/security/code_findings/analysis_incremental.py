"""Deterministic cache and dependency-aware invalidation for owned analysis."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeSecurityRuleSpec,
    GraphEdgeKind,
    PathEvidence,
)
from fdai.core.security.code_findings.python_analysis import (
    PythonAnalysisResult,
    analyze_python_repository,
)
from fdai.core.security.code_findings.python_graph import PythonAnalysisLimits


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IncrementalSnapshot(_Strict):
    schema_version: str = Field(pattern=r"^1\.0\.0$")
    revision: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    rule_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    build_context_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    framework_model_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    file_digests: dict[str, str]
    reverse_dependencies: dict[str, tuple[str, ...]]
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]

    @model_validator(mode="after")
    def _identity_matches_result(self) -> IncrementalSnapshot:
        if self.graph.revision != self.revision:
            raise ValueError("incremental graph revision differs from snapshot")
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


@dataclass(frozen=True, slots=True)
class IncrementalAnalysisResult:
    result: PythonAnalysisResult
    snapshot: IncrementalSnapshot
    plan: IncrementalPlan


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
        current_digests=current_digests,
    )
    if previous is not None and plan.reused_result:
        result = PythonAnalysisResult(previous.graph, previous.paths)
        return IncrementalAnalysisResult(result, previous, plan)
    result = analyze_python_repository(
        root,
        revision=revision,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        rule=rule,
        limits=selected_limits,
    )
    snapshot = IncrementalSnapshot(
        schema_version="1.0.0",
        revision=revision,
        rule_digest=rule_digest,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        file_digests=current_digests,
        reverse_dependencies=_reverse_dependencies(result.graph),
        graph=result.graph,
        paths=result.paths,
    )
    return IncrementalAnalysisResult(result, snapshot, plan)


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


def _reverse_dependencies(graph: CodeGraphArtifact) -> dict[str, tuple[str, ...]]:
    nodes = {node.node_id: node for node in graph.nodes}
    dependencies: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind is not GraphEdgeKind.CALLS:
            continue
        source = nodes.get(edge.source_id)
        target = nodes.get(edge.target_id)
        if source is None or target is None or source.span is None or target.span is None:
            continue
        if source.span.path != target.span.path:
            dependencies.setdefault(target.span.path, set()).add(source.span.path)
    return {key: tuple(sorted(value)) for key, value in sorted(dependencies.items())}


def _plan(
    previous: IncrementalSnapshot | None,
    *,
    revision: str,
    rule_digest: str,
    build_context_digest: str,
    framework_model_digest: str,
    current_digests: dict[str, str],
) -> IncrementalPlan:
    if previous is None:
        files = tuple(sorted(current_digests))
        return IncrementalPlan(files, files, (), False, "no_previous_snapshot")
    identity_matches = (
        previous.revision == revision
        and previous.rule_digest == rule_digest
        and previous.build_context_digest == build_context_digest
        and previous.framework_model_digest == framework_model_digest
    )
    if not identity_matches:
        files = tuple(sorted(current_digests))
        return IncrementalPlan(files, files, (), False, "analysis_identity_changed")
    changed = {
        path
        for path in set(previous.file_digests) | set(current_digests)
        if previous.file_digests.get(path) != current_digests.get(path)
    }
    if not changed:
        files = tuple(sorted(current_digests))
        return IncrementalPlan((), (), files, True, "inputs_unchanged")
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
