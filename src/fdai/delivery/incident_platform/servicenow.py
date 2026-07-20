"""ServiceNow Table API incident read and lifecycle adapter."""

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
class ServiceNowIncidentPlatformConfig:
    instance_url: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.instance_url.startswith("https://"):
            raise ValueError("ServiceNow instance URL MUST use HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("ServiceNow incident timeout MUST be positive")


class ServiceNowIncidentPlatform:
    def __init__(
        self,
        *,
        config: ServiceNowIncidentPlatformConfig,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final = config
        self._token_provider = token_provider
        self._http = http_client

    async def list_active(self, *, limit: int = 100) -> Sequence[ExternalIncident]:
        if not 1 <= limit <= 500:
            raise ValueError("ServiceNow incident limit MUST be in [1, 500]")
        payload = await self._request(
            "GET",
            "/api/now/table/incident",
            params={"sysparm_query": "active=true", "sysparm_limit": limit},
        )
        rows = payload.get("result") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise IncidentPlatformError("ServiceNow incidents payload is malformed")
        return tuple(_incident(row) for row in rows)

    async def acknowledge(self, incident_ref: str) -> ExternalIncident:
        return await self._patch(incident_ref, {"state": "2"})

    async def resolve(self, incident_ref: str) -> ExternalIncident:
        return await self._patch(incident_ref, {"state": "6"})

    async def add_note(self, incident_ref: str, note: str) -> None:
        await self._patch(
            incident_ref,
            {"work_notes": text(note, field="note", limit=2_000)},
        )

    async def _patch(
        self,
        incident_ref: str,
        body: Mapping[str, Any],
    ) -> ExternalIncident:
        payload = await self._request(
            "PATCH",
            f"/api/now/table/incident/{_ref(incident_ref)}",
            body=body,
        )
        row = payload.get("result") if isinstance(payload, Mapping) else None
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
            f"{self._config.instance_url.rstrip('/')}{path}",
            headers={"Content-Type": "application/json"},
            params=params,
            body=body,
            timeout_seconds=self._config.timeout_seconds,
        )


def _incident(value: Any) -> ExternalIncident:
    if not isinstance(value, Mapping):
        raise IncidentPlatformError("ServiceNow incident record is malformed")
    state = str(value.get("state") or "1")
    status = {
        "1": ExternalIncidentStatus.TRIGGERED,
        "2": ExternalIncidentStatus.ACKNOWLEDGED,
        "6": ExternalIncidentStatus.RESOLVED,
        "7": ExternalIncidentStatus.RESOLVED,
    }.get(state, ExternalIncidentStatus.TRIGGERED)
    service = value.get("business_service")
    if isinstance(service, Mapping):
        service = service.get("value") or service.get("display_value")
    return ExternalIncident(
        platform="servicenow",
        incident_ref=text(value.get("sys_id"), field="sys_id", limit=256),
        title=text(
            value.get("short_description") or value.get("number"),
            field="short_description",
            limit=500,
        ),
        severity=str(value.get("priority") or "unknown")[:32],
        status=status,
        created_at=timestamp(value.get("sys_created_on"), field="sys_created_on", assume_utc=True),
        updated_at=timestamp(value.get("sys_updated_on"), field="sys_updated_on", assume_utc=True),
        service_ref=str(service)[:256] if service else None,
    )


def _ref(value: str) -> str:
    return quote(text(value, field="incident_ref", limit=256), safe="")


__all__ = ["ServiceNowIncidentPlatform", "ServiceNowIncidentPlatformConfig"]
