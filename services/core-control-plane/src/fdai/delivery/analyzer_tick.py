"""Analyzer tick - publish reference-analyzer findings as canonical Events.

The scheduled analyzer job drives the reference threshold analyzers out of band
and turns each finding into a normalized :class:`Event` on the event-ingest
topic, so the standard trust router and safety check govern anything that
follows. The tick executes no change of its own.

Idempotency mirrors the scheduler: the key is derived from the resource, the
signal, and the tick's window bucket. A durable claim suppresses repeated
publication across loop ticks and scheduled Job restarts. A publish failure
releases the claim, keeps the finding retryable, and is reported to the caller,
which exits non-zero.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.investigation import (
    AnalyzerFinding,
    InvestigationCoordinator,
    InvestigationRequest,
)
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus, PublishReceipt

_LOGGER = logging.getLogger(__name__)

ANALYZER_EVENT_TOPIC = "fdai.observability.events"
ANALYZER_EVENT_SOURCE = "fdai.delivery.analyzer_tick"
DEFAULT_WINDOW_SECONDS = 300
_EVENT_ID_NAMESPACE = UUID(int=0)


class AnalyzerPublicationStatus(StrEnum):
    """Terminal publication state for one analyzer finding."""

    PUBLISHED = "published"
    PUBLISHED_RECEIPT_UNRECORDED = "published_receipt_unrecorded"
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"
    FAILED = "failed"


class AnalyzerPublicationClaimStatus(StrEnum):
    """State returned by the durable publication ledger."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AnalyzerPublicationClaim:
    """One token-owned publication claim or completed broker receipt."""

    status: AnalyzerPublicationClaimStatus
    token: str | None = None
    claimed_at: datetime | None = None
    receipt: PublishReceipt | None = None


@dataclass(frozen=True, slots=True)
class AnalyzerFindingReceipt:
    """Join timing, evidence, publication, and recovery for one finding."""

    idempotency_key: str
    signal: str
    detection_latency_seconds: float
    evidence_complete: bool
    publication: AnalyzerPublicationStatus
    recovery_closed: bool | None
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "idempotency_key": self.idempotency_key,
            "signal": self.signal,
            "detection_latency_seconds": self.detection_latency_seconds,
            "evidence_complete": self.evidence_complete,
            "publication": self.publication.value,
            "recovery_closed": self.recovery_closed,
            "evidence_refs": list(self.evidence_refs),
        }


