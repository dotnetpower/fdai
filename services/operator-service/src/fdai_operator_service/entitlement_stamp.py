"""Stamp Core's latest entitlement notice on every authenticated Operator response.

Responsibility: carry the notice that Core publishes in `licensing_entitlement_state`
to the Console watermark through the `X-FDAI-Entitlement` response header.
Boundary: reads only that Core-owned row through the Operator's read-only role, at
most once every 15 seconds per process. Bearer authentication marks the request, and
only a marked request's response carries the stamp.
Authority and state: the stamp is an availability notice. It grants and removes no
authority, and no setting turns it off. A missing, malformed, unreadable, or stale
row stamps `not-activated`.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol

import psycopg
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn

ENTITLEMENT_HEADER: Final = "X-FDAI-Entitlement"
NOT_ACTIVATED: Final = "not-activated"
NOTICES: Final = frozenset({"none", "evaluation-ended", NOT_ACTIVATED})
STALE_AFTER: Final = timedelta(minutes=5)
REFRESH_SECONDS: Final = 15.0
READ_TIMEOUT_SECONDS: Final = 2.0

_HEADER_KEY = ENTITLEMENT_HEADER.lower().encode("ascii")
_LOGGER = logging.getLogger(__name__)
_AUTHENTICATED: contextvars.ContextVar[list[bool] | None] = contextvars.ContextVar(
    "fdai_operator_request_authenticated", default=None
)


def mark_request_authenticated() -> None:
    """Record that the current request presented a verified bearer credential.

    The marker is a shared mutable cell, so a verification that runs in a worker
    thread with a copied context still reaches the response stamp.
    """

    marker = _AUTHENTICATED.get()
    if marker is not None:
        marker[0] = True


@dataclass(frozen=True, slots=True)
class EntitlementState:
    """One notice as Core published it, with Core's observation time."""

    notice: str
    observed_at: datetime


class EntitlementStateSource(Protocol):
    """Read the latest published state, or None when Core has published none."""

    async def latest(self) -> EntitlementState | None: ...


@dataclass(frozen=True, slots=True)
class PostgresEntitlementStateSource:
    """Read the Core-owned singleton row through the Operator's read-only role."""

    dsn: str
    statement_timeout_ms: int = 2_000
    connect_timeout_s: int = 2

    async def latest(self) -> EntitlementState | None:
        """Return the stored row, or None when it is absent or malformed."""

        async with await psycopg.AsyncConnection.connect(
            normalize_psycopg_dsn(self.dsn),
            connect_timeout=self.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT notice, observed_at FROM licensing_entitlement_state WHERE singleton"
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        notice, observed_at = row
        if not isinstance(notice, str) or not isinstance(observed_at, datetime):
            return None
        return EntitlementState(notice=notice, observed_at=observed_at)


def current_notice(state: EntitlementState | None, *, now: datetime) -> str:
    """Return the notice to stamp at ``now``, failing closed to ``not-activated``.

    A notice outside the closed vocabulary, a naive time, or an observation more than
    five minutes before or after ``now`` cannot hide the watermark.
    """

    if state is None or state.notice not in NOTICES:
        return NOT_ACTIVATED
    observed_at = state.observed_at
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return NOT_ACTIVATED
    if abs(now - observed_at) > STALE_AFTER:
        return NOT_ACTIVATED
    return state.notice


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EntitlementStamp:
    """Cache the latest published state per process and derive the current stamp.

    Concurrent requests share one in-flight read. A failed read keeps the previous
    state, which still ages out after five minutes; an absent row clears it.
    """

    def __init__(
        self,
        source: EntitlementStateSource | None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        refresh_seconds: float = REFRESH_SECONDS,
        read_timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._source = source
        self._clock = clock
        self._monotonic = monotonic
        self._refresh_seconds = refresh_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._state: EntitlementState | None = None
        self._refreshed_at: float | None = None
        self._inflight: asyncio.Future[None] | None = None

    async def notice(self) -> str:
        """Return the stamp for a response that is starting now."""

        await self._refresh_if_due()
        return current_notice(self._state, now=self._clock())

    async def _refresh_if_due(self) -> None:
        if self._source is None:
            return
        if self._inflight is None:
            if (
                self._refreshed_at is not None
                and self._monotonic() - self._refreshed_at < self._refresh_seconds
            ):
                return
            self._inflight = asyncio.ensure_future(self._refresh(self._source))
        await asyncio.shield(self._inflight)

    async def _refresh(self, source: EntitlementStateSource) -> None:
        try:
            self._state = await asyncio.wait_for(
                source.latest(), timeout=self._read_timeout_seconds
            )
        except Exception as error:  # noqa: BLE001 - an unreadable row only ages the stamp
            _LOGGER.warning(
                "operator_entitlement_state_read_failed",
                extra={"error_type": type(error).__name__},
            )
        finally:
            self._refreshed_at = self._monotonic()
            self._inflight = None


class EntitlementStampMiddleware:
    """Add `X-FDAI-Entitlement` to every response whose request authenticated.

    A route cannot override the stamp: any header with the same name is replaced.
    """

    def __init__(self, app: ASGIApp, *, stamp: EntitlementStamp) -> None:
        self._app = app
        self._stamp = stamp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        marker = [False]
        token = _AUTHENTICATED.set(marker)

        async def send_with_stamp(message: Message) -> None:
            if message["type"] == "http.response.start" and marker[0]:
                notice = await self._stamp.notice()
                headers = [
                    (name, value)
                    for name, value in message.get("headers", ())
                    if name.lower() != _HEADER_KEY
                ]
                headers.append((_HEADER_KEY, notice.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_stamp)
        finally:
            _AUTHENTICATED.reset(token)


__all__ = [
    "ENTITLEMENT_HEADER",
    "EntitlementStamp",
    "EntitlementStampMiddleware",
    "EntitlementState",
    "EntitlementStateSource",
    "PostgresEntitlementStateSource",
    "current_notice",
    "mark_request_authenticated",
]
