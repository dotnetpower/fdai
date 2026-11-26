"""Provider-neutral handover compilation ports: inert artifacts, never execution or promotion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Protocol,
)

from fdai_service_contracts import DocumentEnvelope
from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt


class HandoverSemanticSource(Protocol):
    """Read complete, currently admitted normalized envelopes through their own source authority."""

    async def read(self, notice: HandoverKnowledgeNotice) -> tuple[DocumentEnvelope, ...]:
        """Recheck acceptance, identity, ACL, source versions, purposes, and original retention."""
        ...


class HandoverSemanticPackageStore(Protocol):
    """Private source-ACL-bound package persistence; never a general state or event text field."""

    async def claim(self, key: str, identity: Mapping[str, Any]) -> bool:
        """Reserve before model I/O; an interrupted claim cannot retry."""
        ...

    async def read(self, key: str) -> Mapping[str, Any] | None:
        """Read the exact retained attempt, with no cross-package prefix scan."""
        ...

    async def complete(
        self, key: str, identity: Mapping[str, Any], package: Mapping[str, Any]
    ) -> None:
        """Close only this original claim atomically with audit; a changed replay is a conflict."""
        ...

    async def reconcile(self, notice: HandoverKnowledgeNotice, *, withdrawn: bool) -> int:
        """Apply bounded current-source retention without deleting claim or audit identity."""
        ...


class HandoverSemanticCompiler(Protocol):
    """Norns-only off-path candidate extraction; exact receipts are content-free and inert."""

    async def compile(self, notice: HandoverKnowledgeNotice) -> HandoverSemanticReceipt:
        """Compile admitted sources into a bounded package or explicit unavailable outcome."""
        ...


class HandoverSemanticReviewer(Protocol):
    """Mimir-only deterministic package verification with an independent current source read."""

    async def review(
        self,
        notice: HandoverKnowledgeNotice,
        receipt: HandoverSemanticReceipt,
    ) -> HandoverSemanticReceipt:
        """Recompile retained candidates and source evidence without a model call or activation."""
        ...

    async def maintain(self, notice: HandoverKnowledgeNotice, *, withdrawn: bool) -> int:
        """Recheck source-private retention through Mimir's existing candidate consumer."""
        ...


__all__ = [
    "HandoverSemanticCompiler",
    "HandoverSemanticPackageStore",
    "HandoverSemanticReviewer",
    "HandoverSemanticSource",
]
