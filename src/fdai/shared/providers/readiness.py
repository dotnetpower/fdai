"""Provider seams for operational-readiness assessment and delivery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from fdai.shared.providers.projection import Finding


@runtime_checkable
class PostureAssessmentProvider(Protocol):
    """Return grounded assurance-twin findings for one bounded scope."""

    async def findings_for_scope(self, scope: str) -> Sequence[Finding]:
        """Evaluate the current scope projection without mutating it."""
        ...


@runtime_checkable
class ReadinessReportPublisher(Protocol):
    """Deliver a serialized readiness report to a read-only surface."""

    async def publish_readiness_report(self, report: Mapping[str, Any]) -> None:
        """Publish one report or raise so the caller records delivery failure."""
        ...


__all__ = ["PostureAssessmentProvider", "ReadinessReportPublisher"]
