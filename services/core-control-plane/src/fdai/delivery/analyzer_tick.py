"""Analyzer tick - publish reference-analyzer findings as canonical Events.

The scheduled analyzer job drives the reference threshold analyzers out of band
and turns each finding into a normalized :class:`Event` on the event-ingest
topic, so the standard trust router and safety check govern anything that
follows. The tick executes no change of its own.

Idempotency mirrors the scheduler: the key is derived from the resource, the
signal, and the tick's window bucket, and the event id is a stable UUID over
that key. A durable claim suppresses repeated publication across loop ticks and
scheduled Job restarts.

Publication has three outcomes, not two. Before it sends, the tick durably
records its send intent; that record is what makes a later retry answerable.

- A failure the bus proves happened before the send
  (:class:`~fdai.shared.providers.event_bus.EventPublishNotAttemptedError`) releases
  the claim, because no record can exist downstream.
- Any other broker or transport failure is uncertain. The claim is preserved
  and marked uncertain instead of released, so no tick republishes a record
  that may already have been accepted.
- A broker acknowledgement whose receipt could not be persisted is uncertain in
  the same way. Its send-intent record survives, so lease expiry resolves to
  reconciliation rather than to an automatic republication.

An uncertain key is never republished on lease expiry alone. The tick asks the
bound :class:`AnalyzerPublicationReconciler` whether the stable event id was
accepted downstream: an accepted event completes the claim and suppresses the
repeat, a provably absent event releases the claim for one retry, and an
unavailable or failing reconciler fails that finding closed. A deployment
without a reconciler therefore stalls one uncertain key instead of emitting a
duplicate.

The claim is authoritative, so an unreadable or unwritable claim never becomes
an implicit permission to publish. A claim-store failure fails that finding
closed without publishing and an active claim owned by another tick fails
closed.
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
from fdai.shared.providers.event_bus import (
    EventBus,
    EventPublishNotAttemptedError,
    PublishReceipt,
)

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
    RECONCILED_DUPLICATE = "reconciled_duplicate"
    UNCERTAIN = "publish_uncertain"
    AWAITING_RECONCILIATION = "awaiting_reconciliation"
    FAILED = "failed"


class AnalyzerPublicationClaimStatus(StrEnum):
    """State returned by the durable publication ledger."""

    NEW = "new"
    """This tick owns a fresh claim and has attempted no send."""

    SENDING = "sending"
    """This tick owns the claim and has durably recorded a send attempt."""

    IN_PROGRESS = "in_progress"
    """Another tick owns an unexpired claim for the same key."""

    COMPLETED = "completed"
    """A broker acknowledgement for this key is durably recorded."""

    UNCERTAIN = "uncertain"
    """A previous attempt MAY have reached the broker; reconcile before retry."""


@dataclass(frozen=True, slots=True)
class AnalyzerPublicationClaim:
    """One token-owned publication claim or completed broker receipt.

    ``record`` carries the exact durable representation the ledger read, so
    every later transition is a compare-and-set against the state this tick
    actually observed rather than against an assumed one.
    """

    status: AnalyzerPublicationClaimStatus
    token: str | None = None
    claimed_at: datetime | None = None
    receipt: PublishReceipt | None = None
    record: Mapping[str, Any] | None = None

    @property
    def owned(self) -> bool:
        """True when this tick may act on the claim."""
        return self.status in {
            AnalyzerPublicationClaimStatus.NEW,
            AnalyzerPublicationClaimStatus.SENDING,
        }


@dataclass(frozen=True, slots=True)
class AnalyzerFindingReceipt:
    """Join timing, evidence, publication, and recovery for one finding.

    ``evidence_complete`` and ``recovery_closed`` are copied from the typed
    assessment a canonical reducer produced. A finding without one carries no
    completeness or recovery claim at all, because a receipt that inferred one
    from free-form analyzer text would report a conclusion nothing verified.
    """

    idempotency_key: str
    signal: str
    detection_latency_seconds: float
    evidence_complete: bool
    publication: AnalyzerPublicationStatus
    recovery_closed: bool | None
    evidence_refs: tuple[str, ...]
    assessed_by: str | None = None
    evidence_gaps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "idempotency_key": self.idempotency_key,
            "signal": self.signal,
            "detection_latency_seconds": self.detection_latency_seconds,
            "evidence_complete": self.evidence_complete,
            "publication": self.publication.value,
            "recovery_closed": self.recovery_closed,
            "evidence_refs": list(self.evidence_refs),
            "assessed_by": self.assessed_by,
            "evidence_gaps": list(self.evidence_gaps),
        }


class AnalyzerPublicationLedger(Protocol):
    """Durable first-writer guard for analyzer event publication."""

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        """Claim the key or return its active, completed, or uncertain state."""
        ...

    async def mark_sending(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> AnalyzerPublicationClaim:
        """Durably record the send intent before the record leaves this process.

        The returned claim owns the send-intent record. A crash after this
        write leaves a key whose outcome is unknown, which is the honest
        state: the alternative would let lease expiry republish a record the
        broker may already hold.
        """
        ...

    async def mark_uncertain(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        reason: str,
    ) -> AnalyzerPublicationClaim:
        """Record that this key's send outcome is unknown."""
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
        *,
        provably_unsent: bool = False,
    ) -> None:
        """Release a claim whose record provably never reached the broker.

        ``provably_unsent`` is the caller's attestation that the bus reported a
        strictly pre-send failure. A recorded send intent is releasable only
        with that attestation, so an ambiguous transport error can never take
        the same path by accident.
        """
        ...


