"""Read exact worker-produced report-line drafts through a StateStore projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import ReportingLineDraftArtifact

from fdai.shared.providers.state_store import StateStore


class ReportingLineDraftReader(Protocol):
    """Read one exact immutable document-derived report-line artifact."""

    async def get(self, upload_id: UUID) -> ReportingLineDraftArtifact: ...


@dataclass(frozen=True, slots=True)
class StateStoreReportingLineDraftReader:
    """Read the worker projection without document or graph mutation authority."""

    store: StateStore

    async def get(self, upload_id: UUID) -> ReportingLineDraftArtifact:
        value = await self.store.read_state(f"report_line_draft:{upload_id}")
        if value is None:
            raise ValueError("reporting-line draft source is unavailable")
        return ReportingLineDraftArtifact.model_validate(dict(value))


__all__ = ["ReportingLineDraftReader", "StateStoreReportingLineDraftReader"]
