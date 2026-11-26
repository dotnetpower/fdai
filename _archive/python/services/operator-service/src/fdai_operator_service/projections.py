"""Fail-closed production projection boundary for the extracted Operator routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from fdai_service_contracts import (
    AgentActivityQuery,
    AuditPageProjection,
    AuditQuery,
    BrowserEvidenceQuery,
    BrowserEvidenceWorkspaceQuery,
    HilQueueProjection,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentPageProjection,
    IncidentQuery,
    JsonProjection,
    PageProjection,
)
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class ProjectionUnavailableError(RuntimeError):
    """An authoritative service-local projection adapter is not yet bound."""


async def http_exception_error(_: Request, exc: Exception) -> Response:
    """Normalize recognized projection absence without hiding other HTTP failures."""

    if not isinstance(exc, HTTPException):
        return _error(500, "Operator API request failed")
    detail = exc.detail if isinstance(exc.detail, str) else "Operator API request failed"
    if exc.status_code == 503 and re.fullmatch(
        r"authoritative [A-Za-z][A-Za-z -]{0,63} projection is unavailable"
        r" for [a-z0-9.-]{1,128}",
        detail,
    ):
        detail = "authoritative Operator projection is unavailable"
    return JSONResponse(
        {"error": {"status": exc.status_code, "message": detail}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def projection_unavailable_error(_: Request, __: Exception) -> Response:
    return _error(503, "authoritative Operator projection is unavailable")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


@dataclass(frozen=True, slots=True)
class UnavailableOperatorReadModel:
    """Reject projection reads instead of presenting synthetic or empty live state."""

    reason: str = "authoritative Operator projection adapter is not configured"

    def _raise(self) -> NoReturn:
        raise ProjectionUnavailableError(self.reason)

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        del query
        self._raise()

    async def list_audit(self, query: AuditQuery) -> PageProjection | AuditPageProjection:
        del query
        self._raise()

    async def list_browser_evidence(self, query: BrowserEvidenceQuery) -> JsonProjection:
        del query
        self._raise()

    async def list_browser_evidence_workspace(
        self, query: BrowserEvidenceWorkspaceQuery
    ) -> JsonProjection:
        del query
        self._raise()

    async def dashboard_metrics(self) -> JsonProjection:
        self._raise()

    async def llm_usage(self, range_start: datetime, range_end: datetime) -> JsonProjection:
        del range_start, range_end
        self._raise()

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection:
        del query
        self._raise()

    async def list_incidents(self, query: IncidentQuery) -> IncidentPageProjection:
        del query
        self._raise()

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection | None:
        del query
        self._raise()

    async def get_rca(self, correlation_id: str) -> JsonProjection | None:
        del correlation_id
        self._raise()

    async def get_rule_fire_trace(self, correlation_id: str) -> JsonProjection | None:
        del correlation_id
        self._raise()


__all__ = [
    "ProjectionUnavailableError",
    "UnavailableOperatorReadModel",
    "http_exception_error",
    "projection_unavailable_error",
]
