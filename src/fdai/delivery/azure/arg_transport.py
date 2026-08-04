"""Authenticated, bounded Azure Resource Graph HTTP pagination."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from math import isfinite
from typing import Any

import httpx

from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_INITIAL_RETRY_DELAY_SECONDS = 0.5
_DEFAULT_MAX_RETRY_DELAY_SECONDS = 30.0
_DEFAULT_MAX_RESPONSE_BYTES = 10_000_000
_DEFAULT_MAX_TOTAL_RESPONSE_BYTES = 64_000_000


class ArgThrottleGate:
    """Share ARG quota backoff across concurrent queries in one adapter."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._not_before = 0.0

    async def wait(self) -> None:
        while True:
            async with self._lock:
                delay = self._not_before - _monotonic()
            if delay > 0:
                await _sleep(delay)
                continue
            return

    async def defer(self, delay_seconds: float) -> None:
        if delay_seconds <= 0:
            return
        async with self._lock:
            self._not_before = max(self._not_before, _monotonic() + delay_seconds)

    async def observe(self, headers: httpx.Headers) -> None:
        quota_delay = _quota_reset_seconds(headers)
        if quota_delay is not None:
            await self.defer(quota_delay)


async def _sleep(delay_seconds: float) -> None:
    await asyncio.sleep(delay_seconds)


def _monotonic() -> float:
    return asyncio.get_running_loop().time()


