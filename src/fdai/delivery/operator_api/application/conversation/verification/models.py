"""Internal result contract for deterministic answer verification handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerificationStatus = Literal["verified", "corrected", "consistent", "unverified"]


@dataclass(frozen=True, slots=True)
class VerificationPayload:
    """Handler result converted into the public answer verification contract."""

    status: VerificationStatus
    answer: str
    authority: str
    checks_completed: int
    checks_total: int
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None