class AnalyzerPublicationLedger(Protocol):
    """Durable first-writer guard for analyzer event publication."""

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        """Claim the key or return its active/completed state."""
        ...

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        """Persist the broker acknowledgement for the claimed key."""
        ...

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> None:
        """Release a failed publication claim so the next tick can retry."""
        ...


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
    duplicates_suppressed: int = 0
    unsupported_targets: tuple[str, ...] = ()
    analyzer_errors: tuple[tuple[str, str], ...] = ()
    publish_errors: tuple[tuple[str, str], ...] = ()
    receipts: tuple[AnalyzerFindingReceipt, ...] = ()

    @property
    def failed(self) -> bool:
        """True when the tick must report a non-zero result to its caller."""
        return bool(self.publish_errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "targets": self.targets,
            "findings": self.findings,
            "published": self.published,
            "duplicates_suppressed": self.duplicates_suppressed,
            "unsupported_targets": list(self.unsupported_targets),
            "analyzer_errors": [list(item) for item in self.analyzer_errors],
            "publish_errors": [list(item) for item in self.publish_errors],
            "receipts": [item.to_dict() for item in self.receipts],
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

    __slots__ = (
        "_bus",
        "_clock",
        "_coordinator",
        "_mode",
        "_publication_ledger",
        "_topic",
        "_window_seconds",
    )

    def __init__(
        self,
        *,
        coordinator: InvestigationCoordinator,
        event_bus: EventBus,
        publication_ledger: AnalyzerPublicationLedger,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        topic: str = ANALYZER_EVENT_TOPIC,
        mode: Mode = Mode.SHADOW,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds MUST be positive")
        self._coordinator = coordinator
        self._bus = event_bus
        self._publication_ledger = publication_ledger
        self._window_seconds = window_seconds
        self._topic = topic
        self._mode = mode
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(self, targets: Sequence[AnalyzerTarget]) -> AnalyzerTickReport:
        """Investigate every target and publish one Event per finding."""
        if not targets:
            return AnalyzerTickReport(targets=0, findings=0, published=0)

        window_at = self._clock()
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
        duplicates_suppressed = 0
        publish_errors: list[tuple[str, str]] = []
        receipts: list[AnalyzerFindingReceipt] = []
        for finding in report.findings:
            event = self._build_event(
                finding,
                window_at=window_at,
                ingested_at=self._clock(),
            )
            claim = await self._publication_ledger.claim(event.idempotency_key)
            if claim.status is AnalyzerPublicationClaimStatus.COMPLETED:
                duplicates_suppressed += 1
                receipts.append(
                    _finding_receipt(
                        finding,
                        event=event,
                        at=self._clock(),
                        publication=AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED,
                    )
                )
                continue
            if claim.status is AnalyzerPublicationClaimStatus.IN_PROGRESS:
                error = "RuntimeError:publication_claim_in_progress"
                publish_errors.append((event.idempotency_key, error))
                receipts.append(
                    _finding_receipt(
                        finding,
                        event=event,
                        at=self._clock(),
                        publication=AnalyzerPublicationStatus.FAILED,
                    )
                )
                continue
            try:
                broker_receipt = await self._bus.publish(
                    self._topic,
                    finding.resource_ref,
                    event.model_dump(mode="json"),
                )
            except Exception as exc:  # noqa: BLE001 - one bad finding must not silence the rest
                try:
                    await self._publication_ledger.release(event.idempotency_key, claim)
                except Exception as release_exc:  # noqa: BLE001 - preserve both bounded failures
                    error = (
                        f"{type(exc).__name__}:{exc}; "
                        f"claim_release={type(release_exc).__name__}:{release_exc}"
                    )
                else:
                    error = f"{type(exc).__name__}:{exc}"
                publish_errors.append((event.idempotency_key, error))
                receipts.append(
                    _finding_receipt(
                        finding,
                        event=event,
                        at=self._clock(),
                        publication=AnalyzerPublicationStatus.FAILED,
                    )
                )
                _LOGGER.warning(
                    "analyzer_publish_failed",
                    extra={"idempotency_key": event.idempotency_key, "error": error},
                )
                continue
            try:
                await self._publication_ledger.complete(
                    event.idempotency_key,
                    claim,
                    broker_receipt,
                )
            except Exception as exc:  # noqa: BLE001 - broker success and ledger failure both matter
                error = f"publication_receipt={type(exc).__name__}:{exc}"
                publish_errors.append((event.idempotency_key, error))
                published += 1
                receipts.append(
                    _finding_receipt(
                        finding,
                        event=event,
                        at=self._clock(),
                        publication=AnalyzerPublicationStatus.PUBLISHED_RECEIPT_UNRECORDED,
                    )
                )
                _LOGGER.warning(
                    "analyzer_publication_receipt_failed",
                    extra={"idempotency_key": event.idempotency_key, "error": error},
                )
                continue
            published += 1
            receipts.append(
                _finding_receipt(
                    finding,
                    event=event,
                    at=self._clock(),
                    publication=AnalyzerPublicationStatus.PUBLISHED,
                )
            )

        return AnalyzerTickReport(
            targets=len(targets),
            findings=len(report.findings),
            published=published,
            duplicates_suppressed=duplicates_suppressed,
            unsupported_targets=unsupported,
            analyzer_errors=analyzer_errors,
            publish_errors=tuple(publish_errors),
            receipts=tuple(receipts),
        )

    def _build_event(
        self,
        finding: AnalyzerFinding,
        *,
        window_at: datetime,
        ingested_at: datetime,
    ) -> Event:
        if finding.occurred_at.tzinfo is None:
            raise ValueError(
                f"analyzer finding {finding.signal!r} carries a naive occurred_at; "
                "a provider MUST return timezone-aware timestamps"
            )
        idempotency_key = analyzer_idempotency_key(
            finding, at=window_at, window_seconds=self._window_seconds
        )
        return Event(
            schema_version="1.0.0",
            event_id=uuid5(_EVENT_ID_NAMESPACE, idempotency_key),
            idempotency_key=idempotency_key,
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
            ingested_at=ingested_at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=self._mode,
        )


def _finding_receipt(
    finding: AnalyzerFinding,
    *,
    event: Event,
    at: datetime,
    publication: AnalyzerPublicationStatus,
) -> AnalyzerFindingReceipt:
    latency = (at - finding.occurred_at).total_seconds()
    if latency < 0:
        raise ValueError(f"analyzer finding {finding.signal!r} occurred after its publication tick")
    return AnalyzerFindingReceipt(
        idempotency_key=event.idempotency_key,
        signal=finding.signal,
        detection_latency_seconds=latency,
        evidence_complete=_metadata_bool(finding.metadata, "evidence_complete") is True,
        publication=publication,
        recovery_closed=_metadata_bool(finding.metadata, "recovery_closed"),
        evidence_refs=finding.evidence_refs,
    )


def _metadata_bool(metadata: Mapping[str, Any], key: str) -> bool | None:
    value = metadata.get(key)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"analyzer finding metadata {key!r} MUST be 'true' or 'false'")


__all__ = [
    "ANALYZER_EVENT_SOURCE",
    "ANALYZER_EVENT_TOPIC",
    "DEFAULT_WINDOW_SECONDS",
    "AnalyzerFindingReceipt",
    "AnalyzerPublicationClaim",
    "AnalyzerPublicationClaimStatus",
    "AnalyzerPublicationLedger",
    "AnalyzerPublicationStatus",
    "AnalyzerTarget",
    "AnalyzerTickReport",
    "AnalyzerTickRunner",
    "analyzer_idempotency_key",
]
