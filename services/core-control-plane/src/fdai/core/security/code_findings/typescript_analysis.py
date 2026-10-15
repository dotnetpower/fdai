"""Bounded process adapter for the TypeScript Compiler API frontend."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeSecurityRuleSpec,
    PathEvidence,
    RuleAnalysisKind,
)


class TypeScriptAnalysisError(RuntimeError):
    """The frontend was unavailable or returned output outside the strict contract."""


@dataclass(frozen=True, slots=True)
class TypeScriptFrontendConfig:
    node: Path
    script: Path
    timeout_seconds: int = 60
    max_files: int = 5000
    max_file_bytes: int = 1_000_000
    max_output_bytes: int = 20_000_000


@dataclass(frozen=True, slots=True)
class TypeScriptAnalysisResult:
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]


def typescript_files(
    root: Path, config: TypeScriptFrontendConfig
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return safe TypeScript files and explicit input coverage limits."""
    candidates = sorted(
        path
        for pattern in ("*.ts", "*.tsx", "*.mts", "*.cts")
        for path in root.rglob(pattern)
        if path.is_file()
    )
    limits: list[str] = []
    if len(candidates) > config.max_files:
        limits.append("typescript.file-limit")
        candidates = candidates[: config.max_files]
    files: list[str] = []
    base = root.resolve(strict=True)
    for path in candidates:
        relative = path.relative_to(base).as_posix()
        if path.is_symlink():
            limits.append(f"typescript.symlink.{len(limits)}")
            continue
        try:
            size = path.stat().st_size
        except OSError:
            limits.append(f"typescript.unavailable.{len(limits)}")
            continue
        if size > config.max_file_bytes:
            limits.append(f"typescript.file-size.{len(limits)}")
            continue
        files.append(relative)
    return tuple(files), tuple(limits)


def analyze_typescript_repository(
    root: Path,
    *,
    revision: str,
    build_context_digest: str,
    framework_model_digest: str,
    rule: CodeSecurityRuleSpec,
    config: TypeScriptFrontendConfig,
) -> TypeScriptAnalysisResult | None:
    """Run the trusted Compiler API frontend and validate every returned identity."""
    if "typescript" not in rule.languages or rule.analysis_kind is not RuleAnalysisKind.GRAPH_FLOW:
        raise ValueError("TypeScript analysis requires a graph_flow rule that names typescript")
    base = root.resolve(strict=True)
    if not base.is_dir():
        raise ValueError("analysis root must be a directory")
    node = config.node.resolve(strict=True)
    script = config.script.resolve(strict=True)
    if not node.is_file() or not script.is_file() or script.is_relative_to(base):
        raise ValueError("TypeScript frontend bindings must be files outside analyzed source")
    files, input_limits = typescript_files(base, config)
    if not files:
        return None
    request = {
        "root": str(base),
        "files": files,
        "revision": revision,
        "build_context_digest": build_context_digest,
        "framework_model_digest": framework_model_digest,
        "rule": rule.model_dump(mode="json"),
        "limits": {"max_call_depth": 12, "max_paths": 5000},
    }
    try:
        completed = subprocess.run(  # noqa: S603 - exact trusted executable and script paths
            [str(node), str(script)],
            input=json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
            capture_output=True,
            cwd=base,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            timeout=config.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TypeScriptAnalysisError(f"TypeScript frontend failed: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise TypeScriptAnalysisError(
            f"TypeScript frontend exited {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', 'replace')[:300]}"
        )
    if len(completed.stdout) > config.max_output_bytes:
        raise TypeScriptAnalysisError("TypeScript frontend output exceeds the configured limit")
    try:
        document = json.loads(completed.stdout)
        graph = CodeGraphArtifact.model_validate(document["graph"])
        paths = tuple(PathEvidence.model_validate(item) for item in document["paths"])
    except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise TypeScriptAnalysisError("TypeScript frontend output violates the contract") from exc
    if input_limits:
        graph = graph.model_copy(
            update={"coverage_limits": tuple(sorted({*graph.coverage_limits, *input_limits}))}
        )
    _validate_result(graph, paths, revision=revision, rule=rule)
    return TypeScriptAnalysisResult(graph, paths)


def _validate_result(
    graph: CodeGraphArtifact,
    paths: tuple[PathEvidence, ...],
    *,
    revision: str,
    rule: CodeSecurityRuleSpec,
) -> None:
    if graph.revision != revision:
        raise TypeScriptAnalysisError("TypeScript graph revision differs from the request")
    expected_digest = graph.digest()
    known_nodes = {node.node_id for node in graph.nodes}
    for path in paths:
        if (
            path.revision != revision
            or path.rule_id != rule.rule_id
            or path.rule_version != rule.version
            or path.graph_digest != expected_digest
        ):
            raise TypeScriptAnalysisError("TypeScript path identity differs from the request")
        if any(step.node_id not in known_nodes for step in path.steps):
            raise TypeScriptAnalysisError("TypeScript path references an unknown graph node")


__all__ = [
    "TypeScriptAnalysisError",
    "TypeScriptAnalysisResult",
    "TypeScriptFrontendConfig",
    "analyze_typescript_repository",
    "typescript_files",
]
