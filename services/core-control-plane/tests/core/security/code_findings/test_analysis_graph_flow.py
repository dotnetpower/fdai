from __future__ import annotations

from fdai.core.security.code_findings.analysis_contracts import (
    AnalysisProvenance,
    CodeGraphArtifact,
    CodeGraphEdge,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    EvidenceConfidence,
    GraphEdgeKind,
    GraphNodeKind,
    PathStepRole,
    RuleAnalysisKind,
    RuleSelector,
    SourceSpan,
)
from fdai.core.security.code_findings.analysis_graph_flow import derive_graph_paths

DIGEST = f"sha256:{'b' * 64}"


def _span(line: int) -> SourceSpan:
    return SourceSpan(path="app.py", start_line=line, end_line=line)


def _rule() -> CodeSecurityRuleSpec:
    return CodeSecurityRuleSpec(
        schema_version="1.0.0",
        rule_id="fdai.python.sql-injection",
        version="1.0.0",
        analysis_kind=RuleAnalysisKind.GRAPH_FLOW,
        languages=("python",),
        cwe_ids=(89,),
        selectors=(
            RuleSelector(role="source", symbol="request.args"),
            RuleSelector(role="sink", symbol="execute", argument_index=0),
        ),
        vulnerable_cases=("cross-file",),
        safe_cases=("parameterized",),
    )


def _edge(
    kind: GraphEdgeKind,
    source: str,
    target: str,
    *,
    source_role: PathStepRole | None = None,
    target_role: PathStepRole | None = None,
    source_context: tuple[str, ...] = (),
    target_context: tuple[str, ...] = (),
) -> CodeGraphEdge:
    return CodeGraphEdge(
        edge_id=f"edge:{kind.value}:{source}:{target}",
        kind=kind,
        source_id=source,
        target_id=target,
        provenance=AnalysisProvenance(
            frontend="test-frontend",
            frontend_version="1.0.0",
            model_version="1.0.0",
            confidence=EvidenceConfidence.EXACT,
        ),
        source_role=source_role,
        target_role=target_role,
        source_context=source_context,
        target_context=target_context,
    )


def _graph(revision: str, line_shift: int = 0) -> CodeGraphArtifact:
    nodes = (
        CodeGraphNode(
            node_id="function:route",
            kind=GraphNodeKind.FUNCTION,
            name="route",
            span=SourceSpan(path="app.py", start_line=1, end_line=20 + line_shift),
        ),
        CodeGraphNode(
            node_id="function:helper",
            kind=GraphNodeKind.FUNCTION,
            name="helper",
            span=_span(10 + line_shift),
        ),
        CodeGraphNode(
            node_id="source:request",
            kind=GraphNodeKind.SOURCE,
            name="request.args",
            span=_span(3 + line_shift),
        ),
        CodeGraphNode(
            node_id="call:helper",
            kind=GraphNodeKind.CALL_SITE,
            name="helper",
            span=_span(4 + line_shift),
        ),
        CodeGraphNode(
            node_id="sink:execute",
            kind=GraphNodeKind.SINK,
            name="execute",
            span=_span(12 + line_shift),
        ),
    )
    return CodeGraphArtifact(
        schema_version="1.1.0",
        revision=revision,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        frontend_versions={"test-frontend": "1.0.0"},
        nodes=nodes,
        edges=(
            _edge(
                GraphEdgeKind.FLOWS_TO,
                "source:request",
                "call:helper",
                source_role=PathStepRole.SOURCE,
                target_role=PathStepRole.CALL,
                source_context=("function:route",),
                target_context=("function:route", "function:helper"),
            ),
            _edge(
                GraphEdgeKind.FLOWS_TO,
                "call:helper",
                "call:helper",
                source_role=PathStepRole.CALL,
                target_role=PathStepRole.RETURN,
                source_context=("function:route", "function:helper"),
                target_context=("function:route", "function:helper"),
            ),
            _edge(
                GraphEdgeKind.FLOWS_TO,
                "call:helper",
                "sink:execute",
                source_role=PathStepRole.RETURN,
                target_role=PathStepRole.SINK,
                source_context=("function:route", "function:helper"),
                target_context=("function:route",),
            ),
            _edge(GraphEdgeKind.CALLS, "call:helper", "function:helper"),
        ),
    )


def test_common_traversal_materializes_call_return_and_sink() -> None:
    (path,) = derive_graph_paths(_graph("a" * 40), _rule())

    assert [step.role for step in path.steps] == [
        PathStepRole.SOURCE,
        PathStepRole.CALL,
        PathStepRole.RETURN,
        PathStepRole.SINK,
    ]
    assert path.steps[1].call_context == ("function:route", "function:helper")
    assert path.steps[2].call_context == ("function:route", "function:helper")


def test_path_identity_survives_revision_and_line_shift() -> None:
    (first,) = derive_graph_paths(_graph("a" * 40), _rule())
    (second,) = derive_graph_paths(_graph("c" * 40, line_shift=5), _rule())

    assert first.path_id == second.path_id
    assert first.graph_digest != second.graph_digest
