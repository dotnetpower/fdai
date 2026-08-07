"""Fail-closed production projection boundary for the extracted Operator routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from fdai_service_contracts import (
    AuditQuery,
    HilQueueProjection,
    HilQueueQuery,
    JsonProjection,
    PageProjection,
)


class ProjectionUnavailableError(RuntimeError):
    """An authoritative service-local projection adapter is not yet bound."""


@dataclass(frozen=True, slots=True)
class UnavailableOperatorReadModel:
    """Reject projection reads instead of presenting synthetic or empty live state."""

    reason: str = "authoritative Operator projection adapter is not configured"

    def _raise(self) -> NoReturn:
        raise ProjectionUnavailableError(self.reason)

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        del query
        self._raise()

    async def dashboard_metrics(self) -> JsonProjection:
        self._raise()

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection:
        del query
        self._raise()

    async def list_incidents(self) -> JsonProjection:
        self._raise()

    async def get_rca(self) -> JsonProjection:
        self._raise()

    async def get_rule_fire_trace(self, correlation_id: str) -> JsonProjection | None:
        del correlation_id
        self._raise()


__all__ = ["ProjectionUnavailableError", "UnavailableOperatorReadModel"]
