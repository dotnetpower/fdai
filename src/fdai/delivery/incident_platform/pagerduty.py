"""PagerDuty REST incident read and lifecycle adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.delivery.incident_platform._common import (
    TokenProvider,
    request_json,
    text,
    timestamp,
)
from fdai.shared.providers.incident_platform import (
    ExternalIncident,
    ExternalIncidentStatus,
    IncidentPlatformError,
)


@dataclass(frozen=True, slots=True)
class PagerDutyIncidentPlatformConfig:
    api_base: str = "https://api.pagerduty.com"
    from_email: str = ""
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.api_base.startswith("https://"):
            raise ValueError("PagerDuty incident API base MUST use HTTPS")
        if not self.from_email.strip():
            raise ValueError("PagerDuty incident from_email MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("PagerDuty incident timeout MUST be positive")


class PagerDutyIncidentPlatform:
    def __init__(
        self,
        *,
        config: PagerDutyIncidentPlatformConfig,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final = config
        self._token_provider = token_provider
        self._http = http_client

    async def list_active(self, *, limit: int = 100) -> Sequence[ExternalIncident]:
        _validate_limit(limit)
        payload = await self._request(
            "GET",
            "/incidents",
            params={"limit": limit, "statuses[]": "triggered,acknowledged"},
        )
        rows = payload.get("incidents") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise IncidentPlatformError("PagerDuty incidents payload is malformed")
        return tuple(_incident(row) for row in rows)

    async def acknowledge(self, incident_ref: str) -> ExternalIncident:
        return await self._set_status(incident_ref, ExternalIncidentStatus.ACKNOWLEDGED)

    async def resolve(self, incident_ref: str) -> ExternalIncident:
        return await self._set_status(incident_ref, ExternalIncidentStatus.RESOLVED)

    async def add_note(self, incident_ref: str, note: str) -> None:
        bounded_note = text(note, field="note", limit=2_000)
        await self._request(
            "POST",
            f"/incidents/{_ref(incident_ref)}/notes",
            body={"note": {"content": bounded_note}},
        )

    async def _set_status(
        self,
        incident_ref: str,
        status: ExternalIncidentStatus,
    ) -> ExternalIncident:
        payload = await self._request(
            "PUT",
            f"/incidents/{_ref(incident_ref)}",
            body={"incident": {"type": "incident_reference", "status": status.value}},
        )
        row = payload.get("incident") if isinstance(payload, Mapping) else None
        return _incident(row)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        return await request_json(
            self._http,
            self._token_provider,
            method,
            f"{self._config.api_base.rstrip('/')}{path}",
            headers={
                "From": self._config.from_email,
                "Content-Type": "application/json",
            },
            params=params,
            body=body,
            timeout_seconds=self._config.timeout_seconds,
            authorization_scheme="pagerduty-token",
        )


def _incident(value: Any) -> ExternalIncident:
    if not isinstance(value, Mapping):
        raise IncidentPlatformError("PagerDuty incident record is malformed")
    service = value.get("service")
    service_ref = service.get("id") if isinstance(service, Mapping) else None
    urgency = value.get("urgency")
    return ExternalIncident(
        platform="pagerduty",
        incident_ref=text(value.get("id"), field="id", limit=256),
        title=text(value.get("title"), field="title", limit=500),
        severity=str(urgency or "unknown")[:32],
        status=ExternalIncidentStatus(text(value.get("status"), field="status", limit=32)),
        created_at=timestamp(value.get("created_at"), field="created_at"),
        updated_at=timestamp(value.get("updated_at"), field="updated_at"),
        service_ref=str(service_ref)[:256] if service_ref else None,
        source_url=str(value.get("html_url"))[:2_000] if value.get("html_url") else None,
    )


def _ref(value: str) -> str:
    return quote(text(value, field="incident_ref", limit=256), safe="")


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 500:
        raise ValueError("PagerDuty incident limit MUST be in [1, 500]")


__all__ = ["PagerDutyIncidentPlatform", "PagerDutyIncidentPlatformConfig"]
