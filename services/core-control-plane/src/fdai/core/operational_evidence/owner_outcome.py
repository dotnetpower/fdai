"""Owner-side request of independent operational evidence before the unchanged ``admit``.

Boundary owners call ``request_operational_evidence`` as one bounded provider call. It never
raises for an outage: every failure becomes ``unavailable`` so the owner keeps today's generic
hold. A rejected response counts only after the owner re-read the exact rejection record its own
attempt named; a forged or foreign response body therefore degrades to ``unavailable``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionClass,
    OperationalEvidenceRejectionRecord,
)
from pydantic import ValidationError

from fdai.shared.providers.operational_evidence_issuer import (
    OperationalEvidenceIssuer,
    OperationalEvidenceOutcomeReader,
    OperationalEvidenceUnavailableError,
)

_LOGGER = logging.getLogger(__name__)
_EXPECTED_FAILURES = (
    OperationalEvidenceUnavailableError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class OperationalEvidenceRejectedError(PermissionError):
    """A boundary refused an input because the verifier recorded an explicit class."""

    def __init__(self, message: str, *, attempt: OperationalEvidenceAttempt) -> None:
        super().__init__(f"{message}: {attempt.hold_reason('unavailable')}")
        self.attempt = attempt


@dataclass(frozen=True, slots=True)
class OperationalEvidenceAttempt:
    """What one issuance attempt proved to its owner; it never grants authority."""

    status: OperationalEvidenceIssuanceStatus
    rejection: OperationalEvidenceRejectionRecord | None = None

    @property
    def rejection_class(self) -> OperationalEvidenceRejectionClass | None:
        return self.rejection.rejection_class if self.rejection is not None else None

    @property
    def rejection_digest(self) -> str | None:
        return self.rejection.record_digest if self.rejection is not None else None

    def hold_reason(self, generic: str) -> str:
        """Return the owner's reason: the generic hold unless a class was proven."""

        if self.rejection is None:
            return generic
        return f"operational_evidence_{self.rejection.rejection_class.value}"

    def raise_if_rejected(self, message: str) -> None:
        """Refuse with the explicit class; an outage keeps the caller's generic refusal."""

        if self.rejection is not None:
            raise OperationalEvidenceRejectedError(message, attempt=self)


UNAVAILABLE_ATTEMPT = OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.UNAVAILABLE)


class OperationalEvidenceRequester:
    """The issuer, outcome reader, and producer identity one boundary owner is bound to.

    Identical in-flight requests coalesce into one attempt; once an attempt ends, the next
    request starts a fresh attempt, so a rejection is never reused.
    """

    def __init__(
        self,
        *,
        issuer: OperationalEvidenceIssuer,
        outcomes: OperationalEvidenceOutcomeReader,
        producer_id: str,
        producer_version: str,
        timeout_seconds: float = 2.5,
    ) -> None:
        if not 0 < timeout_seconds <= 5:
            raise ValueError("operational evidence request timeout MUST be in (0, 5]")
        self._issuer = issuer
        self._outcomes = outcomes
        self.producer_id = producer_id
        self.producer_version = producer_version
        self._timeout = timeout_seconds
        self._inflight: dict[str, asyncio.Future[OperationalEvidenceAttempt]] = {}

    async def request(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
        locator: Mapping[str, str],
        clock: Callable[[], datetime],
    ) -> OperationalEvidenceAttempt:
        """Request one issuance for the exact tuple the owner will pass to ``admit``."""

        try:
            lookup = OperationalEvidenceLookup(
                evidence_digest=evidence_digest,
                scope_digest=scope_digest,
                purpose_id=purpose_id,
                source_revision=source_revision,
            )
            request = OperationalEvidenceIssuanceRequest(
                attempt_id=uuid4().hex,
                lookup=lookup,
                locator=OperationalEvidenceLocator(
                    purpose_id=purpose_id, coordinates=dict(locator)
                ),
                producer_id=self.producer_id,
                producer_version=self.producer_version,
                requested_at=clock(),
            )
        except (ValidationError, ValueError):
            return UNAVAILABLE_ATTEMPT
        key = request.coalescing_key
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[OperationalEvidenceAttempt] = (
            asyncio.get_running_loop().create_future()
        )
        self._inflight[key] = future
        try:
            attempt = await self._attempt(request, lookup, clock)
            future.set_result(attempt)
            return attempt
        except BaseException:
            if not future.done():
                future.set_result(UNAVAILABLE_ATTEMPT)
            raise
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]

    async def _attempt(
        self,
        request: OperationalEvidenceIssuanceRequest,
        lookup: OperationalEvidenceLookup,
        clock: Callable[[], datetime],
    ) -> OperationalEvidenceAttempt:
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._issuer.issue(request)
                if (
                    not isinstance(response, OperationalEvidenceIssuanceResponse)
                    or response.attempt_id != request.attempt_id
                    or response.lookup_digest != lookup.lookup_digest
                ):
                    return UNAVAILABLE_ATTEMPT
                if response.status is OperationalEvidenceIssuanceStatus.ISSUED:
                    return OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.ISSUED)
                if response.status is not OperationalEvidenceIssuanceStatus.REJECTED:
                    return UNAVAILABLE_ATTEMPT
                record = await self._outcomes.outcome(response, lookup=lookup)
        except _EXPECTED_FAILURES as exc:
            _LOGGER.warning(
                "operational_evidence_request_unavailable",
                extra={"purpose_id": lookup.purpose_id, "error_type": type(exc).__name__},
            )
            return UNAVAILABLE_ATTEMPT
        if (
            not isinstance(record, OperationalEvidenceRejectionRecord)
            or record.record_digest != response.record_digest
            or record.attempt_id != request.attempt_id
            or record.lookup_digest != lookup.lookup_digest
            or record.purpose_id != lookup.purpose_id
            or not record.current_at(clock())
        ):
            return UNAVAILABLE_ATTEMPT
        return OperationalEvidenceAttempt(OperationalEvidenceIssuanceStatus.REJECTED, record)


async def request_operational_evidence(
    requester: OperationalEvidenceRequester | None,
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
    locator: Mapping[str, str],
    clock: Callable[[], datetime] | None = None,
) -> OperationalEvidenceAttempt:
    """Request issuance when a requester is bound; otherwise the attempt is unavailable."""

    if requester is None:
        return UNAVAILABLE_ATTEMPT
    return await requester.request(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=purpose_id,
        source_revision=source_revision,
        locator=locator,
        clock=clock or (lambda: datetime.now(UTC)),
    )


__all__ = [
    "UNAVAILABLE_ATTEMPT",
    "OperationalEvidenceAttempt",
    "OperationalEvidenceRejectedError",
    "OperationalEvidenceRequester",
    "request_operational_evidence",
]
