"""The investigation coordinator's optional hard per-analyzer timeout."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from fdai.core.investigation import (
    KIND_AKS,
    InvestigationCoordinator,
    InvestigationOutcome,
    InvestigationRequest,
)
from fdai.core.investigation.contract import AnalyzerFinding


class _HangingAnalyzer:
    """An analyzer that never returns in time (simulates a wedged backend)."""

    @property
    def resource_kind(self) -> str:
        return KIND_AKS

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        await asyncio.sleep(10)  # far longer than the test's timeout
        return ()  # pragma: no cover - never reached


def _request() -> InvestigationRequest:
    return InvestigationRequest(
        requested_by="op@example.com",
        resources=(("aks-1", KIND_AKS),),
    )


@pytest.mark.asyncio
async def test_hanging_analyzer_times_out_and_marks_partial() -> None:
    coordinator = InvestigationCoordinator(
        analyzers=(_HangingAnalyzer(),),
        analyzer_timeout_seconds=0.01,
    )

    report = await coordinator.investigate(_request())

    assert report.outcome is InvestigationOutcome.PARTIAL
    assert report.analyzer_errors == (("aks-1", "timeout"),)
    assert report.findings == ()


def test_nonpositive_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="analyzer_timeout_seconds"):
        InvestigationCoordinator(analyzers=(), analyzer_timeout_seconds=0.0)
