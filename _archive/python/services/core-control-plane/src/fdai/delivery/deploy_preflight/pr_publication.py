"""Fail-closed preflight refresh immediately before a remediation PR publish.

The caller supplies a read-only refresh that re-renders and re-analyzes the
exact proposed patch. This delivery wrapper does not approve, execute, or open
a PR itself; only a verified report reaches the injected publisher.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from fdai.core.deploy_preflight.report import DeploymentReadinessReport, ReadinessVerdict
from fdai.shared.providers.feasibility_probe import ProbeCategory
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)

_MAX_FUTURE_SKEW_SECONDS = 60.0
_MAX_CATEGORIES = len(ProbeCategory)


@dataclass(frozen=True, slots=True)
class RefreshedPreflight:
    """Read-only refresh result bound to the exact rendered PR patch.

    The refresh implementation must re-render and re-probe after the last
    source or Inventory change. An old report with a newly computed patch
    digest is not fresh evidence.
    """

    report: DeploymentReadinessReport
    patch_sha256: str


PreflightRefresh = Callable[[RemediationPr], Awaitable[RefreshedPreflight]]


class PreflightHoldReason(StrEnum):
    UNAVAILABLE = "unavailable"
    PATCH_DRIFT = "patch_drift"
    SCOPE_DRIFT = "scope_drift"
    STALE_EVIDENCE = "stale_evidence"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    BLOCKING_FINDING = "blocking_finding"
    INVALID_REPORT = "invalid_report"


class PreflightPublicationHoldError(RuntimeError):
    """Content-free denial; the executor's existing lifecycle records failure."""

    def __init__(self, reason: PreflightHoldReason) -> None:
        self.reason = reason
        super().__init__(f"preflight publication held: {reason.value}")

    def to_dict(self) -> dict[str, str]:
        return {"decision": "human_review", "hold": self.reason.value}


def _age_seconds(report: DeploymentReadinessReport, now: datetime) -> float | None:
    try:
        captured_at = datetime.fromisoformat(report.generated_at)
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            return None
        return (now - captured_at).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return None


class PreflightVerifiedPrPublisher:
    """Decorate an existing PR publisher without changing its authority.

    ``expected_scope`` and ``required_categories`` come from the caller's
    trusted deployment context, not from the PR body or a model response.
    A missing refresh or partial probe set cannot authorize publication.
    """

    def __init__(
        self,
        *,
        publisher: RemediationPrPublisher,
        refresh: PreflightRefresh | None,
        expected_scope: str,
        required_categories: frozenset[ProbeCategory],
        max_age_seconds: float = 900.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not expected_scope or expected_scope != expected_scope.strip():
            raise ValueError("expected_scope must be a normalized non-empty scope")
        if not required_categories or len(required_categories) > _MAX_CATEGORIES:
            raise ValueError("required_categories must be a non-empty probe set")
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive")
        self._publisher = publisher
        self._refresh = refresh
        self._scope = expected_scope
        self._required = required_categories
        self._max_age = max_age_seconds
        self._clock = clock

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        """Re-probe once per attempt, including redelivery of an existing PR.

        A failed or unavailable refresh leaves the underlying PR publisher
        untouched. The delegate retains its own remote idempotency and audit
        lifecycle; this wrapper does not cache an earlier clearance.
        """

        if self._refresh is None:
            raise PreflightPublicationHoldError(PreflightHoldReason.UNAVAILABLE)
        frozen = replace(pr, metadata=MappingProxyType(dict(pr.metadata)))
        try:
            refreshed = await self._refresh(frozen)
        except Exception:
            raise PreflightPublicationHoldError(PreflightHoldReason.UNAVAILABLE) from None
        if not isinstance(refreshed, RefreshedPreflight):
            raise PreflightPublicationHoldError(PreflightHoldReason.UNAVAILABLE)
        digest = hashlib.sha256(frozen.patch.encode("utf-8")).hexdigest()
        if refreshed.patch_sha256 != digest:
            raise PreflightPublicationHoldError(PreflightHoldReason.PATCH_DRIFT)
        report = refreshed.report
        if not isinstance(report, DeploymentReadinessReport):
            raise PreflightPublicationHoldError(PreflightHoldReason.INVALID_REPORT)
        if report.scope != self._scope:
            raise PreflightPublicationHoldError(PreflightHoldReason.SCOPE_DRIFT)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise PreflightPublicationHoldError(PreflightHoldReason.STALE_EVIDENCE)
        age = _age_seconds(report, now)
        if age is None or age < -_MAX_FUTURE_SKEW_SECONDS or age > self._max_age:
            raise PreflightPublicationHoldError(PreflightHoldReason.STALE_EVIDENCE)
        checked_categories = set(report.checked_categories)
        if not self._required.issubset(checked_categories) or any(
            finding.category not in checked_categories for finding in report.findings
        ):
            raise PreflightPublicationHoldError(PreflightHoldReason.INCOMPLETE_COVERAGE)
        if report.blocking_findings:
            raise PreflightPublicationHoldError(PreflightHoldReason.BLOCKING_FINDING)
        if report.verdict not in {ReadinessVerdict.CLEAR, ReadinessVerdict.NEEDS_REVIEW}:
            raise PreflightPublicationHoldError(PreflightHoldReason.INVALID_REPORT)
        if bool(report.findings) != (report.verdict is ReadinessVerdict.NEEDS_REVIEW):
            raise PreflightPublicationHoldError(PreflightHoldReason.INVALID_REPORT)
        if report.scope != self._scope or pr.patch != frozen.patch:
            raise PreflightPublicationHoldError(PreflightHoldReason.PATCH_DRIFT)
        return await self._publisher.publish(frozen)


__all__ = [
    "PreflightHoldReason",
    "PreflightPublicationHoldError",
    "PreflightRefresh",
    "PreflightVerifiedPrPublisher",
    "RefreshedPreflight",
]
