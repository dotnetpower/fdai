"""Content-addressed proof of a command committed with its case revision."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssignmentCommandReceipt:
    """Bind replay to the whole authenticated request, not a coincident review timestamp."""

    proposal_id: str
    request_digest: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-f0-9]{64}", self.request_digest) is None:
            raise ValueError("assignment command digest MUST be SHA-256")
        if self.proposal_id != f"operator-{self.request_digest[:32]}":
            raise ValueError("assignment command identity MUST match its digest")

    def to_dict(self) -> dict[str, str]:
        """Return the inert identity retained in the atomic case snapshot."""
        return {"proposal_id": self.proposal_id, "request_digest": self.request_digest}


__all__ = ["AssignmentCommandReceipt"]
