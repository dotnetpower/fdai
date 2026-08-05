"""Internal result contract for deterministic answer verification handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerificationStatus = Literal["verified", "consistent", "corrected", "unverified"]


@dataclass(frozen=True, slots=True)
class VerificationPayload:
    """Dependency-free result returned by extracted verification branches."""

    status: VerificationStatus
    answer: str
    authority: str
    checks_completed: int
    checks_total: int
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None
