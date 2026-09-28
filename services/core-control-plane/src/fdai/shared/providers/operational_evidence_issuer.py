"""Provider-neutral seam for requesting independent operational evidence issuance.

A boundary owner calls ``OperationalEvidenceIssuer.issue`` as a bounded provider call - never an
agent call - before it calls the unchanged ``DecisionEvidenceAdmissionProvider.admit``. The
response is content-free. Only ``OperationalEvidenceOutcomeReader.outcome`` may turn a rejected
response into a class, and only for the record that exact attempt named.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionRecord,
)


class OperationalEvidenceUnavailableError(RuntimeError):
    """The verifier, a source, the proof store, or a registry cannot answer now."""


class OperationalEvidenceIssuer(Protocol):
    """Ask the independent verifier to read back one exact decision input."""

    def issue(
        self,
        request: OperationalEvidenceIssuanceRequest,
    ) -> Awaitable[OperationalEvidenceIssuanceResponse]: ...


class OperationalEvidenceOutcomeReader(Protocol):
    """Return the rejection record one attempt named, or nothing."""

    def outcome(
        self,
        response: OperationalEvidenceIssuanceResponse,
        *,
        lookup: OperationalEvidenceLookup,
    ) -> Awaitable[OperationalEvidenceRejectionRecord | None]: ...


__all__ = [
    "OperationalEvidenceIssuer",
    "OperationalEvidenceOutcomeReader",
    "OperationalEvidenceUnavailableError",
]