class AnalyzerPublicationReconciler(Protocol):
    """Answer whether one stable event id was already accepted downstream."""

    async def reconcile(
        self,
        *,
        event_id: UUID,
        idempotency_key: str,
        topic: str,
    ) -> PublishReceipt | None:
        """Return the acknowledgement for an accepted event, else ``None``.

        ``None`` MUST mean the implementation independently established that
        the event is absent downstream. An implementation that cannot decide
        MUST raise instead, because a guess here becomes either a duplicate
        publication or a lost finding.
        """
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
    uncertain: int = 0
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
            "uncertain": self.uncertain,
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
        "_reconciler",
        "_topic",
        "_window_seconds",
    )

    def __init__(
        self,
        *,
        coordinator: InvestigationCoordinator,
        event_bus: EventBus,
        publication_ledger: AnalyzerPublicationLedger,
        publication_reconciler: AnalyzerPublicationReconciler | None = None,
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
        self._reconciler = publication_reconciler
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
        uncertain = 0
        publish_errors: list[tuple[str, str]] = []
        receipts: list[AnalyzerFindingReceipt] = []
        for finding in report.findings:
            event = self._build_event(
                finding,
                window_at=window_at,
                ingested_at=self._clock(),
            )
            outcome = await self._publish_finding(finding, event=event)
            if outcome.error is not None:
                publish_errors.append((event.idempotency_key, outcome.error))
            if outcome.status in {
                AnalyzerPublicationStatus.PUBLISHED,
                AnalyzerPublicationStatus.PUBLISHED_RECEIPT_UNRECORDED,
            }:
                published += 1
            elif outcome.status in {
                AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED,
                AnalyzerPublicationStatus.RECONCILED_DUPLICATE,
            }:
                duplicates_suppressed += 1
            elif outcome.status in {
                AnalyzerPublicationStatus.UNCERTAIN,
                AnalyzerPublicationStatus.AWAITING_RECONCILIATION,
            }:
                uncertain += 1
            receipts.append(
                _finding_receipt(
                    finding,
                    event=event,
                    at=self._clock(),
                    publication=outcome.status,
                )
            )

        return AnalyzerTickReport(
            targets=len(targets),
            findings=len(report.findings),
            published=published,
            duplicates_suppressed=duplicates_suppressed,
            uncertain=uncertain,
            unsupported_targets=unsupported,
            analyzer_errors=analyzer_errors,
            publish_errors=tuple(publish_errors),
            receipts=tuple(receipts),
        )

    async def _publish_finding(
        self,
        finding: AnalyzerFinding,
        *,
        event: Event,
    ) -> _PublicationOutcome:
        """Publish one finding at most once, or explain why it did not publish."""

        key = event.idempotency_key
        try:
            claim = await self._publication_ledger.claim(key)
        except Exception as exc:  # noqa: BLE001 - an unreadable claim MUST NOT allow publication
            return _failure(key, "publication_claim", exc, "analyzer_publication_claim_failed")
        if claim.status is AnalyzerPublicationClaimStatus.COMPLETED:
            return _PublicationOutcome(AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED)
        if claim.status is AnalyzerPublicationClaimStatus.IN_PROGRESS:
            return _PublicationOutcome(
                AnalyzerPublicationStatus.FAILED,
                error="RuntimeError:publication_claim_in_progress",
            )
        if claim.status is AnalyzerPublicationClaimStatus.UNCERTAIN:
            reconciled = await self._reconcile(claim, event=event)
            if reconciled.outcome is not None:
                return reconciled.outcome
            claim = reconciled.claim if reconciled.claim is not None else claim
        if not claim.owned:
            return _PublicationOutcome(
                AnalyzerPublicationStatus.FAILED,
                error="RuntimeError:publication_claim_not_owned",
            )
        return await self._send(finding, event=event, claim=claim)

    async def _send(
        self,
        finding: AnalyzerFinding,
        *,
        event: Event,
        claim: AnalyzerPublicationClaim,
    ) -> _PublicationOutcome:
        """Record the send intent, publish, and record the terminal outcome."""

        key = event.idempotency_key
        try:
            sending = await self._publication_ledger.mark_sending(key, claim)
        except Exception as exc:  # noqa: BLE001 - an unrecorded intent MUST NOT be sent
            await self._release_quietly(key, claim)
            return _failure(key, "publication_intent", exc, "analyzer_publication_intent_failed")
        try:
            broker_receipt = await self._bus.publish(
                self._topic,
                finding.resource_ref,
                event.model_dump(mode="json"),
            )
        except EventPublishNotAttemptedError as exc:
            try:
                await self._publication_ledger.release(key, sending, provably_unsent=True)
            except Exception as release_exc:  # noqa: BLE001 - preserve both bounded failures
                error = (
                    f"{type(exc).__name__}:{exc}; "
                    f"claim_release={type(release_exc).__name__}:{release_exc}"
                )
            else:
                error = f"{type(exc).__name__}:{exc}"
            _LOGGER.warning(
                "analyzer_publish_not_attempted",
                extra={"idempotency_key": key, "error": error},
            )
            return _PublicationOutcome(AnalyzerPublicationStatus.FAILED, error=error)
        except Exception as exc:  # noqa: BLE001 - an ambiguous send MUST NOT release its claim
            reason = f"{type(exc).__name__}:{exc}"
            try:
                await self._publication_ledger.mark_uncertain(key, sending, reason=reason)
            except Exception as mark_exc:  # noqa: BLE001 - the send intent already fails closed
                error = (
                    f"publish_uncertain={reason}; "
                    f"claim_uncertain={type(mark_exc).__name__}:{mark_exc}"
                )
            else:
                error = f"publish_uncertain={reason}"
            _LOGGER.warning(
                "analyzer_publish_uncertain",
                extra={"idempotency_key": key, "error": error},
            )
            return _PublicationOutcome(AnalyzerPublicationStatus.UNCERTAIN, error=error)
        try:
            await self._publication_ledger.complete(key, sending, broker_receipt)
        except Exception as exc:  # noqa: BLE001 - broker success and ledger failure both matter
            error = f"publication_receipt={type(exc).__name__}:{exc}"
            _LOGGER.warning(
                "analyzer_publication_receipt_failed",
                extra={"idempotency_key": key, "error": error},
            )
            return _PublicationOutcome(
                AnalyzerPublicationStatus.PUBLISHED_RECEIPT_UNRECORDED,
                error=error,
            )
        return _PublicationOutcome(AnalyzerPublicationStatus.PUBLISHED)

    async def _reconcile(
        self,
        claim: AnalyzerPublicationClaim,
        *,
        event: Event,
    ) -> _ReconciliationOutcome:
        """Resolve one uncertain key through an independent observation."""

        key = event.idempotency_key
        if self._reconciler is None:
            return _ReconciliationOutcome(
                outcome=_PublicationOutcome(
                    AnalyzerPublicationStatus.AWAITING_RECONCILIATION,
                    error="RuntimeError:publication_reconciler_unbound",
                )
            )
        try:
            receipt = await self._reconciler.reconcile(
                event_id=event.event_id,
                idempotency_key=key,
                topic=self._topic,
            )
        except Exception as exc:  # noqa: BLE001 - an undecided key MUST NOT be republished
            return _ReconciliationOutcome(
                outcome=_failure(
                    key,
                    "publication_reconcile",
                    exc,
                    "analyzer_publication_reconcile_failed",
                    status=AnalyzerPublicationStatus.AWAITING_RECONCILIATION,
                )
            )
        if receipt is not None:
            try:
                await self._publication_ledger.complete(key, claim, receipt)
            except Exception as exc:  # noqa: BLE001 - an unrecorded outcome stays uncertain
                return _ReconciliationOutcome(
                    outcome=_failure(
                        key,
                        "publication_reconcile_receipt",
                        exc,
                        "analyzer_publication_reconcile_failed",
                        status=AnalyzerPublicationStatus.AWAITING_RECONCILIATION,
                    )
                )
            _LOGGER.info(
                "analyzer_publication_reconciled_duplicate",
                extra={"idempotency_key": key, "event_id": str(event.event_id)},
            )
            return _ReconciliationOutcome(
                outcome=_PublicationOutcome(AnalyzerPublicationStatus.RECONCILED_DUPLICATE)
            )
        try:
            await self._publication_ledger.release(key, claim)
            retry = await self._publication_ledger.claim(key)
        except Exception as exc:  # noqa: BLE001 - a half-cleared claim MUST NOT be republished
            return _ReconciliationOutcome(
                outcome=_failure(
                    key,
                    "publication_reconcile_release",
                    exc,
                    "analyzer_publication_reconcile_failed",
                    status=AnalyzerPublicationStatus.AWAITING_RECONCILIATION,
                )
            )
        if retry.status is not AnalyzerPublicationClaimStatus.NEW:
            return _ReconciliationOutcome(
                outcome=_PublicationOutcome(
                    AnalyzerPublicationStatus.FAILED,
                    error="RuntimeError:publication_claim_not_reclaimed",
                )
            )
        return _ReconciliationOutcome(claim=retry)

    async def _release_quietly(
        self,
        key: str,
        claim: AnalyzerPublicationClaim,
    ) -> None:
        """Release a claim whose owner never attempted a send."""

        try:
            await self._publication_ledger.release(key, claim)
        except Exception:  # noqa: BLE001 - the failing store already fails this finding closed
            _LOGGER.warning("analyzer_publication_release_failed", extra={"idempotency_key": key})

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
                "assessment": (
                    finding.assessment.to_dict() if finding.assessment is not None else None
                ),
            },
            detected_at=finding.occurred_at,
            ingested_at=ingested_at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=self._mode,
        )


