"""Contract tests for owned code-security graph and path evidence."""

from __future__ import annotations

import json

import pytest
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
    PathEvidenceStep,
    PathStepRole,
    RuleAnalysisKind,
    RuleSelector,
    SourceSpan,
)
from pydantic import ValidationError

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def span(path: str, line: int) -> SourceSpan:
    return SourceSpan(path=path, start_line=line, end_line=line)


def provenance() -> AnalysisProvenance:
    return AnalysisProvenance(
        frontend="python-ast",
        frontend_version="1.0.0",
        model_version="1.0.0",
        confidence=EvidenceConfidence.EXACT,
    )


def graph() -> CodeGraphArtifact:
    nodes = (
        CodeGraphNode(
            node_id="source:src/api.py:4",
            kind=GraphNodeKind.SOURCE,
            name="request.args",
            span=span("src/api.py", 4),
        ),
        CodeGraphNode(
            node_id="sink:src/db.py:9",
            kind=GraphNodeKind.SINK,
            name="cursor.execute",
            span=span("src/db.py", 9),
        ),
    )
    edge = CodeGraphEdge(
        edge_id="flow:source-to-sink",
        kind=GraphEdgeKind.FLOWS_TO,
        source_id=nodes[0].node_id,
        target_id=nodes[1].node_id,
        provenance=provenance(),
        source_role=PathStepRole.SOURCE,
        target_role=PathStepRole.SINK,
        source_context=("src.api.route",),
        target_context=("src.api.route", "src.db.query"),
    )
    return CodeGraphArtifact(
        schema_version="1.1.0",
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        frontend_versions={"python-ast": "1.0.0"},
        nodes=nodes,
        edges=(edge,),
    )


def test_graph_contract_is_deterministic_and_closed() -> None:
    artifact = graph()
    reparsed = CodeGraphArtifact.model_validate_json(artifact.canonical_bytes())

    assert reparsed == artifact
    assert reparsed.digest() == artifact.digest()
    assert json.loads(artifact.canonical_bytes())["schema_version"] == "1.1.0"


def test_flow_edge_requires_source_and_target_occurrences() -> None:
    with pytest.raises(ValidationError, match="source and target roles"):
        CodeGraphEdge(
            edge_id="flow:missing-occurrence",
            kind=GraphEdgeKind.FLOWS_TO,
            source_id="source:a",
            target_id="sink:b",
            provenance=provenance(),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("nodes", lambda value: value + (value[0],), "node ids"),
        (
            "edges",
            lambda value: (value[0].model_copy(update={"target_id": "missing:node"}),),
            "unknown node",
        ),
        ("frontend_versions", lambda _value: {}, "frontend version"),
    ],
)
def test_graph_contract_rejects_ambiguous_or_dangling_records(
    field: str,
    value,
    message: str,  # type: ignore[no-untyped-def]
) -> None:
    artifact = graph()
    body = artifact.model_dump(mode="python")
    body[field] = value(getattr(artifact, field))

    with pytest.raises(ValidationError, match=message):
        CodeGraphArtifact.model_validate(body)


def test_rule_contract_requires_contextual_sanitizer_and_safe_cases() -> None:
    rule = CodeSecurityRuleSpec(
        schema_version="1.0.0",
        rule_id="fdai.python.sql-injection",
        version="1.0.0",
        analysis_kind=RuleAnalysisKind.GRAPH_FLOW,
        languages=("python",),
        cwe_ids=(89,),
        selectors=(
            RuleSelector(role="source", symbol="flask.request.args"),
            RuleSelector(role="sink", symbol="cursor.execute", argument_index=0),
            RuleSelector(
                role="sanitizer",
                symbol="cursor.execute",
                security_context="sql-parameter-binding",
            ),
        ),
        vulnerable_cases=("python-sqli-cross-file",),
        safe_cases=("python-sqli-parameterized",),
    )

    assert rule.digest().startswith("sha256:")
    with pytest.raises(ValidationError, match="security_context"):
        RuleSelector(role="sanitizer", symbol="html.escape")
    with pytest.raises(ValidationError, match="safe_cases"):
        CodeSecurityRuleSpec.model_validate({**rule.model_dump(), "safe_cases": []})


def test_path_evidence_requires_source_to_sink_order_and_stable_context() -> None:
    artifact = graph()
    steps = (
        PathEvidenceStep(
            node_id=artifact.nodes[0].node_id,
            role=PathStepRole.SOURCE,
            span=span("src/api.py", 4),
            call_context=("src.api.route",),
        ),
        PathEvidenceStep(
            node_id=artifact.nodes[1].node_id,
            role=PathStepRole.SINK,
            span=span("src/db.py", 9),
            call_context=("src.api.route", "src.db.query"),
        ),
    )
    evidence = PathEvidence(
        schema_version="1.1.0",
        path_id="path:contract-test",
        revision=REVISION,
        graph_digest=artifact.digest(),
        rule_id="fdai.python.sql-injection",
        rule_version="1.0.0",
        steps=steps,
        sanitizers_considered=("sql-parameter-binding",),
    )

    reparsed = PathEvidence.model_validate_json(evidence.canonical_bytes())
    assert reparsed.digest() == evidence.digest()
    with pytest.raises(ValidationError, match="start at a source"):
        PathEvidence.model_validate({**evidence.model_dump(), "steps": tuple(reversed(steps))})


def test_contracts_reject_path_traversal_and_unexplained_uncertainty() -> None:
    with pytest.raises(ValidationError, match="repository-relative"):
        span("../secret.py", 1)
    with pytest.raises(ValidationError, match="at least one alternative"):
        AnalysisProvenance(
            frontend="typescript",
            frontend_version="1.0.0",
            model_version="1.0.0",
            confidence=EvidenceConfidence.UNRESOLVED,
        )
