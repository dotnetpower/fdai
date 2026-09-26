"""Principal-scoped current-evidence observations for semantic runtime readiness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts.ontology_query import EvidenceAuthority

from .session import Principal


@dataclass(frozen=True, slots=True)
class SemanticCurrentEvidenceObservation:
    """Bounded evidence that one runtime function completed for one principal scope."""

    function_name: str
    complete: bool
    authority: EvidenceAuthority
    principal_scope_digest: str
    incomplete_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.function_name.strip():
            raise ValueError("semantic evidence function_name MUST be non-empty")
        if self.complete and self.incomplete_reason is not None:
            raise ValueError("complete semantic evidence MUST NOT carry an incomplete reason")
        if (
            self.incomplete_reason is not None
            and re.fullmatch(
                r"[a-z0-9][a-z0-9_+.-]{0,255}",
                self.incomplete_reason,
            )
            is None
        ):
            raise ValueError("semantic evidence incomplete reason MUST be a bounded machine token")
        if (
            len(self.principal_scope_digest) != 71
            or not self.principal_scope_digest.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in self.principal_scope_digest[7:]
            )
        ):
            raise ValueError("semantic evidence principal scope MUST be a SHA-256 digest")


class SemanticCurrentEvidenceProbe(Protocol):
    """Exercise one exact registered read function for an authenticated principal."""

    async def observe(
        self,
        *,
        function_name: str,
        principal: Principal,
    ) -> SemanticCurrentEvidenceObservation: ...


__all__ = [
    "SemanticCurrentEvidenceObservation",
    "SemanticCurrentEvidenceProbe",
]
