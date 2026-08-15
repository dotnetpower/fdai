"""Analyzer tick - publish reference-analyzer findings as canonical Events.

The scheduled analyzer job drives the reference threshold analyzers out of band
and turns each finding into a normalized :class:`Event` on the event-ingest
topic, so the standard trust router and safety check govern anything that
follows. The tick executes no change of its own.

Idempotency mirrors the scheduler: the key is derived from the resource, the
signal, and the tick's window bucket, so a retried tick republishes the same key
instead of double-firing. A publish failure keeps the finding retryable and is
reported to the caller, which exits non-zero.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.investigation import (
    AnalyzerFinding,
    InvestigationCoordinator,
    InvestigationRequest,
)
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

ANALYZER_EVENT_TOPIC = "aw.observability.events"
ANALYZER_EVENT_SOURCE = "fdai.delivery.analyzer_tick"
DEFAULT_WINDOW_SECONDS = 300


@dataclass(frozen=True, slots=True)
class AnalyzerTarget:
    """One resource the tick investigates."""

    resource_ref: str
    resource_kind: str

    def __post_init__(self) -> None:
        if not self.resource_ref.strip():
            raise ValueError("AnalyzerTarget.resource_ref MUST be non-empty")
        if not self.resource_kind.strip():
            raise ValueError("AnalyzerTarget.resource_kind MUST be non-empty")


@dataclass(frozen=True, slots=True)
class AnalyzerTickReport:
    """Outcome of one tick."""

    targets: int
    findings: int
    published: int
    unsupported_targets: tuple[str, ...] = ()
    analyzer_errors: tuple[tuple[str, str], ...] = ()
    publish_errors: tuple[tuple[str, str], ...] = ()

    @property
    def failed(self) -> bool:
        """True when the tick must report a non-zero result to its caller."""
        return bool(self.publish_errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "targets": self.targets,
            "findings": self.findings,
            "published": self.published,
            "unsupported_targets": list(self.unsupported_targets),
            "analyzer_errors": [list(item) for item in self.analyzer_errors],
            "publish_errors": [list(item) for item in self.publish_errors],
        }


def analyzer_idempotency_key(
    finding: AnalyzerFinding,
    *,
    at: datetime,
    window_seconds: int,
) -> str:
    """Return a stable key per resource, signal, and window bucket."""
    bucket = int(at.timestamp() // window_seconds)
    return f"analyzer:{finding.resource_ref}:{finding.signal}:{bucket}"


class AnalyzerTickRunner:
    """Run one analyzer pass and publish its findings."""

    __slots__ = ("_bus", "_clock", "_coordinator", "_mode", "_topic", "_window_seconds")

    def __init__(
        self,
        *,
        coordinator: InvestigationCoordinator,
        event_bus: EventBus,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        topic: str = ANALYZER_EVENT_TOPIC,
        mode: Mode = Mode.SHADOW,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds MUST be positive")
        self._coordinator = coordinator
        self._bus = event_bus
        self._window_seconds = window_seconds
        self._topic = topic
        self._mode = mode
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(self, targets: Sequence[AnalyzerTarget]) -> AnalyzerTickReport:
        """Investigate every target and publish one Event per finding."""
        if not targets:
            return AnalyzerTickReport(targets=0, findings=0, published=0)

        at = self._clock()
        report = await self._coordinator.investigate(
            InvestigationRequest(
                requested_by=ANALYZER_EVENT_SOURCE,
                resources=tuple((item.resource_ref, item.resource_kind) for item in targets),
                window_seconds=self._window_seconds,
            )
        )
        unsupported = tuple(
            resource_ref
            for resource_ref, error in report.analyzer_errors
            if error.startswith("no_analyzer_for_kind:")
        )
        analyzer_errors = tuple(
            (resource_ref, error)
            for resource_ref, error in report.analyzer_errors
            if not error.startswith("no_analyzer_for_kind:")
        )

        published = 0
        publish_errors: list[tuple[str, str]] = []
        for finding in report.findings:
            event = self._build_event(finding, at=at)
            try:
                await self._bus.publish(
                    self._topic,
                    finding.resource_ref,
                    event.model_dump(mode="json"),
                )
            except Exception as exc:  # noqa: BLE001 - one bad finding must not silence the rest
                publish_errors.append((event.idempotency_key, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning(
                    "analyzer_publish_failed",
                    extra={"idempotency_key": event.idempotency_key, "error": str(exc)},
                )
                continue
            published += 1

        return AnalyzerTickReport(
            targets=len(targets),
            findings=len(report.findings),
            published=published,
            unsupported_targets=unsupported,
            analyzer_errors=analyzer_errors,
            publish_errors=tuple(publish_errors),
        )

    def _build_event(self, finding: AnalyzerFinding, *, at: datetime) -> Event:
        if finding.occurred_at.tzinfo is None:
            raise ValueError(
                f"analyzer finding {finding.signal!r} carries a naive occurred_at; "
                "a provider MUST return timezone-aware timestamps"
            )
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=analyzer_idempotency_key(
                finding, at=at, window_seconds=self._window_seconds
            ),
            source=ANALYZER_EVENT_SOURCE,
            event_type=f"analyzer.{finding.signal}.observed",
            resource_ref=finding.resource_ref,
            payload={
                "resource_kind": finding.resource_kind,
                "signal": finding.signal,
                "observation": finding.observation,
                "severity": finding.severity.value,
                "evidence_refs": list(finding.evidence_refs),
                "remediation_ref": finding.remediation_ref,
                "window_seconds": self._window_seconds,
                "metadata": dict(finding.metadata),
            },
            detected_at=finding.occurred_at,
            ingested_at=at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=self._mode,
        )


__all__ = [
    "ANALYZER_EVENT_SOURCE",
    "ANALYZER_EVENT_TOPIC",
    "DEFAULT_WINDOW_SECONDS",
    "AnalyzerTarget",
    "AnalyzerTickReport",
    "AnalyzerTickRunner",
    "analyzer_idempotency_key",
]
