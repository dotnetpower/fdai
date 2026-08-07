"""Read-only configuration baseline, drift, Knowledge, and performance panel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from fdai.core.detection.configuration_drift import (
    ConfigurationBaselineRegistry,
    ConfigurationObservation,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    compare_configuration,
)
from fdai.core.detection.configuration_review import ConfigurationReviewCampaignStore
from fdai.delivery.configuration_review_store import configuration_review_campaign_id
from fdai.delivery.operator_api.application.conversation.capabilities.configuration_drift import (
    ConfigurationDriftChatTools,
)


class ConfigurationBaselinesPanel:
    """Project one server-pinned baseline without exposing mutation controls."""

    path = "/configuration-baselines"
    name = "configuration-baselines"

    def __init__(
        self,
        context: ConfigurationDriftChatTools,
        *,
        review_store: ConfigurationReviewCampaignStore | None = None,
    ) -> None:
        self._context = context
        self._review_store = review_store

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        baseline = await self._context.baseline_source.load()
        report = await self._context.service.run()
        counts = Counter(finding.drift_type.value for finding in report.findings)
        performance = report.performance.to_dict() if report.performance is not None else None
        campaign = (
            None
            if self._review_store is None
            else await self._review_store.get(
                configuration_review_campaign_id(scope=baseline.scope, version=baseline.version)
            )
        )
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
            "versions": _version_history(baseline, self._context.baseline_registry),
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
                "configured": campaign is not None,
                "state": campaign.state.value if campaign is not None else "not-configured",
                "completed_runs": len(campaign.runs) if campaign is not None else 0,
                "required_runs": campaign.required_successes if campaign is not None else 3,
                "failed_attempts": len(campaign.failed_attempts) if campaign is not None else 0,
            },
        }


def _version_history(
    active: FrozenConfigurationBaseline,
    registry: ConfigurationBaselineRegistry | None,
) -> list[dict[str, Any]]:
    if registry is None:
        return []
    records = sorted(
        registry.list(scope=active.scope),
        key=lambda record: (record.baseline.created_at, record.baseline.version),
        reverse=True,
    )
    history: list[dict[str, Any]] = []
    for record in records:
        candidate = record.baseline
        comparison = compare_configuration(
            active,
            ConfigurationObservation(
                scope=active.scope,
                observed_at=candidate.created_at,
                source=f"configuration baseline {candidate.version}",
                completeness=(
                    EvidenceCompleteness.PARTIAL
                    if candidate.unknown_items
                    else EvidenceCompleteness.COMPLETE
                ),
                resources=candidate.resources,
                links=candidate.links,
            ),
        )
        counts = Counter(finding.drift_type.value for finding in comparison.findings)
        verdict = (
            DriftVerdict.BLOCKED.value
            if candidate.unknown_items and comparison.verdict is DriftVerdict.PASSED
            else comparison.verdict.value
        )
        history.append(
            {
                "version": candidate.version,
                "sha256": candidate.sha256,
                "status": record.status.value,
                "created_at": candidate.created_at.isoformat(),
                "resource_count": len(candidate.resources),
                "topology_count": len(candidate.links),
                "unknown_count": len(candidate.unknown_items),
                "comparison": {
                    "baseline_version": active.version,
                    "verdict": verdict,
                    "finding_count": len(comparison.findings),
                    "counts": dict(sorted(counts.items())),
                },
            }
        )
    return history


__all__ = ["ConfigurationBaselinesPanel"]
