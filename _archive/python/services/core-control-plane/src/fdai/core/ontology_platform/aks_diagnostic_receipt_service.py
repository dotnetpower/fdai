"""Assess and persist one exact-target AKS diagnostic evidence receipt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fdai.core.ontology_platform.kubernetes_diagnostic_assessment import (
    AksDiagnosticContext,
    AksDiagnosticEvidenceReceipt,
    assess_aks_diagnostic,
)


class AksDiagnosticReceiptWriter(Protocol):
    """Append immutable diagnostic evidence without granting authority."""

    async def append(
        self,
        receipt: AksDiagnosticEvidenceReceipt,
    ) -> AksDiagnosticEvidenceReceipt:
        """Persist or return the identical receipt already bound to its identity."""

        ...


@dataclass(frozen=True, slots=True)
class AksDiagnosticReceiptService:
    """Application service for deterministic assessment and durable evidence."""

    writer: AksDiagnosticReceiptWriter

    async def assess_and_persist(
        self,
        context: AksDiagnosticContext,
    ) -> AksDiagnosticEvidenceReceipt:
        """Assess typed evidence and persist its no-authority receipt."""

        return await self.writer.append(assess_aks_diagnostic(context))


__all__ = ["AksDiagnosticReceiptService", "AksDiagnosticReceiptWriter"]
