"""Private immutable semantic compilation attempts with transactional content-free audit."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt
from psycopg.rows import (
    dict_row,
    tuple_row,
)
from psycopg.types.json import Jsonb

from fdai.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.rule_catalog.pipeline.distill.handover_retention import retention_decision


@dataclass(frozen=True, slots=True)
class PostgresHandoverSemanticPackages:
    """Core-only package store; unfinished claims remain held instead of repeating model I/O."""

    config: PostgresStateStoreConfig

    async def claim(self, key: str, identity: Mapping[str, Any]) -> bool:
        """Reserve once and audit before any compilation; a colliding identity is an error."""
        _validate(key, identity)
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "INSERT INTO handover_semantic_package(key,identity) VALUES(%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING key",
                    (key, Jsonb(dict(identity))),
                )
            ).fetchone()
            if row is not None:
                await self._audit(connection, key, "claimed")
                return True
            retained = await (
                await connection.execute(
                    "SELECT identity FROM handover_semantic_package WHERE key=%s",
                    (key,),
                )
            ).fetchone()
            if retained is None or retained["identity"] != identity:
                raise ValueError("semantic package claim identity conflicts")
            return False

    async def read(self, key: str) -> Mapping[str, Any] | None:
        """Read only after current source/retention checks; retired bytes remain inaccessible."""
        _validate(key, {})
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT identity,retention_descriptor,retired_at "
                    "FROM handover_semantic_package WHERE key=%s FOR UPDATE",
                    (key,),
                )
            ).fetchone()
            if row is None:
                return None
            if await self._maintain(connection, key, row, withdrawn=False, read_only=True):
                return {"identity": row["identity"], "package": None, "retired": True}
            row = await (
                await connection.execute(
                    "SELECT identity,package FROM handover_semantic_package WHERE key=%s",
                    (key,),
                )
            ).fetchone()
        return dict(row) if row is not None else None

    async def complete(
        self, key: str, identity: Mapping[str, Any], package: Mapping[str, Any]
    ) -> None:
        """Complete atomically with audit; an identical repeat is a no-op."""
        _validate(key, identity)
        _validate(key, package)
        descriptor = package.get("retention")
        receipt = HandoverSemanticReceipt.model_validate(package.get("receipt"))
        if (
            not isinstance(descriptor, Mapping)
            or descriptor.get("source_id") != identity.get("source_id")
            or receipt.package_ref != key
            or package.get("identity") != identity
        ):
            raise ValueError("semantic package completion requires its source retention descriptor")
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT identity,package,retired_at FROM handover_semantic_package "
                    "WHERE key=%s FOR UPDATE",
                    (key,),
                )
            ).fetchone()
            if row is None or row["identity"] != identity or row["retired_at"] is not None:
                raise ValueError("semantic package completion has no exact claim")
            if row["package"] is not None:
                if row["package"] != package:
                    raise ValueError("semantic package completion conflicts")
                return
            await connection.execute(
                "UPDATE handover_semantic_package SET package=%s,retention_descriptor=%s,"
                "receipt=%s WHERE key=%s",
                (
                    Jsonb(dict(package)),
                    Jsonb(dict(descriptor)),
                    Jsonb(receipt.model_dump(mode="json")),
                    key,
                ),
            )
            await self._audit(connection, key, "completed")

    async def reconcile(self, notice: HandoverKnowledgeNotice, *, withdrawn: bool) -> int:
        """Mimir checks 25 oldest source packages; immutable claim and receipt survive scrubbing."""
        notice.require_current(datetime.now(UTC))
        async with await self._connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT key,identity,retention_descriptor,retired_at "
                    "FROM handover_semantic_package "
                    "WHERE identity->>'source_id'=%s AND package IS NOT NULL "
                    "ORDER BY checked_at,key LIMIT 25 FOR UPDATE SKIP LOCKED",
                    (notice.source_id,),
                )
            ).fetchall()
            for row in rows:
                applies = (
                    withdrawn and row["identity"].get("source_revision", 0) <= notice.goal_revision
                )
                await self._maintain(connection, row["key"], row, withdrawn=applies)
        return len(rows)

    async def _maintain(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        key: str,
        row: Mapping[str, Any],
        *,
        withdrawn: bool,
        read_only: bool = False,
    ) -> bool:
        descriptor = row["retention_descriptor"]
        if descriptor is None:
            return row["retired_at"] is not None
        policy = await (
            await connection.execute(
                "SELECT fdai_core_handover_package_policy(%s) AS policy, clock_timestamp() AS at",
                (key,),
            )
        ).fetchone()
        if policy is None or not isinstance(policy["policy"], Mapping):
            raise ValueError("semantic package current retention policy is unavailable")
        retired, scrub = retention_decision(
            descriptor,
            policy["policy"],
            at=policy["at"],
            withdrawn=withdrawn,
            retired=row["retired_at"] is not None,
        )
        if read_only:
            return retired
        changed = await (
            await connection.execute(
                "UPDATE handover_semantic_package SET checked_at=clock_timestamp(), "
                "retired_at=CASE WHEN %s THEN COALESCE(retired_at,clock_timestamp()) "
                "ELSE retired_at END, "
                "package=CASE WHEN %s THEN NULL ELSE package END WHERE key=%s "
                "RETURNING receipt IS NOT NULL AS completed",
                (retired, scrub, key),
            )
        ).fetchone()
        if retired and row["retired_at"] is None:
            await self._audit(connection, key, "retired")
        if scrub and changed is not None and changed["completed"]:
            await self._audit(connection, key, "scrubbed")
        return retired

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        connection = await psycopg.AsyncConnection.connect(
            self.config.dsn,
            row_factory=dict_row,
            connect_timeout=self.config.connect_timeout_s,
        )
        try:
            role = await (await connection.execute("SELECT current_user AS role")).fetchone()
            if role is None or role["role"] != "fdai_core":
                raise PermissionError("semantic packages require the Core SQL role")
            await connection.execute(
                "SELECT set_config('statement_timeout',%s,true)",
                (str(self.config.statement_timeout_ms),),
            )
        except BaseException:
            await connection.close()
            raise
        return connection

    async def _audit(
        self, connection: psycopg.AsyncConnection[dict[str, Any]], key: str, state: str
    ) -> None:
        factory = connection.row_factory
        connection.row_factory = tuple_row  # type: ignore[assignment]
        try:
            await PostgresStateStore(config=self.config)._append_audit_in_transaction(
                connection,
                {
                    "actor": "Norns" if state in {"claimed", "completed"} else "Mimir",
                    "action_kind": "handover.semantic." + state,
                    "idempotency_key": key + ":" + state,
                    "package_ref": key,
                    "execution_authority": False,
                },
            )
        finally:
            connection.row_factory = factory


def _validate(key: str, value: Mapping[str, Any]) -> None:
    if re.fullmatch(r"human_assignment:semantic-package:[a-f0-9]{64}", key) is None:
        raise ValueError("semantic package key must be canonical")
    if len(json.dumps(value, sort_keys=True, allow_nan=False).encode()) > 1_048_576:
        raise ValueError("semantic package exceeds private storage bound")


__all__ = ["PostgresHandoverSemanticPackages"]
