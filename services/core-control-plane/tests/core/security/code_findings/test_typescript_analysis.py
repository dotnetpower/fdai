"""Boundary tests for the TypeScript Compiler API frontend adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    GraphNodeKind,
    PathEvidence,
    PathEvidenceStep,
    PathStepRole,
    RuleAnalysisKind,
    RuleSelector,
    SourceSpan,
)
from fdai.core.security.code_findings.typescript_analysis import (
    TypeScriptAnalysisError,
    TypeScriptFrontendConfig,
    analyze_typescript_repository,
)

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def rule() -> CodeSecurityRuleSpec:
    return CodeSecurityRuleSpec(
        schema_version="1.0.0",
        rule_id="fdai.typescript.sql-injection",
        version="1.0.0",
        analysis_kind=RuleAnalysisKind.GRAPH_FLOW,
        languages=("typescript",),
        cwe_ids=(89,),
        selectors=(
            RuleSelector(role="source", symbol="Request.query"),
            RuleSelector(role="sink", symbol="query", argument_index=0),
            RuleSelector(role="propagator", symbol="trim"),
        ),
        vulnerable_cases=("typescript-sqli-cross-file",),
        safe_cases=("typescript-sqli-parameterized",),
    )


def contract() -> dict[str, object]:
    source = CodeGraphNode(
        node_id="source:1",
        kind=GraphNodeKind.SOURCE,
        name="request parameter",
        span=SourceSpan(path="app.ts", start_line=2, end_line=2),
    )
    sink = CodeGraphNode(
        node_id="sink:1",
        kind=GraphNodeKind.SINK,
        name="pool.query",
        span=SourceSpan(path="app.ts", start_line=3, end_line=3),
    )
    graph = CodeGraphArtifact(
        schema_version="1.0.0",
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        frontend_versions={"typescript-compiler": "5.9.3"},
        nodes=(source, sink),
    )
    path = PathEvidence(
        schema_version="1.0.0",
        revision=REVISION,
        graph_digest=graph.digest(),
        rule_id=rule().rule_id,
        rule_version=rule().version,
        steps=(
            PathEvidenceStep(node_id=source.node_id, role=PathStepRole.SOURCE, span=source.span),  # type: ignore[arg-type]
            PathEvidenceStep(node_id=sink.node_id, role=PathStepRole.SINK, span=sink.span),  # type: ignore[arg-type]
        ),
    )
    return {"graph": graph.model_dump(mode="json"), "paths": [path.model_dump(mode="json")]}


def frontend(tmp_path: Path, document: dict[str, object]) -> TypeScriptFrontendConfig:
    script = tmp_path / "frontend.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "json.load(sys.stdin)\n"
        f"print({json.dumps(json.dumps(document))})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return TypeScriptFrontendConfig(node=script, script=script)


def test_adapter_accepts_only_revision_bound_closed_graph(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.ts").write_text("export const value = 1;", encoding="utf-8")

    result = analyze_typescript_repository(
        source,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        rule=rule(),
        config=frontend(tmp_path, contract()),
    )

    assert result is not None and len(result.paths) == 1


def test_adapter_rejects_mismatched_path_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.ts").write_text("export const value = 1;", encoding="utf-8")
    document = contract()
    document["paths"][0]["graph_digest"] = "sha256:" + "c" * 64  # type: ignore[index]

    with pytest.raises(TypeScriptAnalysisError, match="path identity"):
        analyze_typescript_repository(
            source,
            revision=REVISION,
            build_context_digest=DIGEST,
            framework_model_digest=DIGEST,
            rule=rule(),
            config=frontend(tmp_path, document),
        )


def test_adapter_rejects_graph_path_outside_requested_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.ts").write_text("export const value = 1;", encoding="utf-8")
    document = contract()
    document["graph"]["nodes"][0]["span"]["path"] = "other.ts"  # type: ignore[index]

    with pytest.raises(TypeScriptAnalysisError, match="outside the request"):
        analyze_typescript_repository(
            source,
            revision=REVISION,
            build_context_digest=DIGEST,
            framework_model_digest=DIGEST,
            rule=rule(),
            config=frontend(tmp_path, document),
        )


def test_adapter_returns_none_when_repository_has_no_typescript(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    binding = frontend(tmp_path, contract())

    assert (
        analyze_typescript_repository(
            source,
            revision=REVISION,
            build_context_digest=DIGEST,
            framework_model_digest=DIGEST,
            rule=rule(),
            config=binding,
        )
        is None
    )
