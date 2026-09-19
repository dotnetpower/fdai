"""Bound ARM inventory response allocation and transient retries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.http_retry import InvalidRetryAfterError, retry_not_before

_RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def fetch_arm_json(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    resource_type: str,
    timeout_seconds: float,
    max_response_bytes: int,
    max_attempts: int,
) -> tuple[Mapping[str, Any], int]:
    """Read one bounded object; never retry before the provider's cooldown."""
    for attempt in range(max_attempts):
        delay = min(0.5 * (2**attempt), 30.0)
        try:
            async with asyncio.timeout(timeout_seconds):
                async with client.stream(
                    "GET",
                    url,
                    headers=headers,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        now = datetime.now(UTC)
                        try:
                            deadline = retry_not_before(response.headers, now=now)
                        except InvalidRetryAfterError as exc:
                            raise ArmInventoryError(
                                f"ARM returned HTTP {response.status_code} "
                                "with invalid retry metadata",
                                retry_not_before=exc.retry_not_before,
                            ) from exc
                        if deadline is not None:
                            delay = max(delay, (deadline - now).total_seconds())
                        if (
                            response.status_code not in _RETRYABLE
                            or attempt + 1 == max_attempts
                            or delay > 30.0
                        ):
                            raise ArmInventoryError(
                                f"ARM returned HTTP {response.status_code} for {resource_type!r}",
                                retry_not_before=deadline,
                            )
                    else:
                        content = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            if len(content) + len(chunk) > max_response_bytes:
                                raise ArmInventoryError("ARM response exceeded its byte limit")
                            content.extend(chunk)
                        try:
                            payload = json.loads(content)
                        except ValueError as exc:
                            raise ArmInventoryError("ARM returned non-JSON inventory data") from exc
                        if not isinstance(payload, Mapping):
                            raise ArmInventoryError("ARM inventory response MUST be an object")
                        return payload, len(content)
        except (httpx.HTTPError, TimeoutError) as exc:
            if attempt + 1 == max_attempts:
                raise ArmInventoryError(
                    f"ARM request failed for {resource_type!r}: {type(exc).__name__}"
                ) from exc
        await _sleep(delay)
    raise ArmInventoryError("ARM inventory request attempts exhausted")
