"""Shared bounded HTTP helpers for incident platform adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.shared.providers.incident_platform import IncidentPlatformError

TokenProvider = Callable[[], Awaitable[str]]


async def request_json(
    client: httpx.AsyncClient,
    token_provider: TokenProvider,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str | int] | None = None,
    body: Mapping[str, Any] | None = None,
    timeout_seconds: float,
    authorization_scheme: str = "Bearer",
) -> Any:
    try:
        token = await token_provider()
        authorization = (
            f"Token token={token}"
            if authorization_scheme == "pagerduty-token"
            else f"{authorization_scheme} {token}"
        )
        response = await client.request(
            method,
            url,
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                **dict(headers or {}),
            },
            params=params,
            json=body,
            timeout=timeout_seconds,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise IncidentPlatformError("incident platform request failed") from exc
    if response.status_code >= 400:
        raise IncidentPlatformError(f"incident platform returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise IncidentPlatformError("incident platform returned non-JSON") from exc


def timestamp(value: Any, *, field: str, assume_utc: bool = False) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IncidentPlatformError(f"incident platform record missing {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncidentPlatformError(f"incident platform {field} is invalid") from exc
    if parsed.tzinfo is None and assume_utc:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        raise IncidentPlatformError(f"incident platform {field} MUST include timezone")
    return parsed.astimezone(UTC)


def text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IncidentPlatformError(f"incident platform {field} is missing or unbounded")
    return value.strip()


__all__ = ["TokenProvider", "request_json", "text", "timestamp"]
