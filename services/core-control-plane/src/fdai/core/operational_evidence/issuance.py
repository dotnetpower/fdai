"""Deterministic verifier engine: readback, receipt, five proofs, gate, and record.

The engine is a non-agent component. It invokes no model, publishes no topic, and never judges,
approves, executes, or promotes. It derives every receipt field from the pinned registry and
from sources it read itself, evaluates the result with the existing readiness gate, and writes
either one admission or one content-free rejection, create-only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.decision_evidence import DecisionCriticalEvidenceReceipt
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
)
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceRejectionClass,
    OperationalEvidenceRejectionRecord,
)

from fdai.core.readiness.decision_evidence import (
    DecisionEvidenceReadinessGate,
    DecisionEvidenceReadinessReason,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)

from .proofs import build_bundle, build_receipt
from .readback.base import (
    ProofLineageReader,
    PurposeReadback,
    ReadbackContext,
    ReadbackFacts,
    ReadbackUnavailableError,
)
from .rejections import (
    ReadbackRejection,
    class_for_claim_reasons,
    class_for_gate_reason,
    reject,
)
from .revision_history import LineageBinding, RegistryHistory, RegistryPins
from .trust_registry import DeploymentAnchors, PurposeTrust, VerifierEntry, purpose_defects

_R = OperationalEvidenceRejectionClass


@dataclass(frozen=True, slots=True)
class VerifierIdentity:
    """The logical verifier identity this workload was deployed as."""

    verifier_id: str
    verifier_version: str


@dataclass(frozen=True, slots=True)
class IssuedEvidence:
    """Everything one admission record retains; it grants eligibility only."""

    attempt_id: str
    lookup_digest: str
    purpose_id: str
    receipt: DecisionCriticalEvidenceReceipt
    bundle: DecisionEvidenceVerificationBundle
    admission: DecisionEvidenceAdmission
    pins: RegistryPins
    binding: LineageBinding
    readback: Mapping[str, object]
    authentication_receipts: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class StoredAttempt:
    """The one outcome already retained for an attempt id."""

    status: OperationalEvidenceIssuanceStatus
    lookup_digest: str
    record_digest: str


class ProofStoreWriter(Protocol):
    """Create-only writer held by the verifier's database role alone."""

    async def attempt_outcome(self, attempt_id: str) -> StoredAttempt | None: ...

    async def write_admission(self, issued: IssuedEvidence) -> str: ...

    async def write_rejection(self, record: OperationalEvidenceRejectionRecord) -> str: ...


class _PreparedBundle:
    """Return the bundle this engine built for exactly one receipt."""

    def __init__(self, bundle: DecisionEvidenceVerificationBundle) -> None:
        self._bundle = bundle

    async def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationBundle:
        if (
            receipt.receipt_digest != self._bundle.receipt_digest
            or trust_anchor_id != self._bundle.trust_anchor_id
        ):
            raise ValueError("prepared verification bundle does not match the receipt")
        return self._bundle


