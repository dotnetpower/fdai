"""Shared helpers for real notification adapters.

Kept tiny and vendor-neutral: response truncation + POST wrapper. Every
adapter uses the same shape so telemetry looks identical across
channels.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from aiopspilot.shared.providers.notifications.base import (
    ChannelDeliveryError,
    ChannelUnavailableError,
)

_MAX_ERROR_BODY_BYTES = 512


def truncate(body: str, limit: int = _MAX_ERROR_BODY_BYTES) -> str:
    """Truncate ``body`` to ``limit`` bytes with an explicit marker.

    Response bodies from a vendor are untrusted data — a stray reflection
    could carry a secret or a huge payload. Trimming at a fixed limit
    prevents both a leak and a log-flood.
    """
    if len(body) <= limit:
        return body
    return body[:limit] + f"...<truncated {len(body) - limit} bytes>"


async def post_json(
    *,
    client: httpx.AsyncClient,
    url: str,
    payload: Mapping[str, Any] | list[Any],
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float,
    ok_statuses: tuple[int, ...] = (200, 201, 202, 204),
) -> tuple[int, str]:
    """POST ``payload`` as JSON and return ``(status_code, text)`` on 2xx.

    Non-2xx raises :class:`ChannelDeliveryError`; transport errors raise
    :class:`ChannelUnavailableError`. Both carry a truncated body so the
    router can log them without leaking or exploding.
    """
    try:
        response = await client.post(
            url,
            json=payload,
            headers=dict(headers or {}),
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise ChannelUnavailableError(f"POST {url} transport error: {exc}") from exc

    body = truncate(response.text or "")
    if response.status_code not in ok_statuses:
        raise ChannelDeliveryError(f"POST {url} → HTTP {response.status_code}: {body!r}")
    return response.status_code, body


__all__ = ["post_json", "truncate"]
