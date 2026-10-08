"""Installation enrollment: a key-proven request that a customer approver accepts or rejects.

Until an approver accepts it, the Hub plans nothing for the installation. An accepted
installation starts with every Entity unmanaged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from fdai_lifecycle_hub.domain import Installation
from fdai_lifecycle_hub.signing import installation_key_id

# How far `requested_at` may be from the Hub's clock, in either direction.
PROOF_CLOCK_WINDOW = timedelta(minutes=5)


class KeyProofVerifier(Protocol):
    def __call__(self, *, public_key: bytes, payload: bytes, signature: bytes) -> bool:
        """Whether the holder of `public_key` signed `payload`."""
        ...


class EnrollmentStatus(StrEnum):
    PENDING = "pending"
    ENROLLED = "enrolled"
    REJECTED = "rejected"


class ProofFailure(StrEnum):
    INVALID = "enrollment_proof_invalid"
    STALE = "enrollment_proof_stale"


@dataclass(frozen=True, slots=True, kw_only=True)
class EnrollmentRequest:
    """A parsed enrollment request and the exact bytes its proof signs."""

    installation: Installation
    installation_key: bytes
    requested_at: datetime
    signed_payload: bytes
    proof: bytes

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")

    @property
    def installation_key_id(self) -> str:
        return installation_key_id(self.installation_key)

    def proof_failure(self, verify: KeyProofVerifier, now: datetime) -> ProofFailure | None:
        """Why the proof fails at `now`, or None when the key's holder signed it recently."""

        if not verify(
            public_key=self.installation_key, payload=self.signed_payload, signature=self.proof
        ):
            return ProofFailure.INVALID
        if abs(now - self.requested_at) > PROOF_CLOCK_WINDOW:
            return ProofFailure.STALE
        return None
