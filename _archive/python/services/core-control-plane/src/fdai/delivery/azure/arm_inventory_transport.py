"""Bound ARM inventory response allocation and transient retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from fdai_service_contracts.ontology_query import content_digest

from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.http_response import (
    BOUNDED_ACCEPT_ENCODING,
    ResponseBodyTooLargeError,
    read_bounded_response,
)
from fdai.delivery.http_retry import InvalidRetryAfterError, retry_not_before

if TYPE_CHECKING:
    from fdai.delivery.persistence.postgres_inventory_provider_read_admission import (
        DurableProviderReadAdmissionGate,
    )

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
    durable_gate: DurableProviderReadAdmissionGate | None = None,
    require_durable_admission: bool = False,
) -> tuple[Mapping[str, Any], int]:
    """Read one bounded object; never retry before the provider's cooldown."""
    if max_attempts < 1 or max_response_bytes < 1 or timeout_seconds <= 0:
        raise ValueError("fetch_arm_json requires positive retry, byte, and timeout bounds")
    if require_durable_admission and durable_gate is None:
        raise ValueError(
            "qualified ARM operation requires a bound DurableProviderReadAdmissionGate"
        )
    bounded_headers = httpx.Headers(headers)
    bounded_headers["Accept-Encoding"] = BOUNDED_ACCEPT_ENCODING
    for attempt in range(max_attempts):
        delay = min(0.5 * (2**attempt), 30.0)
        request_id = f"arm:{resource_type}:attempt-{attempt}:{content_digest({'url': url})[7:23]}"
        idempotency_key = content_digest(
            {"attempt": attempt, "resource_type": resource_type, "url": url}
        )
        if durable_gate is not None:
            receipt = await durable_gate.acquire(
                request_id=request_id,
                idempotency_key=idempotency_key,
                wait_for_cooldown=True,
            )
            if receipt.reused:
                if receipt.reused_response_bytes is None:
                    raise ArmInventoryError(
                        "reused ARM provider-read receipt has no retained response body; "
                        "refusing unbudgeted physical read"
                    )
                reused_payload = json.loads(receipt.reused_response_bytes)
                if not isinstance(reused_payload, Mapping):
                    raise ArmInventoryError("ARM inventory response MUST be an object")
                return reused_payload, len(receipt.reused_response_bytes)
        try:
            async with asyncio.timeout(timeout_seconds):
                async with client.stream(
                    "GET",
                    url,
                    headers=bounded_headers,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        now = datetime.now(UTC)
                        try:
                            deadline = retry_not_before(response.headers, now=now)
                        except InvalidRetryAfterError as exc:
                            if durable_gate is not None:
                                retry_sec = (
                                    (exc.retry_not_before - now).total_seconds()
                                    if exc.retry_not_before is not None
                                    else None
                                )
                                await durable_gate.record_ambiguous_or_cancelled(
                                    request_id=request_id,
                                    reason="invalid_retry_after",
                                    retry_after_seconds=retry_sec,
                                    now=now,
                                )
                            raise ArmInventoryError(
                                f"ARM returned HTTP {response.status_code} "
                                "with invalid retry metadata",
                                retry_not_before=exc.retry_not_before,
                            ) from exc
                        retry_sec = (
                            max(0.0, (deadline - now).total_seconds())
                            if deadline is not None
                            else None
                        )
                        if deadline is not None:
                            delay = max(delay, (deadline - now).total_seconds())
                        if durable_gate is not None:
                            await durable_gate.record_ambiguous_or_cancelled(
                                request_id=request_id,
                                reason=f"http_{response.status_code}",
                                retry_after_seconds=retry_sec,
                                now=now,
                            )
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
                        try:
                            content = await read_bounded_response(
                                response, max_bytes=max_response_bytes
                            )
                        except ResponseBodyTooLargeError as exc:
                            if durable_gate is not None:
                                await durable_gate.record_ambiguous_or_cancelled(
                                    request_id=request_id,
                                    reason="response_body_too_large",
                                )
                            raise ArmInventoryError("ARM response exceeded its byte limit") from exc
                        except httpx.DecodingError as exc:
                            if durable_gate is not None:
                                await durable_gate.record_ambiguous_or_cancelled(
                                    request_id=request_id,
                                    reason="invalid_compressed_body",
                                )
                            raise ArmInventoryError(
                                "ARM returned invalid compressed inventory data"
                            ) from exc
                        try:
                            payload = json.loads(content)
                        except ValueError as exc:
                            if durable_gate is not None:
                                await durable_gate.record_ambiguous_or_cancelled(
                                    request_id=request_id,
                                    reason="non_json_body",
                                )
                            raise ArmInventoryError("ARM returned non-JSON inventory data") from exc
                        if not isinstance(payload, Mapping):
                            if durable_gate is not None:
                                await durable_gate.record_ambiguous_or_cancelled(
                                    request_id=request_id,
                                    reason="non_mapping_json",
                                )
                            raise ArmInventoryError("ARM inventory response MUST be an object")
                        if durable_gate is not None:
                            body_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
                            await durable_gate.complete(
                                request_id=request_id,
                                idempotency_key=idempotency_key,
                                response_digest=body_digest,
                                response_payload=content,
                            )
                        return payload, len(content)
        except asyncio.CancelledError:
            if durable_gate is not None:
                await asyncio.shield(
                    durable_gate.record_ambiguous_or_cancelled(
                        request_id=request_id,
                        reason="cancelled",
                    )
                )
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            if durable_gate is not None:
                await durable_gate.record_ambiguous_or_cancelled(
                    request_id=request_id,
                    reason=type(exc).__name__,
                )
            if attempt + 1 == max_attempts:
                raise ArmInventoryError(
                    f"ARM request failed for {resource_type!r}: {type(exc).__name__}"
                ) from exc
        await _sleep(delay)
    raise ArmInventoryError("ARM inventory request attempts exhausted")
