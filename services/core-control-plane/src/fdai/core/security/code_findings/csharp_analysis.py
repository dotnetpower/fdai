"""Bounded Roslyn compiler frontend for C# code-security graph analysis."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.core.security.code_findings.analysis_contracts import (
    AnalysisProvenance,
    CodeGraphArtifact,
    CodeGraphEdge,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    EvidenceConfidence,
    GraphEdgeKind,
    GraphNodeKind,
    PathEvidence,
    PathStepRole,
    SourceSpan,
)
from fdai.core.security.code_findings.analysis_graph_flow import materialize_graph_paths

FRONTEND = "roslyn"


@dataclass(frozen=True, slots=True)
class CSharpCompilerConfig:
    dotnet: Path
    assembly: Path
    timeout_seconds: int = 60
    max_files: int = 2_000
    max_file_bytes: int = 2_000_000
    max_output_bytes: int = 20_000_000
    max_paths: int = 1_000
    max_depth: int = 16


@dataclass(frozen=True, slots=True)
class CSharpAnalysisResult:
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Step(_Strict):
    role: Literal["source", "flow", "call", "return", "sanitizer", "sink"]
    path: str = Field(min_length=1, max_length=1_024)
    line: int = Field(ge=1, le=10_000_000)
    name: str = Field(min_length=1, max_length=1_024)
    context: tuple[str, ...] = Field(max_length=16)


class _Method(_Strict):
    path: str = Field(min_length=1, max_length=1_024)
    line: int = Field(ge=1, le=10_000_000)
    name: str = Field(min_length=1, max_length=1_024)


class _Response(_Strict):
    schema_version: Literal["1.0.0"]
    compiler_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    paths: tuple[tuple[_Step, ...], ...] = Field(max_length=1_000)
    methods: tuple[_Method, ...] = Field(max_length=100_000)
    error_count: int = Field(ge=0, le=1_000_000)
    coverage_limits: tuple[str, ...] = Field(max_length=64)


def _stable_id(*parts: object) -> str:
    raw = "\0".join(str(part) for part in parts).encode()
    return f"csharp:{hashlib.sha256(raw).hexdigest()[:24]}"


def _span(path: str, line: int) -> SourceSpan:
    return SourceSpan(
        path=path,
        start_line=line,
        start_column=1,
        end_line=line,
        end_column=1,
    )


def _files(root: Path, config: CSharpCompilerConfig) -> tuple[str, ...]:
    paths = sorted(path for path in root.rglob("*.cs") if path.is_file())
    if len(paths) > config.max_files:
        raise ValueError("C# compiler input exceeds the file limit")
    files: list[str] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_relative_to(root):
            raise ValueError("C# source escapes the analysis root")
        if path.stat().st_size > config.max_file_bytes:
            raise ValueError("C# source exceeds the file byte limit")
        files.append(path.relative_to(root).as_posix())
    return tuple(files)


def analyze_csharp_repository(
    root: Path,
    *,
    revision: str,
    build_context_digest: str,
    framework_model_digest: str,
    rule: CodeSecurityRuleSpec,
    config: CSharpCompilerConfig,
) -> CSharpAnalysisResult | None:
    """Analyze C# with Roslyn without emitting or executing a target assembly."""
    if "csharp" not in rule.languages:
        raise ValueError("C# analysis requires a rule that names csharp")
    base = root.resolve(strict=True)
    if root.is_symlink() or not base.is_dir():
        raise ValueError("C# analysis root must be a non-symlink directory")
    files = _files(base, config)
    if not files:
        return None
    dotnet = config.dotnet.resolve(strict=True)
    assembly = config.assembly.resolve(strict=True)
    if not dotnet.is_file() or not assembly.is_file() or assembly.is_relative_to(base):
        raise ValueError("C# compiler bindings must be trusted files outside analyzed source")
    request = {
        "root": str(base),
        "files": files,
        "rule": rule.model_dump(mode="json"),
        "max_paths": config.max_paths,
        "max_depth": config.max_depth,
    }
    try:
        completed = subprocess.run(  # noqa: S603 - exact trusted executable and assembly paths
            [str(dotnet), str(assembly)],
            input=json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode(),
            capture_output=True,
            cwd=base,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
                "DOTNET_gcServer": "0",
                "DOTNET_GCHeapHardLimit": "0x40000000",
            },
            timeout=config.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"C# compiler frontend failed: {type(exc).__name__}") from exc
    if completed.returncode != 0 or len(completed.stdout) > config.max_output_bytes:
        raise ValueError("C# compiler frontend failed or exceeded its output limit")
    try:
        document = _Response.model_validate_json(completed.stdout)
    except ValidationError as exc:
        raise ValueError("C# compiler frontend output violates its contract") from exc
    allowed = set(files)
    if any(item.path not in allowed for item in document.methods) or any(
        step.path not in allowed for evidence_path in document.paths for step in evidence_path
    ):
        raise ValueError("C# compiler frontend returned a path outside the request")
    nodes: dict[str, CodeGraphNode] = {}
    edges: dict[str, CodeGraphEdge] = {}
    provenance = AnalysisProvenance(
        frontend=FRONTEND,
        frontend_version=document.compiler_version,
        model_version="1.0.0",
        confidence=EvidenceConfidence.EXACT,
    )
    file_nodes: dict[str, str] = {}
    for relative in files:
        node_id = _stable_id("file", relative)
        file_nodes[relative] = node_id
        nodes[node_id] = CodeGraphNode(node_id=node_id, kind=GraphNodeKind.FILE, name=relative)
    for method in document.methods:
        node_id = _stable_id("method", method.path, method.line, method.name)
        nodes[node_id] = CodeGraphNode(
            node_id=node_id,
            kind=GraphNodeKind.FUNCTION,
            name=method.name,
            span=_span(method.path, method.line),
        )
        edge_id = _stable_id("declares", file_nodes[method.path], node_id)
        edges[edge_id] = CodeGraphEdge(
            edge_id=edge_id,
            kind=GraphEdgeKind.DECLARES,
            source_id=file_nodes[method.path],
            target_id=node_id,
            provenance=provenance,
        )
    for evidence_path in document.paths:
        previous: tuple[str, _Step] | None = None
        for step in evidence_path:
            node_id = _stable_id(step.role, step.path, step.line, step.name, step.context)
            kind = {
                "source": GraphNodeKind.SOURCE,
                "sink": GraphNodeKind.SINK,
                "sanitizer": GraphNodeKind.SANITIZER,
                "call": GraphNodeKind.CALL_SITE,
                "return": GraphNodeKind.CALL_SITE,
                "flow": GraphNodeKind.DATA_FLOW,
            }[step.role]
            nodes[node_id] = CodeGraphNode(
                node_id=node_id,
                kind=kind,
                name=step.name,
                span=_span(step.path, step.line),
            )
            if previous is not None:
                prior_id, prior = previous
                edge_id = _stable_id("flow", prior_id, node_id, prior.context, step.context)
                edges[edge_id] = CodeGraphEdge(
                    edge_id=edge_id,
                    kind=GraphEdgeKind.FLOWS_TO,
                    source_id=prior_id,
                    target_id=node_id,
                    provenance=provenance,
                    source_role=PathStepRole(prior.role),
                    target_role=PathStepRole(step.role),
                    source_context=prior.context,
                    target_context=step.context,
                )
            previous = (node_id, step)
    coverage = set(document.coverage_limits)
    if document.error_count:
        coverage.add(f"csharp.compiler-attribution-errors:{document.error_count}")
    graph = CodeGraphArtifact(
        schema_version="1.1.0",
        revision=revision,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        frontend_versions={FRONTEND: document.compiler_version},
        nodes=tuple(sorted(nodes.values(), key=lambda item: item.node_id)),
        edges=tuple(sorted(edges.values(), key=lambda item: item.edge_id)),
        coverage_limits=tuple(sorted(coverage)),
    )
    flow = materialize_graph_paths(graph, rule)
    return CSharpAnalysisResult(flow.graph, flow.paths)


__all__ = ["CSharpAnalysisResult", "CSharpCompilerConfig", "analyze_csharp_repository"]
