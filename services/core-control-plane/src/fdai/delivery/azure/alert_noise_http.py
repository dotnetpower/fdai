"""Pinned Azure Monitor GET collections with scope, pagination and total-budget fencing."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

AZURE_ALERT_APIS = {
    "Microsoft.Insights/metricAlerts": "2018-03-01",
    "Microsoft.Insights/scheduledQueryRules": "2023-12-01",
    "Microsoft.Insights/activityLogAlerts": "2020-10-01",
    "Microsoft.Insights/actionGroups": "2023-01-01",
    "Microsoft.AlertsManagement/actionRules": "2021-08-08",
    "Microsoft.AlertsManagement/alerts": "2019-03-01",
}
_ORIGIN = "https://management.azure.com"
_AUDIENCE = _ORIGIN + "/.default"
_GUID = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
_PATH = re.compile(
    rf"/subscriptions/{_GUID}(?:/resourceGroups/([A-Za-z0-9_.()-]{{1,90}}))?"
    r"/providers/([^/]+/[^/]+)",
    re.IGNORECASE,
)


class AlertReadUnavailable(RuntimeError):  # noqa: N818 - preserve the public exception name
    """Safe failure code; bounded previous rows remain private, never in exception text."""

    def __init__(self, reason: str, *, rows: tuple[Mapping[str, Any], ...] = ()) -> None:
        super().__init__(reason)
        self.rows = rows

    @property
    def terminal(self) -> bool:
        """Throttling, timeout and a consumed shared budget end the collection attempt."""
        return str(self) in {
            "provider_status_429",
            "provider_status_503",
            "provider_timeout",
            "reader_identity_invalid",
            "provider_read_unavailable",
        } or str(self).startswith("total_")


@dataclass(frozen=True, slots=True)
class AlertReadLimits:
    """Finite per-collection and shared-attempt resource ceilings, not permissions."""

    pages: int = 10
    items: int = 2000
    bytes_per_page: int = 2_000_000
    timeout_seconds: float = 10.0
    total_pages: int = 40
    total_items: int = 10_000
    total_bytes: int = 20_000_000
    total_seconds: float = 60.0

    def __post_init__(self) -> None:
        for value, ceiling in (
            (self.pages, 100),
            (self.items, 10_000),
            (self.bytes_per_page, 5_000_000),
            (self.total_pages, 100),
            (self.total_items, 20_000),
            (self.total_bytes, 50_000_000),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("alert read count/byte limits are invalid")
        for seconds, ceiling in ((self.timeout_seconds, 30), (self.total_seconds, 120)):
            if type(seconds) not in (int, float) or not 0 < seconds <= ceiling:
                raise ValueError("alert read time limits are invalid")


@dataclass(slots=True)
class AlertReadBudget:
    """One local collection attempt shares these ceilings across every source and resolver."""

    limits: AlertReadLimits
    pages: int = 0
    items: int = 0
    bytes: int = 0
    _started: float = field(default_factory=time.monotonic, repr=False)
    _stopped: str | None = field(default=None, repr=False)

    def remaining_seconds(self) -> float:
        """Return the remaining wall-clock budget or stop before another operation."""
        if self._stopped is not None:
            raise AlertReadUnavailable(self._stopped)
        remaining = self.limits.total_seconds - (time.monotonic() - self._started)
        if remaining <= 0:
            raise AlertReadUnavailable("total_deadline_exceeded")
        return remaining

    def stop(self, reason: str) -> None:
        """Latch a terminal failure so a later collection/resolver cannot restart the attempt."""
        self._stopped = reason

    def consume(self, kind: str, count: int = 1) -> None:
        """Charge before retaining data or making a request; never silently truncate."""
        self.remaining_seconds()
        if kind not in {"pages", "items", "bytes"} or type(count) is not int or count < 0:
            raise ValueError("alert read budget charge is invalid")
        value = getattr(self, kind) + count
        if value > getattr(self.limits, "total_" + kind):
            reason = "total_" + kind + "_exceeded"
            self.stop(reason)
            raise AlertReadUnavailable(reason)
        setattr(self, kind, value)


_DEFAULT_READ_LIMITS = AlertReadLimits()


class AzureAlertReader:
    """Read only pinned collections; redirects, filter drift and arbitrary next links fail."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        identity: WorkloadIdentity,
        limits: AlertReadLimits = _DEFAULT_READ_LIMITS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http, self._identity, self._limits = http, identity, limits
        self._clock = clock

    def new_budget(self) -> AlertReadBudget:
        """Start an isolated attempt; concurrent assessments never share mutable counters."""
        return AlertReadBudget(self._limits)

    async def list(
        self,
        path: str,
        *,
        api_version: str,
        params: Mapping[str, str] | None = None,
        budget: AlertReadBudget | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        """Return a complete list or an explicit failure carrying only bounded prior rows."""
        query = _request_query(path, api_version, params)
        budget = budget if budget is not None else self.new_budget()
        if budget.limits != self._limits:
            raise ValueError("alert read budget MUST use the reader ceilings")
        rows: list[Mapping[str, Any]] = []
        try:
            async with asyncio.timeout(budget.remaining_seconds()):
                budget.consume("pages")  # Exhaustion must stop before another identity exchange.
                try:
                    token = await self._identity.get_token(_AUDIENCE)
                except Exception:
                    raise AlertReadUnavailable("reader_identity_invalid") from None
                if (
                    token.audience != _AUDIENCE
                    or token.expires_at.tzinfo is None
                    or token.expires_at <= self._clock()
                    or not token.token
                ):
                    raise AlertReadUnavailable("reader_identity_invalid")
                next_url = _ORIGIN + path + "?" + urlencode(query)
                seen: set[tuple[tuple[str, str], ...]] = set()
                for page in range(self._limits.pages):
                    cursor_key = tuple(sorted(_query(urlsplit(next_url).query).items()))
                    if cursor_key in seen:
                        raise AlertReadUnavailable("pagination_cycle")
                    seen.add(cursor_key)
                    if page:
                        budget.consume("pages")
                    async with self._http.stream(
                        "GET",
                        next_url,
                        headers={
                            "Authorization": f"Bearer {token.token}",
                            "Accept-Encoding": "identity",
                        },
                        timeout=self._limits.timeout_seconds,
                        follow_redirects=False,
                    ) as response:
                        if response.status_code != 200:
                            raise AlertReadUnavailable(f"provider_status_{response.status_code}")
                        if (
                            response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                        ):
                            raise AlertReadUnavailable("provider_encoding_unsupported")
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > self._limits.bytes_per_page:
                                raise AlertReadUnavailable("provider_bytes_exceeded")
                            budget.consume("bytes", len(chunk))
                            data.extend(chunk)
                    payload = json.loads(
                        data,
                        object_pairs_hook=_unique_keys,
                        parse_constant=_reject_number,
                        parse_float=_finite_float,
                    )
                    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                        raise AlertReadUnavailable("provider_shape_invalid")
                    for item in payload["value"]:
                        if not isinstance(item, dict):
                            raise AlertReadUnavailable("provider_row_invalid")
                        if len(rows) >= self._limits.items:
                            raise AlertReadUnavailable("provider_items_exceeded")
                        budget.consume("items")
                        rows.append(item)
                    continuation = payload.get("nextLink")
                    if continuation is None:
                        return tuple(rows)
                    next_url = _cursor(continuation, path, query)
                raise AlertReadUnavailable("provider_pages_exceeded")
        except AlertReadUnavailable as exc:
            if exc.terminal:
                budget.stop(str(exc))
            raise AlertReadUnavailable(str(exc), rows=tuple(rows)) from None
        except (TimeoutError, httpx.TimeoutException):
            budget.stop("provider_timeout")
            raise AlertReadUnavailable("provider_timeout", rows=tuple(rows)) from None
        except Exception:
            # Identity/transport exceptions can contain credentials or provider response bodies.
            budget.stop("provider_read_unavailable")
            raise AlertReadUnavailable("provider_read_unavailable", rows=tuple(rows)) from None


def _request_query(path: str, version: str, params: Mapping[str, str] | None) -> dict[str, str]:
    match = _PATH.fullmatch(path) if isinstance(path, str) else None
    if match is None or match[1] in {".", ".."} or AZURE_ALERT_APIS.get(match[2]) != version:
        raise ValueError("alert read MUST use a pinned management collection")
    if match[2] == "Microsoft.AlertsManagement/alerts" and match[1] is None:
        raise ValueError("alert history MUST use the authorized resource-group scope")
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("alert read parameters MUST be a mapping")
    extra = dict(params or {})
    allowed = {"customTimeRange", "includeContext", "includeEgressConfig", "pageCount"}
    if (
        set(extra) - allowed
        or (extra and match[2] != "Microsoft.AlertsManagement/alerts")
        or any(not isinstance(v, str) or not v or len(v) > 4096 for v in extra.values())
    ):
        raise ValueError("alert read parameters are invalid")
    if any(extra.get(key, "false") != "false" for key in ("includeContext", "includeEgressConfig")):
        raise ValueError("alert history MUST exclude private context and egress configuration")
    return {"api-version": version, **extra}


def _query(raw: str) -> dict[str, str]:
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
    if len({key.casefold() for key, _ in pairs}) != len(pairs) or any(
        not key or not value or any(ord(char) < 32 for char in key + value) for key, value in pairs
    ):
        raise ValueError("query parameter is empty, duplicated or malformed")
    return dict(pairs)


def _cursor(raw: object, path: str, initial: Mapping[str, str]) -> str:
    if (
        not isinstance(raw, str)
        or not 1 <= len(raw) <= 16_384
        or "#" in raw
        or any(ord(char) < 33 or ord(char) > 126 for char in raw)
    ):
        raise AlertReadUnavailable("provider_cursor_invalid")
    parsed = urlsplit(raw)
    query = _query(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "management.azure.com"
        or parsed.path.casefold() != path.casefold()
        or parsed.fragment
        or any(query.get(key) != value for key, value in initial.items())
        or any(
            key.casefold() not in {"$skiptoken", "skiptoken", "continuationtoken"}
            for key in query.keys() - initial.keys()
        )
    ):
        raise AlertReadUnavailable("provider_cursor_outside_scope")
    return raw


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provider key")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    del value
    raise ValueError("non-finite provider value")


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("non-finite provider value")
    return value
