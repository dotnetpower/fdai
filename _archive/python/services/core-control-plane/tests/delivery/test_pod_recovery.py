"""Shared recovery protocol adapter keeps active Finding identity and citations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.investigation.kubernetes_pod_status import POD_STATUS_ASSESSOR
from fdai.delivery.pod_recovery import PodRecoveryAnalyzer
from fdai.shared.contracts.models import Severity

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _prior() -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref="resource:example-pod",
        resource_kind="kubernetes_pod",
        signal="pod_unready",
        observation="Provider observed a Pod that was not Ready.",
        severity=Severity.MEDIUM,
        occurred_at=NOW - timedelta(seconds=10),
        evidence_refs=("pod:prior-example",),
        assessment=FindingAssessment(
            assessed_by=POD_STATUS_ASSESSOR,
            evidence_complete=True,
            recovery_closed=False,
            status="pod_unready",
        ),
    )


async def test_shared_method_carries_prior_finding_reference_and_same_signal() -> None:
    prior = _prior()
    recovered = replace(
        prior,
        occurred_at=NOW,
        evidence_refs=("pod:current-example",),
        assessment=replace(prior.assessment, recovery_closed=True),
    )
    analyzer = SimpleNamespace(assess_recovery=AsyncMock(return_value=recovered))
    result = await PodRecoveryAnalyzer(analyzer).analyze_recovery(
        prior_finding=prior, finding_ref="Finding:example", window_seconds=60
    )
    assert len(result) == 1
    assert result[0].signal == prior.signal
    assert result[0].metadata["prior_finding_ref"] == "Finding:example"
    assert "Finding:example" in result[0].evidence_refs
    analyzer.assess_recovery.assert_awaited_once_with(prior=prior, window_seconds=60)


async def test_incomplete_positive_recovery_does_not_create_a_result() -> None:
    analyzer = SimpleNamespace(assess_recovery=AsyncMock(return_value=None))
    assert (
        await PodRecoveryAnalyzer(analyzer).analyze_recovery(
            prior_finding=_prior(), finding_ref="Finding:example", window_seconds=60
        )
        == ()
    )


@pytest.mark.parametrize(
    "invalid", ["blank_ref", "healthy", "unknown", "foreign", "closed", "uncited"]
)
async def test_recovery_rejects_nonfault_or_unattributed_prior_before_reading(invalid: str) -> None:
    prior = _prior()
    finding_ref = "Finding:example"
    if invalid == "blank_ref":
        finding_ref = ""
    elif invalid == "healthy":
        prior = replace(prior, signal="healthy")
    elif invalid == "unknown":
        prior = replace(
            prior,
            signal="insufficient_evidence",
            assessment=replace(prior.assessment, status="insufficient_evidence"),
        )
    elif invalid == "foreign":
        prior = replace(prior, resource_kind="vm")
    elif invalid == "closed":
        prior = replace(prior, assessment=replace(prior.assessment, recovery_closed=True))
    else:
        prior = replace(prior, evidence_refs=())
    analyzer = SimpleNamespace(assess_recovery=AsyncMock())
    with pytest.raises(ValueError, match="prior actual active Finding"):
        await PodRecoveryAnalyzer(analyzer).analyze_recovery(
            prior_finding=prior, finding_ref=finding_ref, window_seconds=60
        )
    analyzer.assess_recovery.assert_not_awaited()


async def test_ordinary_detection_still_delegates_without_recovery_context() -> None:
    finding = _prior()
    analyzer = SimpleNamespace(analyze=AsyncMock(return_value=(finding,)))
    assert await PodRecoveryAnalyzer(analyzer).analyze(
        resource_ref=finding.resource_ref, window_seconds=60
    ) == (finding,)
