"""Read-only configuration baseline, drift, Knowledge, and performance panel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_configuration_drift import (
    ConfigurationDriftChatTools,
)


class ConfigurationBaselinesPanel:
    """Project one server-pinned baseline without exposing mutation controls."""

    path = "/configuration-baselines"
    name = "configuration-baselines"

    def __init__(self, context: ConfigurationDriftChatTools) -> None:
        self._context = context

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        baseline = await self._context.baseline_source.load()
        report = await self._context.service.run()
        counts = Counter(finding.drift_type.value for finding in report.findings)
        performance = report.performance.to_dict() if report.performance is not None else None
        return {
            "source": "configuration-baseline",
            "baseline": {
                "version": baseline.version,
                "sha256": baseline.sha256,
                "scope": baseline.scope,
                "created_at": baseline.created_at.isoformat(),
                "document_name": self._context.document_name,
                "document_sha256": baseline.document_sha256,
                "resource_count": len(baseline.resources),
                "topology_count": len(baseline.links),
                "unknown_count": len(baseline.unknown_items),
                "lifecycle": "active-pinned",
            },
            "drift": {
                "verdict": report.verdict.value,
                "observed_at": report.observed_at.isoformat(),
                "finding_count": len(report.findings),
                "counts": dict(sorted(counts.items())),
            },
            "knowledge": {
                "status": report.knowledge_status.value,
                "citation_count": len(report.knowledge_citations),
                "citations": list(report.knowledge_citations),
            },
            "safety": {
                "mutation_count": report.mutation_count,
                "approval_request_count": report.approval_request_count,
                "mitigation_execution_count": report.mitigation_execution_count,
                "unsupported_claim_count": report.unsupported_claim_count,
            },
            "performance": performance,
            "review": {
                "configured": False,
                "state": "not-configured",
                "completed_runs": 0,
                "required_runs": 3,
            },
        }


__all__ = ["ConfigurationBaselinesPanel"]
