from collections.abc import Sequence
from datetime import UTC, datetime

from fdai.core.investigation import (
    InvestigationCoordinator,
    InvestigationOutcome,
    InvestigationRequest,
)
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricProviderError


class CpuUnavailable:
    resource_kind = "virtual_machine"

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        raise MetricProviderError("CPU metric source unavailable")


class AvailabilityObserved:
    resource_kind = "virtual_machine"

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        return (
            AnalyzerFinding(
                resource_ref=resource_ref,
                resource_kind=self.resource_kind,
                signal="resource_availability",
                observation="Observed VM is stopped.",
                severity=Severity.HIGH,
                occurred_at=datetime.now(UTC),
                evidence_refs=("inventory:observed-stop",),
            ),
        )


async def test_same_kind_detectors_do_not_overwrite_or_hide_independent_findings() -> None:
    coordinator = InvestigationCoordinator(analyzers=(CpuUnavailable(), AvailabilityObserved()))
    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="test:observer",
            resources=(("resource:vm", "virtual_machine"),),
            window_seconds=300,
        )
    )
    assert len(report.findings) == 1
    assert report.findings[0].signal == "resource_availability"
    assert len(report.analyzer_errors) == 1
    assert report.outcome == InvestigationOutcome.PARTIAL