async def fetch_arg_pages(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    audience: str,
    endpoint: str,
    api_version: str,
    subscriptions: tuple[str, ...],
    query: str,
    resource_type: str,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
    error_type: type[RuntimeError],
    map_row: Callable[[Mapping[str, Any]], ResourceRecord | None],
    project_links: Callable[[Mapping[str, Any], ResourceRecord], tuple[LinkRecord, ...]],
    throttle_gate: ArgThrottleGate | None = None,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    initial_retry_delay_seconds: float = _DEFAULT_INITIAL_RETRY_DELAY_SECONDS,
    max_retry_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
    """Fetch all pages for one shard without silently accepting a partial result."""
    rows = await fetch_arg_row_pages(
        identity=identity,
        http_client=http_client,
        audience=audience,
        endpoint=endpoint,
        api_version=api_version,
        subscriptions=subscriptions,
        query=query,
        result_name=resource_type,
        page_size=page_size,
        max_pages=max_pages,
        timeout_seconds=timeout_seconds,
        error_type=error_type,
        throttle_gate=throttle_gate,
        max_attempts=max_attempts,
        initial_retry_delay_seconds=initial_retry_delay_seconds,
        max_retry_delay_seconds=max_retry_delay_seconds,
    )
    collected: list[ResourceRecord] = []
    collected_links: list[LinkRecord] = []
    for row in rows:
        record = map_row(row)
        if record is not None:
            collected.append(record)
            collected_links.extend(project_links(row, record))
    return tuple(collected), tuple(collected_links)


async def fetch_arg_row_pages(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    audience: str,
    endpoint: str,
    api_version: str,
    subscriptions: tuple[str, ...],
    query: str,
    result_name: str,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
    error_type: type[RuntimeError],
    throttle_gate: ArgThrottleGate | None = None,
    max_records: int | None = None,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    initial_retry_delay_seconds: float = _DEFAULT_INITIAL_RETRY_DELAY_SECONDS,
    max_retry_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
    request_headers: Mapping[str, str] | None = None,
    allow_truncated_without_token: bool = False,
    max_response_bytes: int | None = _DEFAULT_MAX_RESPONSE_BYTES,
    max_total_response_bytes: int | None = _DEFAULT_MAX_TOTAL_RESPONSE_BYTES,
) -> tuple[Mapping[str, Any], ...]:
    """Fetch a complete, bounded ARG row set with quota-aware retries."""
    if max_attempts < 1:
        raise ValueError("max_attempts MUST be >= 1")
    if initial_retry_delay_seconds <= 0 or max_retry_delay_seconds <= 0:
        raise ValueError("ARG retry delays MUST be positive")
    if max_records is not None and max_records < 1:
        raise ValueError("max_records MUST be >= 1")
    if max_response_bytes is not None and max_response_bytes < 1:
        raise ValueError("max_response_bytes MUST be >= 1")
    if max_total_response_bytes is not None and max_total_response_bytes < 1:
        raise ValueError("max_total_response_bytes MUST be >= 1")
    url = (
        f"{endpoint.rstrip('/')}"
        "/providers/Microsoft.ResourceGraph/resources"
        f"?api-version={api_version}"
    )
    collected: list[Mapping[str, Any]] = []
    skip_token: str | None = None
    seen_skip_tokens: set[str] = set()
    total_response_bytes = 0
    gate = throttle_gate or ArgThrottleGate()
    static_headers = dict(request_headers) if request_headers is not None else None

    for page in range(max_pages):
        body: dict[str, Any] = {
            "subscriptions": list(subscriptions),
            "query": query,
            "options": {"$top": page_size},
        }
        if skip_token is not None:
            body["options"]["$skipToken"] = skip_token

        response = await _post_with_retry(
            identity=identity,
            http_client=http_client,
            url=url,
            headers=static_headers,
            audience=audience,
            body=body,
            timeout_seconds=timeout_seconds,
            resource_type=result_name,
            page=page,
            error_type=error_type,
            throttle_gate=gate,
            max_attempts=max_attempts,
            initial_retry_delay_seconds=initial_retry_delay_seconds,
            max_retry_delay_seconds=max_retry_delay_seconds,
        )

        if response.status_code >= 400:
            raise error_type(
                f"ARG returned HTTP {response.status_code} for {result_name!r} (page {page})"
            )
        if max_response_bytes is not None and len(response.content) > max_response_bytes:
            raise error_type(
                f"ARG response exceeded {max_response_bytes} bytes for {result_name!r} "
                f"(page {page})"
            )
        total_response_bytes += len(response.content)
        if max_total_response_bytes is not None and total_response_bytes > max_total_response_bytes:
            raise error_type(
                f"ARG responses exceeded {max_total_response_bytes} total bytes for "
                f"{result_name!r} (page {page})"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise error_type(f"ARG returned non-JSON for {result_name!r} (page {page})") from exc
        if not isinstance(payload, Mapping):
            raise error_type(f"ARG payload was not an object for {result_name!r} (page {page})")

        data = payload.get("data")
        if not isinstance(data, list):
            raise error_type(f"ARG payload missing 'data' array for {result_name!r} (page {page})")

        for row in data:
            if not isinstance(row, Mapping):
                raise error_type(
                    f"ARG payload contained a non-object row for {result_name!r} (page {page})"
                )
            collected.append(row)
        if max_records is not None and len(collected) > max_records:
            raise error_type(
                f"ARG returned more than {max_records} records for {result_name!r}; "
                "narrow the query"
            )

        next_token = payload.get("$skipToken")
        if not isinstance(next_token, str) or not next_token:
            if not allow_truncated_without_token and (
                payload.get("resultTruncated") is True or _count_is_truncated(payload)
            ):
                raise error_type(
                    f"ARG returned a truncated result without a continuation token for "
                    f"{result_name!r} (page {page})"
                )
            break
        if next_token in seen_skip_tokens:
            raise error_type(
                f"ARG continuation token did not advance for {result_name!r} (page {page})"
            )
        seen_skip_tokens.add(next_token)
        skip_token = next_token
    else:
        raise error_type(
            f"ARG pagination cap ({max_pages}) exceeded for {result_name!r}; "
            "narrow the query or raise max_pages via config"
        )

    return tuple(collected)


async def _post_with_retry(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str] | None,
    audience: str,
    body: Mapping[str, Any],
    timeout_seconds: float,
    resource_type: str,
    page: int,
    error_type: type[RuntimeError],
    throttle_gate: ArgThrottleGate,
    max_attempts: int,
    initial_retry_delay_seconds: float,
    max_retry_delay_seconds: float,
) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    for attempt in range(max_attempts):
        await throttle_gate.wait()
        if headers is None:
            try:
                token = await identity.get_token(audience)
            except Exception as exc:  # noqa: BLE001 - identity boundary fails closed
                raise error_type(
                    f"ARG identity token request failed for {resource_type!r} "
                    f"(page {page}, attempt {attempt + 1}): {type(exc).__name__}"
                ) from exc
            request_headers: Mapping[str, str] = {
                "Authorization": f"Bearer {token.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            request_headers = headers
        try:
            response = await http_client.post(
                url,
                headers=request_headers,
                content=json.dumps(body),
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt + 1 >= max_attempts:
                break
            await throttle_gate.defer(
                min(
                    initial_retry_delay_seconds * (2**attempt),
                    max_retry_delay_seconds,
                )
            )
            continue

        await throttle_gate.observe(response.headers)
        if response.status_code not in _RETRYABLE_STATUS_CODES or attempt + 1 >= max_attempts:
            return response
        retry_delay = _retry_after_seconds(response.headers.get("Retry-After"))
        if retry_delay is None:
            retry_delay = min(
                initial_retry_delay_seconds * (2**attempt),
                max_retry_delay_seconds,
            )
        elif retry_delay > max_retry_delay_seconds:
            return response
        await throttle_gate.defer(retry_delay)

    if last_error is None:
        raise error_type(
            f"ARG request retry loop ended without a response for {resource_type!r} (page {page})"
        )
    raise error_type(
        f"ARG request failed for {resource_type!r} (page {page}) after "
        f"{max_attempts} attempts: {type(last_error).__name__}"
    ) from last_error


def _quota_reset_seconds(headers: httpx.Headers) -> float | None:
    try:
        remaining = int(headers.get("x-ms-user-quota-remaining", ""))
    except ValueError:
        return None
    if remaining > 0:
        return None
    raw = headers.get("x-ms-user-quota-resets-after")
    if raw is None:
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (float(part) for part in parts)
    except ValueError:
        return None
    if (
        not all(isfinite(value) for value in (hours, minutes, seconds))
        or hours < 0
        or not 0 <= minutes < 60
        or not 0 <= seconds < 60
    ):
        return None
    delay = hours * 3600 + minutes * 60 + seconds
    return delay


def _retry_after_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        delay = float(raw)
    except ValueError:
        return None
    return delay if isfinite(delay) and delay >= 0 else None


def _count_is_truncated(payload: Mapping[str, Any]) -> bool:
    count = payload.get("count")
    total = payload.get("totalRecords")
    return (
        isinstance(count, int)
        and not isinstance(count, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and count < total
    )
