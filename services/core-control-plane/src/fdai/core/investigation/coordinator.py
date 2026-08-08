"""Investigation coordinator - multi-resource orchestration + budget.

Given a request naming several resources, the coordinator dispatches the
registered :class:`ResourceAnalyzer` for each resource kind, collects the
findings, correlates them into a timeline + root-cause hypothesis, ranks
P1..P3 recommendations, and measures elapsed time against a latency budget
(session notes slide 14: "one investigation ~5 min"). It is **read-only** -
it proposes, the risk gate disposes.

Fail-closed: an analyzer that raises is recorded as an error and the run is
marked :attr:`InvestigationOutcome.PARTIAL`; one bad analyzer never aborts
the whole investigation or fabricates a finding.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.investigation.analyzer import ResourceAnalyzer
from fdai.core.investigation.contract import (
    AnalyzerFinding,
    InvestigationOutcome,
    InvestigationReport,
    TimelineEntry,
    severity_rank,
)
from fdai.core.investigation.recommendations import (
    build_recommendations,
    build_timeline,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_BUDGET_SECONDS = 300.0
_DEFAULT_WINDOW_SECONDS = 3_600.0


@dataclass(frozen=True, slots=True)
class InvestigationRequest:
    """A request to investigate a set of resources.

    ``resources`` is a sequence of ``(resource_ref, resource_kind)`` pairs.
    ``requested_by`` is the operator principal (never anonymous).
    """

    requested_by: str
    resources: tuple[tuple[str, str], ...]
    window_seconds: float = _DEFAULT_WINDOW_SECONDS
    budget_seconds: float = _DEFAULT_BUDGET_SECONDS

    def __post_init__(self) -> None:
        if not self.requested_by:
            raise ValueError("InvestigationRequest.requested_by MUST be non-empty")
        if not self.resources:
            raise ValueError("InvestigationRequest.resources MUST be non-empty")
        if self.budget_seconds <= 0:
            raise ValueError("InvestigationRequest.budget_seconds MUST be positive")


def correlate(timeline: Sequence[TimelineEntry]) -> tuple[tuple[str, ...], str | None]:
    """Derive deterministic correlation statements + a root-cause hypothesis.

    Pure. Statements pair each timeline entry with the next entry on a
    *different* resource ("X preceded Y"). The root cause is the earliest
    of the most-severe findings - the plausible trigger of the chain.
    """
    if not timeline:
        return (), None

    def _desc(entry: TimelineEntry) -> str:
        return f"{entry.severity.value} on {entry.resource_ref} ({entry.description})"

    statements: list[str] = []
    for earlier, later in zip(timeline, timeline[1:], strict=False):
        if earlier.resource_ref == later.resource_ref:
            continue
        delta = (later.occurred_at - earlier.occurred_at).total_seconds()
        statements.append(f"{_desc(earlier)} preceded {_desc(later)} (delta={delta:g}s)")

    most_severe = min(timeline, key=lambda e: (severity_rank(e.severity), e.occurred_at))
    root_cause = (
        f"Likely trigger: {most_severe.description} "
        f"on {most_severe.resource_ref} at {most_severe.occurred_at.isoformat()}"
    )
    return tuple(statements), root_cause


class InvestigationCoordinator:
    """Orchestrate per-resource analyzers into one grounded report."""

    __slots__ = ("_analyzers", "_analyzer_timeout", "_monotonic", "_wall_clock")

    def __init__(
        self,
        *,
        analyzers: Sequence[ResourceAnalyzer],
        monotonic: Callable[[], float] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        analyzer_timeout_seconds: float | None = None,
    ) -> None:
        # Index analyzers by the single resource kind each declares.
        self._analyzers: dict[str, ResourceAnalyzer] = {
            analyzer.resource_kind: analyzer for analyzer in analyzers
        }
        self._monotonic: Callable[[], float] = monotonic or time.monotonic
        self._wall_clock: Callable[[], datetime] = wall_clock or (lambda: datetime.now(tz=UTC))
        if analyzer_timeout_seconds is not None and analyzer_timeout_seconds <= 0:
            raise ValueError("analyzer_timeout_seconds MUST be positive when set")
        self._analyzer_timeout = analyzer_timeout_seconds

    async def investigate(self, request: InvestigationRequest) -> InvestigationReport:
        started = self._monotonic()
        requested_at = self._wall_clock()

        findings: list[AnalyzerFinding] = []
        errors: list[tuple[str, str]] = []
        matched = 0

        for resource_ref, resource_kind in request.resources:
            analyzer = self._analyzers.get(resource_kind)
            if analyzer is None:
                errors.append((resource_ref, f"no_analyzer_for_kind:{resource_kind}"))
                continue
            matched += 1
            try:
                result = await self._run_analyzer(
                    analyzer, resource_ref=resource_ref, window=request.window_seconds
                )
            except TimeoutError:
                errors.append((resource_ref, "timeout"))
                _LOGGER.warning(
                    "analyzer_timeout",
                    extra={"resource_ref": resource_ref, "kind": resource_kind},
                )
                continue
            except Exception as exc:  # noqa: BLE001 - isolate one analyzer failure
                errors.append((resource_ref, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning(
                    "analyzer_failed",
                    extra={"resource_ref": resource_ref, "kind": resource_kind},
                )
                continue
            findings.extend(result)

        timeline = build_timeline(findings)
        correlation, root_cause = correlate(timeline)
        recommendations = build_recommendations(findings)
        elapsed = self._monotonic() - started

        outcome = self._classify(
            matched=matched,
            error_count=len(errors),
            elapsed=elapsed,
            budget=request.budget_seconds,
        )

        return InvestigationReport(
            investigation_id=f"inv-{uuid4().hex[:12]}",
            requested_by=request.requested_by,
            requested_at=requested_at,
            window_seconds=request.window_seconds,
            resources=request.resources,
            outcome=outcome,
            findings=tuple(findings),
            timeline=timeline,
            correlation=correlation,
            root_cause=root_cause if findings else None,
            recommendations=recommendations,
            elapsed_seconds=elapsed,
            budget_seconds=request.budget_seconds,
            analyzer_errors=tuple(errors),
        )

    async def _run_analyzer(
        self, analyzer: ResourceAnalyzer, *, resource_ref: str, window: float
    ) -> Sequence[AnalyzerFinding]:
        """Run one analyzer, enforcing the hard timeout when configured.

        Without a timeout a hanging metric backend would block the whole
        investigation indefinitely; ``asyncio.wait_for`` bounds it and the
        caller records a ``timeout`` error (-> PARTIAL).
        """
        coro = analyzer.analyze(resource_ref=resource_ref, window_seconds=window)
        if self._analyzer_timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=self._analyzer_timeout)

    @staticmethod
    def _classify(
        *, matched: int, error_count: int, elapsed: float, budget: float
    ) -> InvestigationOutcome:
        if matched == 0:
            return InvestigationOutcome.ABSTAINED
        if elapsed > budget:
            return InvestigationOutcome.BUDGET_EXCEEDED
        if error_count > 0:
            return InvestigationOutcome.PARTIAL
        return InvestigationOutcome.COMPLETED


__all__ = [
    "InvestigationCoordinator",
    "InvestigationRequest",
    "correlate",
]