@dataclass(frozen=True, slots=True)
class _PublicationOutcome:
    """One finding's terminal publication state and its reportable error."""

    status: AnalyzerPublicationStatus
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ReconciliationOutcome:
    """Either a terminal outcome, or the reclaimed claim a retry may use."""

    outcome: _PublicationOutcome | None = None
    claim: AnalyzerPublicationClaim | None = None


def _failure(
    key: str,
    label: str,
    exc: Exception,
    log_event: str,
    *,
    status: AnalyzerPublicationStatus = AnalyzerPublicationStatus.FAILED,
) -> _PublicationOutcome:
    error = f"{label}={type(exc).__name__}:{exc}"
    _LOGGER.warning(log_event, extra={"idempotency_key": key, "error": error})
    return _PublicationOutcome(status, error=error)


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
    assessment = finding.assessment
    return AnalyzerFindingReceipt(
        idempotency_key=event.idempotency_key,
        signal=finding.signal,
        detection_latency_seconds=latency,
        evidence_complete=assessment is not None and assessment.evidence_complete,
        publication=publication,
        recovery_closed=assessment.recovery_closed if assessment is not None else None,
        evidence_refs=finding.evidence_refs,
        assessed_by=assessment.assessed_by if assessment is not None else None,
        evidence_gaps=assessment.evidence_gaps if assessment is not None else (),
    )


__all__ = [
    "ANALYZER_EVENT_SOURCE",
    "ANALYZER_EVENT_TOPIC",
    "DEFAULT_WINDOW_SECONDS",
    "AnalyzerFindingReceipt",
    "AnalyzerPublicationClaim",
    "AnalyzerPublicationClaimStatus",
    "AnalyzerPublicationLedger",
    "AnalyzerPublicationReconciler",
    "AnalyzerPublicationStatus",
    "AnalyzerTarget",
    "AnalyzerTickReport",
    "AnalyzerTickRunner",
    "analyzer_idempotency_key",
]
