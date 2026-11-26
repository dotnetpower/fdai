"""Shared value types for human-approval escalation routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EscalationDuty(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"
    ESCALATION = "escalation"
    MAINTAINER = "maintainer"


@dataclass(frozen=True, slots=True)
class EscalationRung:
    subject_ref: str
    duty: EscalationDuty
    minimum_role: str = "Approver"

    def __post_init__(self) -> None:
        if not self.subject_ref.strip() or len(self.subject_ref) > 256:
            raise ValueError("escalation subject_ref MUST be non-empty and bounded")
        if self.minimum_role not in {"Approver", "Owner"}:
            raise ValueError("escalation minimum_role MUST be Approver or Owner")


__all__ = ["EscalationDuty", "EscalationRung"]
