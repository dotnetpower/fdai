"""Project active Azure inventory controls into the durable report feed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.report_feed.models import ReportSignal
from fdai.delivery.azure.security_posture import (
    AzureResourceSecurityEvidence,
    analyze_azure_inventory_security,
    controls_to_report_signals,
)
from fdai.shared.providers.inventory import ResourceRecord


@runtime_checkable
class SecurityInventoryReader(Protocol):
    async def list_security_resources(self) -> Sequence[ResourceRecord]:
        """Return the bounded active AKS/node-pool/MySQL inventory."""
        ...


@runtime_checkable
class SecuritySignalWriter(Protocol):
    async def record_many(self, signals: Sequence[ReportSignal]) -> None:
        """Persist idempotent report signals."""
        ...


async def project_azure_security_assessment(
    *,
    reader: SecurityInventoryReader,
    writer: SecuritySignalWriter,
    assessed_at: datetime,
    supplemental: Mapping[str, AzureResourceSecurityEvidence] | None = None,
) -> int:
    """Analyze the active inventory and persist its report signals."""

    resources = await reader.list_security_resources()
    controls = analyze_azure_inventory_security(
        resources,
        assessed_at=assessed_at,
        supplemental=supplemental,
    )
    signals = controls_to_report_signals(controls)
    await writer.record_many(signals)
    return len(signals)


__all__ = [
    "SecurityInventoryReader",
    "SecuritySignalWriter",
    "project_azure_security_assessment",
]
