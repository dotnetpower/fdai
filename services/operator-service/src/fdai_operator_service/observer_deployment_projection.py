"""Operator-owned no-authority observer proposal projections from the Core event topic."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    OBSERVER_PROPOSAL_GROUP,
    OBSERVER_PROPOSAL_TOPIC,
    ObserverProposalProjection,
)
from psycopg.rows import dict_row

from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
)
from fdai_operator_service.wara_projection import WaraProjectionPublisher, WaraProjectionSource

PREFIX = "operator-observer-proposal:v1:"
_LOGGER = logging.getLogger(__name__)


def merge_projection(
    previous: Mapping[str, Any] | None, incoming: ObserverProposalProjection
) -> dict[str, object]:
    """Preserve source ordering; a same-time conflict hides both claims until fresh evidence."""
    if previous is None:
        return {"projection": incoming.model_dump(mode="json"), "conflicted": False}
    if set(previous) != {"projection", "conflicted"} or type(previous["conflicted"]) is not bool:
        raise ValueError("observer projection checkpoint is invalid")
    old = ObserverProposalProjection.model_validate(previous["projection"])
    if old.target_ref != incoming.target_ref:
        raise ValueError("observer projection target changed")
    if incoming.source_revision < old.source_revision or incoming.published_at < old.published_at:
        return dict(previous)
    if incoming.projection_digest == old.projection_digest:
        return dict(previous)
    if incoming.published_at == old.published_at:
        highest_revision = incoming if incoming.source_revision > old.source_revision else old
        return {"projection": highest_revision.model_dump(mode="json"), "conflicted": True}
    return {"projection": incoming.model_dump(mode="json"), "conflicted": False}


class ObserverProjectionStore(Protocol):
    async def retain(self, projection: ObserverProposalProjection) -> None: ...
    async def read(self, target_ref: str | None) -> list[Mapping[str, Any]]: ...


class PostgresObserverProjectionStore:
    """Use only the Operator-owned state table and serialize one target's projection writes."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def retain(self, projection: ObserverProposalProjection) -> None:
        projection = ObserverProposalProjection.model_validate_json(projection.model_dump_json())
        key = PREFIX + canonical_digest({"target_ref": projection.target_ref})
        async with await psycopg.AsyncConnection.connect(
            self._dsn, connect_timeout=3, row_factory=dict_row
        ) as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL statement_timeout = '5000ms'")
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,)
                )
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s", (key,)
                )
                row = await cursor.fetchone()
                previous = row["value"] if row else None
                merged = merge_projection(previous, projection)
                if merged != previous:
                    await connection.execute(
                        "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                        (key, json.dumps(merged)),
                    )

    async def read(self, target_ref: str | None) -> list[Mapping[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, connect_timeout=3, row_factory=dict_row
        ) as connection:
            await connection.execute("SET LOCAL statement_timeout = '5000ms'")
            if target_ref is not None:
                key = PREFIX + canonical_digest({"target_ref": target_ref})
                cursor = await connection.execute("SELECT value FROM state_kv WHERE key=%s", (key,))
            else:
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key LIKE %s ORDER BY key LIMIT 129",
                    (PREFIX + "%",),
                )
            return [row["value"] for row in await cursor.fetchall()]


class ObserverProposalReader:
    """Role-gated operations adapter; expired content is not returned as a usable proposal."""

    def __init__(
        self,
        store: ObserverProjectionStore,
        *,
        fallback: ProjectionReader,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store, self._fallback = store, fallback
        self._now = now or (lambda: datetime.now(UTC))

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        if query.operation != "observer.deployment.proposals":
            return await self._fallback.read(query)
        target = query.params.get("target_ref", ())
        if len(target) > 1 or target and (not target[0] or len(target[0]) > 512):
            raise ProjectionUnavailableError("observer proposal target is invalid")
        try:
            async with asyncio.timeout(8):
                rows = await self._store.read(target[0] if target else None)
            items: list[dict[str, object]] = []
            for row in rows[:128]:
                if set(row) != {"projection", "conflicted"} or type(row["conflicted"]) is not bool:
                    raise ValueError("observer projection checkpoint is invalid")
                projection = ObserverProposalProjection.model_validate(row["projection"])
                if target and projection.target_ref != target[0]:
                    raise ValueError("observer projection target mismatch")
                current = (
                    projection.published_at <= self._now() < projection.expires_at
                    and not row["conflicted"]
                    and projection.state == "current"
                )
                items.append(
                    {
                        "target_ref": projection.target_ref,
                        "state": "current" if current else "unavailable",
                        "reason": "conflict"
                        if row["conflicted"]
                        else "current_evidence"
                        if current
                        else "expired_or_unavailable",
                        "proposal": projection.proposal.model_dump(mode="json")
                        if current and projection.proposal
                        else None,
                        "projection_digest": projection.projection_digest,
                        "expires_at": projection.expires_at.isoformat(),
                        "execution_authority": False,
                    }
                )
            return {
                "source": "core.observer-deployment.projections",
                "synthetic": False,
                "items": items,
                "complete": len(rows) <= 128,
                "execution_authority": False,
            }
        except (ValueError, psycopg.Error, TimeoutError) as exc:
            raise ProjectionUnavailableError("observer proposal evidence is unavailable") from exc


class ObserverProposalBridge:
    """Supervise commit-after-processing consumption on the existing service transport."""

    def __init__(
        self,
        *,
        store: ObserverProjectionStore,
        source: WaraProjectionSource,
        publisher: WaraProjectionPublisher,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store, self._source, self._publisher = store, source, publisher
        self._now = now or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._healthy = False

    def workers_ready(self) -> bool:
        return self._task is not None and not self._task.done() and self._healthy

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="observer-proposal-projection")

    async def aclose(self) -> None:
        task, self._task = self._task, None
        self._healthy = False
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                if not await self._source.probe_readiness():
                    raise RuntimeError("observer projection source unavailable")
                self._healthy = True
                async for payload in self._source.subscribe(
                    OBSERVER_PROPOSAL_TOPIC, OBSERVER_PROPOSAL_GROUP
                ):
                    try:
                        projection = ObserverProposalProjection.model_validate(payload)
                        if projection.published_at > self._now():
                            raise ValueError("observer projection publication is from the future")
                    except ValueError:
                        await self._publisher.publish(
                            OBSERVER_PROPOSAL_TOPIC + ".dlq",
                            "invalid-observer-projection",
                            {"reason": "invalid_observer_projection"},
                        )
                        continue
                    async with asyncio.timeout(8):
                        await self._store.retain(projection)
                self._healthy = False
            except Exception:
                self._healthy = False
                _LOGGER.warning("observer_proposal_projection_retrying")
            await asyncio.sleep(1)
