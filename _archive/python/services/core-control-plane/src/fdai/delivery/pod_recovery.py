"""Adapt Pod status recovery to the shared optional analyzer recovery method."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.investigation.contract import AnalyzerFinding
from fdai.core.investigation.kubernetes_pod_status import (
    POD_STATUS_ASSESSOR,
    POD_STATUS_FAULT_SIGNALS,
    KubernetesPodFailureAnalyzer,
)


class PodRecoveryAnalyzer:
    """Only callers holding an active durable Finding may request recovery."""

    resource_kind = "kubernetes_pod"

    def __init__(self, analyzer: KubernetesPodFailureAnalyzer) -> None:
        self._analyzer = analyzer

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> tuple[AnalyzerFinding, ...]:
        return await self._analyzer.analyze(
            resource_ref=resource_ref, window_seconds=window_seconds
        )

    async def analyze_recovery(
        self,
        *,
        prior_finding: AnalyzerFinding,
        finding_ref: str,
        window_seconds: float,
    ) -> tuple[AnalyzerFinding, ...]:
        if (
            not finding_ref.strip()
            or prior_finding.resource_kind != self.resource_kind
            or prior_finding.signal not in POD_STATUS_FAULT_SIGNALS
            or not prior_finding.evidence_refs
            or prior_finding.assessment is None
            or prior_finding.assessment.assessed_by != POD_STATUS_ASSESSOR
            or prior_finding.assessment.status != prior_finding.signal
            or prior_finding.assessment.recovery_closed is True
        ):
            raise ValueError("Pod status recovery MUST reference a prior actual active Finding")
        recovered = await self._analyzer.assess_recovery(
            prior=prior_finding, window_seconds=window_seconds
        )
        if recovered is None:
            return ()
        return (
            replace(
                recovered,
                evidence_refs=tuple(sorted({*recovered.evidence_refs, finding_ref})),
                metadata={**recovered.metadata, "prior_finding_ref": finding_ref},
            ),
        )
