"""SARIF 2.1.0 adapter for FDAI-owned graph-analysis evidence."""

from __future__ import annotations

import json
from typing import Protocol

from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeSecurityRuleSpec,
    GraphNodeKind,
    PathEvidence,
)

PRODUCER = "FDAI analysis engine"
PRODUCER_VERSION = "1.0.0"


class AnalysisResult(Protocol):
    @property
    def graph(self) -> CodeGraphArtifact: ...

    @property
    def paths(self) -> tuple[PathEvidence, ...]: ...


def render_analysis_sarif(result: AnalysisResult, rule: CodeSecurityRuleSpec) -> bytes:
    """Render bounded path evidence without source text or model-generated claims."""
    artifacts = sorted(
        {
            node.span.path
            for node in result.graph.nodes
            if node.kind is GraphNodeKind.FILE and node.span is not None
        }
    )
    results: list[dict[str, object]] = []
    for path in result.paths:
        sink = path.steps[-1]
        results.append(
            {
                "ruleId": rule.rule_id,
                "level": "error",
                "message": {
                    "text": "Untrusted input reaches SQL execution across function boundaries."
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": sink.span.path},
                            "region": {
                                "startLine": sink.span.start_line,
                                "endLine": sink.span.end_line,
                            },
                        }
                    }
                ],
                "codeFlows": [
                    {
                        "threadFlows": [
                            {
                                "locations": [
                                    {
                                        "location": {
                                            "physicalLocation": {
                                                "artifactLocation": {"uri": step.span.path},
                                                "region": {
                                                    "startLine": step.span.start_line,
                                                    "endLine": step.span.end_line,
                                                },
                                            }
                                        }
                                    }
                                    for step in path.steps
                                ]
                            }
                        ]
                    }
                ],
                "properties": {
                    "tags": [f"CWE-{cwe}" for cwe in rule.cwe_ids],
                    "fdaiPathDigest": path.digest(),
                    "fdaiGraphDigest": result.graph.digest(),
                    "fdaiCoverageLimits": list(path.coverage_limits),
                },
            }
        )
    document = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": PRODUCER,
                        "version": PRODUCER_VERSION,
                        "semanticVersion": PRODUCER_VERSION,
                        "rules": [
                            {
                                "id": rule.rule_id,
                                "name": rule.rule_id,
                                "properties": {"tags": [f"CWE-{cwe}" for cwe in rule.cwe_ids]},
                            }
                        ],
                    }
                },
                "invocations": [{"executionSuccessful": not result.graph.coverage_limits}],
                "artifacts": [{"location": {"uri": path}} for path in artifacts],
                "properties": {
                    "truncated": False,
                    "graphDigest": result.graph.digest(),
                    "coverageLimits": list(result.graph.coverage_limits),
                },
                "results": results,
            }
        ],
    }
    return (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


__all__ = ["PRODUCER", "PRODUCER_VERSION", "render_analysis_sarif"]