class OperationalEvidenceVerifierEngine:
    """Issue one admission or one typed rejection per bounded attempt."""

    def __init__(
        self,
        *,
        identity: VerifierIdentity,
        history: Callable[[], RegistryHistory | None],
        anchors: DeploymentAnchors,
        readbacks: Sequence[PurposeReadback],
        writer: ProofStoreWriter,
        lineage: ProofLineageReader | None = None,
        clock: Callable[[], datetime] | None = None,
        readback_timeout_seconds: float = 1.5,
        issuance_blocked: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        if not 0 < readback_timeout_seconds <= 5:
            raise ValueError("operational evidence readback timeout MUST be in (0, 5]")
        indexed: dict[str, PurposeReadback] = {}
        for readback in readbacks:
            for purpose in readback.purposes:
                if purpose in indexed:
                    raise ValueError("operational evidence readback purpose is duplicated")
                indexed[purpose] = readback
        self._identity = identity
        self._history = history
        self._anchors = anchors
        self._readbacks = indexed
        self._writer = writer
        self._lineage = lineage
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout = readback_timeout_seconds
        self._blocked = issuance_blocked

    def bound_purposes(self) -> frozenset[str]:
        """Return purposes with an implemented source readback in this workload."""

        return frozenset(self._readbacks)

    @property
    def identity(self) -> VerifierIdentity:
        """Return the logical verifier identity this workload issues under."""

        return self._identity

    def current_pins(self) -> RegistryPins | None:
        """Return the registry pins new records would carry, or nothing without a history."""

        history = self._history()
        return history.current.pins if history is not None else None

    async def issue(
        self,
        request: OperationalEvidenceIssuanceRequest,
        *,
        caller_principal: str,
    ) -> OperationalEvidenceIssuanceResponse:
        """Return a content-free response; outages never write a record."""

        history = self._history()
        readback = self._readbacks.get(request.lookup.purpose_id)
        if history is None or readback is None:
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        if self._blocked is not None and await self._blocked():
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        try:
            stored = await self._writer.attempt_outcome(request.attempt_id)
        except (OSError, RuntimeError, ValueError):
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        if stored is not None:
            # A replayed attempt returns its retained outcome; it is never recomputed with a
            # later clock and never gains a second, different record.
            if stored.lookup_digest != request.lookup.lookup_digest:
                return OperationalEvidenceIssuanceResponse.unavailable(request)
            return OperationalEvidenceIssuanceResponse(
                attempt_id=request.attempt_id,
                lookup_digest=stored.lookup_digest,
                status=stored.status,
                record_digest=stored.record_digest,
            )
        started = _aware(self._clock())
        trust = history.current.trust
        entry = trust.purpose(request.lookup.purpose_id)
        if entry is None or purpose_defects(
            trust,
            self._anchors,
            purpose_id=request.lookup.purpose_id,
            verifier_id=self._identity.verifier_id,
            verifier_version=self._identity.verifier_version,
            at=started,
        ):
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        verifier = entry.version_binding(
            self._identity.verifier_id, self._identity.verifier_version
        )
        if verifier is None or not verifier.window.active_at(started):
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        pins = history.current.pins
        producer = entry.producer(request.producer_id, request.producer_version)
        if producer is None:
            return await self._rejected(
                request, reject(_R.REPLAY_SUBSTITUTED, "producer_not_registered"), pins, verifier
            )
        if self._anchors.principal(producer.anchor_id) != caller_principal:
            return await self._rejected(
                request, reject(_R.REPLAY_SUBSTITUTED, "producer_anchor_mismatch"), pins, verifier
            )
        context = ReadbackContext(
            request=request,
            trust=entry,
            grants=history.current.grants,
            history=history,
            venue=self._anchors.venue,
            read_at=started,
            clock=self._clock,
            lineage=self._lineage,
        )
        try:
            async with asyncio.timeout(self._timeout):
                result = await readback.read(context)
        except (
            ReadbackUnavailableError,
            TimeoutError,
            OSError,
            LookupError,
            TypeError,
            ValueError,
        ):
            # A source that cannot be read, or that failed in an undeclared way, is an outage:
            # no record is written and the owner keeps its generic hold.
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        if isinstance(result, ReadbackRejection):
            return await self._rejected(request, result, pins, verifier)
        return await self._issue_facts(request, entry, verifier, producer.producer_id, result, pins)

    async def _issue_facts(
        self,
        request: OperationalEvidenceIssuanceRequest,
        entry: PurposeTrust,
        verifier: VerifierEntry,
        producer_id: str,
        facts: ReadbackFacts,
        pins: RegistryPins,
    ) -> OperationalEvidenceIssuanceResponse:
        lookup = request.lookup
        if facts.evidence_digest != lookup.evidence_digest:
            return await self._rejected(
                request, reject(_R.REPLAY_SUBSTITUTED, "evidence_mismatch"), pins, verifier
            )
        if facts.source_identity not in entry.authoritative_source_ids():
            return await self._rejected(
                request, reject(_R.SYNTHETIC_LIVE, "source_outside_pinned_anchors"), pins, verifier
            )
        verified_at = _aware(self._clock())
        fresh_until = _aware(facts.evidence_cutoff) + timedelta(
            seconds=entry.freshness.ceiling_seconds
        )
        caps = [fresh_until, verifier.window.valid_until]
        if facts.valid_until_cap is not None:
            caps.append(_aware(facts.valid_until_cap))
        valid_until = min(caps)
        if (
            not _aware(facts.event_at) <= _aware(facts.evidence_cutoff) <= verified_at
            or valid_until <= verified_at
        ):
            return await self._rejected(
                request, reject(_R.STALE, "evidence_not_fresh"), pins, verifier
            )
        receipt = build_receipt(
            request, entry, facts, pins, producer_id=producer_id, recorded_at=verified_at
        )
        bundle = build_bundle(receipt, verifier, verified_at=verified_at, valid_until=valid_until)
        gate = DecisionEvidenceReadinessGate(
            registry=DecisionEvidenceVerifierRegistry(
                (
                    DecisionEvidenceVerifierBinding(
                        authority_class=entry.authority_class,
                        method_id=entry.method_id,
                        verifier_id=verifier.verifier_id,
                        verifier_version=verifier.verifier_version,
                        trust_anchor_id=verifier.trust_anchor_id,
                        verifier=_PreparedBundle(bundle),
                        valid_from=verifier.window.valid_from,
                        valid_until=verifier.window.valid_until,
                    ),
                )
            ),
            timeout_seconds=1.0,
        )
        producer = entry.producer(request.producer_id, request.producer_version)
        if producer is None:  # pragma: no cover - checked before readback
            raise RuntimeError("operational evidence producer disappeared during issuance")
        result = await gate.evaluate(
            receipt,
            entry.requirement(
                scope_digest=lookup.scope_digest,
                producer=producer,
                source_revision=lookup.source_revision,
            ),
            evaluated_at=verified_at,
        )
        if not result.eligible or result.admission is None or result.verification_bundle is None:
            rejection_class = (
                class_for_claim_reasons(result.rejection_details)
                if result.reason is DecisionEvidenceReadinessReason.PREFLIGHT_REJECTED
                else class_for_gate_reason(result.reason)
            )
            if rejection_class is None:
                return OperationalEvidenceIssuanceResponse.unavailable(request)
            return await self._rejected(
                request,
                reject(rejection_class, result.reason.value, *result.rejection_details),
                pins,
                verifier,
            )
        binding = LineageBinding(
            purpose_id=lookup.purpose_id,
            verifier_id=verifier.verifier_id,
            verifier_version=verifier.verifier_version,
            trust_anchor_id=verifier.trust_anchor_id,
            matched_grants=tuple(sorted(set(facts.matched_grants))),
        )
        issued = IssuedEvidence(
            attempt_id=request.attempt_id,
            lookup_digest=lookup.lookup_digest,
            purpose_id=lookup.purpose_id,
            receipt=receipt,
            bundle=result.verification_bundle,
            admission=result.admission,
            pins=pins,
            binding=binding,
            readback={
                "schema_version": "1.0.0",
                "attempt_id": request.attempt_id,
                "lookup_digest": lookup.lookup_digest,
                "purpose_id": lookup.purpose_id,
                "receipt_digest": receipt.receipt_digest,
                "source_identity": facts.source_identity,
                "matched_grants": list(binding.matched_grants),
                "pins_digest": pins.digest,
                "verified_at": verified_at.isoformat(),
            },
            authentication_receipts=facts.authentication_receipts,
        )
        try:
            record_digest = await self._writer.write_admission(issued)
        except (OSError, RuntimeError, ValueError):
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        return OperationalEvidenceIssuanceResponse(
            attempt_id=request.attempt_id,
            lookup_digest=lookup.lookup_digest,
            status=OperationalEvidenceIssuanceStatus.ISSUED,
            record_digest=record_digest,
        )

    async def _rejected(
        self,
        request: OperationalEvidenceIssuanceRequest,
        rejection: ReadbackRejection,
        pins: RegistryPins,
        verifier: VerifierEntry,
    ) -> OperationalEvidenceIssuanceResponse:
        record = OperationalEvidenceRejectionRecord.create(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            purpose_id=request.lookup.purpose_id,
            rejection_class=rejection.rejection_class,
            reason_codes=rejection.reason_codes,
            conflict_evidence_digests=rejection.conflict_evidence_digests,
            trust_registry_pin=pins.trust_pin,
            grant_registry_pin=pins.grant_pin,
            verifier_id=verifier.verifier_id,
            verifier_version=verifier.verifier_version,
            recorded_at=_aware(self._clock()),
        )
        try:
            record_digest = await self._writer.write_rejection(record)
        except (OSError, RuntimeError, ValueError):
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        return OperationalEvidenceIssuanceResponse(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            status=OperationalEvidenceIssuanceStatus.REJECTED,
            record_digest=record_digest,
        )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("operational evidence time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "IssuedEvidence",
    "OperationalEvidenceVerifierEngine",
    "ProofStoreWriter",
    "StoredAttempt",
    "VerifierIdentity",
]
