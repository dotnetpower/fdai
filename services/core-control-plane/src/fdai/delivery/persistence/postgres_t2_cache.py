"""Single-writer PostgreSQL lifecycle for exact-version T2 cache partitions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_IDEMPOTENCY_KEY_LENGTH = 256
_ROTATION_LOCK_NAMESPACE = 0x46444149
_ROTATION_LOCK_KEY = 0x54324348


class T2CacheLifecycleError(RuntimeError):
    """Report fail-closed cache state, identity, or replay conflicts."""


@dataclass(frozen=True, slots=True)
class PostgresT2CacheConfig:
    """Connection and bounded statement settings for the T2 cache writer."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("T2 cache PostgreSQL DSN must be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("T2 cache PostgreSQL timeouts must be positive")


@dataclass(frozen=True, slots=True)
class T2CacheEntry:
    """One unexpired cache value returned from the active catalog partition."""

    catalog_version: str
    input_hash: str
    output: Mapping[str, Any]
    model: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class T2CacheCatalogState:
    """Authoritative active and rollback catalog versions."""

    active_catalog_version: str
    rollback_catalog_version: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class T2CacheCatalogTransitionReceipt:
    """Replay-stable receipt for one promotion or rollback transaction."""

    idempotency_key: str
    transition_kind: str
    requested_catalog_version: str | None
    previous_active_catalog_version: str | None
    state: T2CacheCatalogState
    receipt_digest: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class T2CacheRotationReceipt:
    """Atomic record of the exact expired partitions removed by one rotation."""

    idempotency_key: str
    active_catalog_version: str
    rollback_catalog_version: str
    cutoff: datetime
    dropped_catalog_versions: tuple[str, ...]
    receipt_digest: str
    recorded_at: datetime


class PostgresT2Cache:
    """Own exact cache partitions, catalog transitions, TTL reads, and rotation."""

    def __init__(self, *, config: PostgresT2CacheConfig) -> None:
        self._config = config

    async def promote(
        self,
        *,
        catalog_version: str,
        idempotency_key: str,
    ) -> T2CacheCatalogTransitionReceipt:
        """Create and activate one exact catalog partition, retaining rollback."""
        _require_digest(catalog_version, "catalog_version")
        _require_idempotency_key(idempotency_key)
        async with await self._connect() as connection, connection.transaction():
            await self._prepare_transaction(connection)
            duplicate = await self._transition_receipt(connection, idempotency_key)
            if duplicate is not None:
                if (
                    duplicate.transition_kind != "promote"
                    or duplicate.requested_catalog_version != catalog_version
                ):
                    raise T2CacheLifecycleError(
                        "T2 cache idempotency key was used for another catalog transition"
                    )
                return duplicate
            await self._ensure_partition(connection, catalog_version)
            previous = await self._state(connection)
            revision = 1 if previous is None else previous.revision + 1
            rollback = (
                previous.rollback_catalog_version
                if previous is not None and previous.active_catalog_version == catalog_version
                else previous.active_catalog_version
                if previous is not None
                else None
            )
            state = T2CacheCatalogState(catalog_version, rollback, revision)
            await self._write_state(connection, state)
            return await self._insert_transition_receipt(
                connection,
                idempotency_key=idempotency_key,
                transition_kind="promote",
                requested_catalog_version=catalog_version,
                previous_active=previous.active_catalog_version if previous is not None else None,
                state=state,
            )

    async def rollback(
        self,
        *,
        idempotency_key: str,
    ) -> T2CacheCatalogTransitionReceipt:
        """Swap the exact active and rollback catalogs without reconstructing data."""
        _require_idempotency_key(idempotency_key)
        async with await self._connect() as connection, connection.transaction():
            await self._prepare_transaction(connection)
            duplicate = await self._transition_receipt(connection, idempotency_key)
            if duplicate is not None:
                if duplicate.transition_kind != "rollback":
                    raise T2CacheLifecycleError(
                        "T2 cache idempotency key was used for another catalog transition"
                    )
                return duplicate
            previous = await self._state(connection)
            if previous is None or previous.rollback_catalog_version is None:
                raise T2CacheLifecycleError("T2 cache rollback catalog is unavailable")
            state = T2CacheCatalogState(
                previous.rollback_catalog_version,
                previous.active_catalog_version,
                previous.revision + 1,
            )
            await self._write_state(connection, state)
            return await self._insert_transition_receipt(
                connection,
                idempotency_key=idempotency_key,
                transition_kind="rollback",
                requested_catalog_version=None,
                previous_active=previous.active_catalog_version,
                state=state,
            )

    async def put(
        self,
        *,
        catalog_version: str,
        input_hash: str,
        output: Mapping[str, Any],
        model: str,
        expires_at: datetime,
    ) -> None:
        """Write only to the current exact catalog partition with a finite TTL."""
        _require_digest(catalog_version, "catalog_version")
        _require_digest(input_hash, "input_hash")
        _require_utc(expires_at, "expires_at")
        if expires_at <= datetime.now(UTC):
            raise ValueError("T2 cache expires_at must be in the future")
        if not model.strip() or len(model) > 256:
            raise ValueError("T2 cache model must contain 1 to 256 characters")
        async with await self._connect() as connection, connection.transaction():
            await self._prepare_transaction(connection)
            state = await self._state(connection)
            if state is None or state.active_catalog_version != catalog_version:
                raise T2CacheLifecycleError("T2 cache writes require the active catalog version")
            await connection.execute(
                """
                INSERT INTO t2_cache (
                    catalog_version, input_hash, output, model, expires_at
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (catalog_version, input_hash, Jsonb(dict(output)), model, expires_at),
            )

    async def get(
        self,
        *,
        catalog_version: str,
        input_hash: str,
        observed_at: datetime | None = None,
    ) -> T2CacheEntry | None:
        """Read an unexpired value only from the current exact catalog version."""
        _require_digest(catalog_version, "catalog_version")
        _require_digest(input_hash, "input_hash")
        at = observed_at or datetime.now(UTC)
        _require_utc(at, "observed_at")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                """
                SELECT cache.catalog_version, cache.input_hash, cache.output, cache.model,
                       cache.created_at, cache.expires_at
                  FROM t2_cache AS cache
                  JOIN t2_cache_catalog_state AS state
                    ON state.singleton = TRUE
                   AND state.active_catalog_version = cache.catalog_version
                 WHERE cache.catalog_version = %s
                   AND cache.input_hash = %s
                   AND cache.expires_at > %s
                 ORDER BY cache.expires_at DESC, cache.created_at DESC
                 LIMIT 1
                """,
                (catalog_version, input_hash, at),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            output = row["output"]
            if not isinstance(output, dict):
                raise T2CacheLifecycleError("T2 cache output is not a JSON object")
            return T2CacheEntry(
                catalog_version=str(row["catalog_version"]),
                input_hash=str(row["input_hash"]),
                output=output,
                model=str(row["model"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
            )

    async def rotate(
        self,
        *,
        active_catalog_version: str,
        rollback_catalog_version: str,
        idempotency_key: str,
        cutoff: datetime,
    ) -> T2CacheRotationReceipt:
        """Drop only fully expired, unprotected partitions and append one receipt."""
        _require_digest(active_catalog_version, "active_catalog_version")
        _require_digest(rollback_catalog_version, "rollback_catalog_version")
        _require_idempotency_key(idempotency_key)
        _require_utc(cutoff, "cutoff")
        if active_catalog_version == rollback_catalog_version:
            raise ValueError("active and rollback catalog versions must differ")
        async with await self._connect() as connection, connection.transaction():
            await self._prepare_transaction(connection)
            duplicate = await self._rotation_receipt(connection, idempotency_key)
            if duplicate is not None:
                if (
                    duplicate.active_catalog_version != active_catalog_version
                    or duplicate.rollback_catalog_version != rollback_catalog_version
                    or duplicate.cutoff != cutoff
                ):
                    raise T2CacheLifecycleError(
                        "T2 cache idempotency key was used for another rotation"
                    )
                return duplicate
            state = await self._state(connection)
            if state is None:
                raise T2CacheLifecycleError("T2 cache catalog state is unavailable")
            if (
                state.active_catalog_version != active_catalog_version
                or state.rollback_catalog_version != rollback_catalog_version
            ):
                raise T2CacheLifecycleError(
                    "T2 cache rotation does not match authoritative active and rollback catalogs"
                )
            candidates = await self._rotation_candidates(
                connection,
                active_catalog_version=active_catalog_version,
                rollback_catalog_version=rollback_catalog_version,
            )
            dropped: list[str] = []
            for catalog_version, partition_name in candidates:
                if await self._partition_is_expired(connection, partition_name, cutoff):
                    await self._drop_partition(connection, partition_name)
                    await connection.execute(
                        "DELETE FROM t2_cache_partition_registry WHERE catalog_version = %s",
                        (catalog_version,),
                    )
                    dropped.append(catalog_version)
            return await self._insert_rotation_receipt(
                connection,
                idempotency_key=idempotency_key,
                active_catalog_version=active_catalog_version,
                rollback_catalog_version=rollback_catalog_version,
                cutoff=cutoff,
                dropped_catalog_versions=tuple(dropped),
            )

    async def state(self) -> T2CacheCatalogState | None:
        """Return the current authoritative catalog state."""
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._state(connection, lock=False)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )

    async def _prepare_transaction(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await self._timeout(connection)
        await connection.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (_ROTATION_LOCK_NAMESPACE, _ROTATION_LOCK_KEY),
        )

    async def _ensure_partition(
        self,
        connection: psycopg.AsyncConnection[Any],
        catalog_version: str,
    ) -> None:
        partition_name = _partition_name(catalog_version)
        cursor = await connection.execute(
            """
            SELECT catalog_version
              FROM t2_cache_partition_registry
             WHERE partition_name = %s
            """,
            (partition_name,),
        )
        registered = await cursor.fetchone()
        if registered is not None and registered["catalog_version"] != catalog_version:
            raise T2CacheLifecycleError("T2 cache partition name collides with another catalog")
        cursor = await connection.execute(
            "SELECT fdai_t2_cache_create_partition(%s) AS partition_name",
            (catalog_version,),
        )
        row = await cursor.fetchone()
        if row is None or row["partition_name"] != partition_name:
            raise T2CacheLifecycleError("T2 cache partition registry is inconsistent")

    async def _state(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        lock: bool = True,
    ) -> T2CacheCatalogState | None:
        suffix = sql.SQL(" FOR UPDATE") if lock else sql.SQL("")
        cursor = await connection.execute(
            sql.SQL(
                """
                SELECT active_catalog_version, rollback_catalog_version, revision
                  FROM t2_cache_catalog_state
                 WHERE singleton = TRUE
                """
            )
            + suffix
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return T2CacheCatalogState(
            active_catalog_version=str(row["active_catalog_version"]),
            rollback_catalog_version=(
                str(row["rollback_catalog_version"])
                if row["rollback_catalog_version"] is not None
                else None
            ),
            revision=int(row["revision"]),
        )

    async def _write_state(
        self,
        connection: psycopg.AsyncConnection[Any],
        state: T2CacheCatalogState,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO t2_cache_catalog_state (
                singleton, active_catalog_version, rollback_catalog_version, revision
            )
            VALUES (TRUE, %s, %s, %s)
            ON CONFLICT (singleton) DO UPDATE
               SET active_catalog_version = EXCLUDED.active_catalog_version,
                   rollback_catalog_version = EXCLUDED.rollback_catalog_version,
                   revision = EXCLUDED.revision,
                   updated_at = CURRENT_TIMESTAMP
            """,
            (
                state.active_catalog_version,
                state.rollback_catalog_version,
                state.revision,
            ),
        )

    async def _transition_receipt(
        self,
        connection: psycopg.AsyncConnection[Any],
        idempotency_key: str,
    ) -> T2CacheCatalogTransitionReceipt | None:
        cursor = await connection.execute(
            "SELECT * FROM t2_cache_catalog_transition WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return _transition_receipt(row) if row is not None else None

    async def _insert_transition_receipt(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        idempotency_key: str,
        transition_kind: str,
        requested_catalog_version: str | None,
        previous_active: str | None,
        state: T2CacheCatalogState,
    ) -> T2CacheCatalogTransitionReceipt:
        digest = _canonical_digest(
            {
                "active_catalog_version": state.active_catalog_version,
                "idempotency_key": idempotency_key,
                "previous_active_catalog_version": previous_active,
                "requested_catalog_version": requested_catalog_version,
                "rollback_catalog_version": state.rollback_catalog_version,
                "state_revision": state.revision,
                "transition_kind": transition_kind,
            }
        )
        cursor = await connection.execute(
            """
            INSERT INTO t2_cache_catalog_transition (
                idempotency_key, transition_kind, requested_catalog_version,
                previous_active_catalog_version, active_catalog_version,
                rollback_catalog_version, state_revision, receipt_digest
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                idempotency_key,
                transition_kind,
                requested_catalog_version,
                previous_active,
                state.active_catalog_version,
                state.rollback_catalog_version,
                state.revision,
                digest,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("T2 cache transition receipt insert returned no row")
        return _transition_receipt(row)

    async def _rotation_candidates(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        active_catalog_version: str,
        rollback_catalog_version: str,
    ) -> tuple[tuple[str, str], ...]:
        cursor = await connection.execute(
            """
            SELECT catalog_version, partition_name
              FROM t2_cache_partition_registry
             WHERE catalog_version <> %s
               AND catalog_version <> %s
             ORDER BY catalog_version
            """,
            (active_catalog_version, rollback_catalog_version),
        )
        return tuple(
            (str(row["catalog_version"]), str(row["partition_name"]))
            for row in await cursor.fetchall()
        )

    async def _partition_is_expired(
        self,
        connection: psycopg.AsyncConnection[Any],
        partition_name: str,
        cutoff: datetime,
    ) -> bool:
        cursor = await connection.execute(
            sql.SQL("SELECT count(*) = 0 OR max(expires_at) <= %s AS eligible FROM {}").format(
                sql.Identifier(partition_name)
            ),
            (cutoff,),
        )
        row = await cursor.fetchone()
        return row is not None and row["eligible"] is True

    async def _drop_partition(
        self,
        connection: psycopg.AsyncConnection[Any],
        partition_name: str,
    ) -> None:
        cursor = await connection.execute(
            "SELECT fdai_t2_cache_drop_partition(%s) AS catalog_version",
            (partition_name,),
        )
        if await cursor.fetchone() is None:
            raise RuntimeError("T2 cache partition drop returned no catalog version")

    async def _rotation_receipt(
        self,
        connection: psycopg.AsyncConnection[Any],
        idempotency_key: str,
    ) -> T2CacheRotationReceipt | None:
        cursor = await connection.execute(
            "SELECT * FROM t2_cache_rotation_receipt WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return _rotation_receipt(row) if row is not None else None

    async def _insert_rotation_receipt(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        idempotency_key: str,
        active_catalog_version: str,
        rollback_catalog_version: str,
        cutoff: datetime,
        dropped_catalog_versions: tuple[str, ...],
    ) -> T2CacheRotationReceipt:
        digest = _canonical_digest(
            {
                "active_catalog_version": active_catalog_version,
                "cutoff": cutoff.isoformat(),
                "dropped_catalog_versions": dropped_catalog_versions,
                "idempotency_key": idempotency_key,
                "rollback_catalog_version": rollback_catalog_version,
            }
        )
        cursor = await connection.execute(
            """
            INSERT INTO t2_cache_rotation_receipt (
                idempotency_key, active_catalog_version, rollback_catalog_version,
                cutoff, dropped_catalog_versions, receipt_digest
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                idempotency_key,
                active_catalog_version,
                rollback_catalog_version,
                cutoff,
                list(dropped_catalog_versions),
                digest,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("T2 cache rotation receipt insert returned no row")
        return _rotation_receipt(row)


def _require_digest(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} must be an immutable SHA-256 digest")


def _require_idempotency_key(value: str) -> None:
    if not value or len(value) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError("idempotency_key must contain 1 to 256 characters")


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


def _partition_name(catalog_version: str) -> str:
    suffix = catalog_version.removeprefix("sha256:")[:24]
    return f"t2_cache_p_{suffix}"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _transition_receipt(row: Mapping[str, Any]) -> T2CacheCatalogTransitionReceipt:
    return T2CacheCatalogTransitionReceipt(
        idempotency_key=str(row["idempotency_key"]),
        transition_kind=str(row["transition_kind"]),
        requested_catalog_version=(
            str(row["requested_catalog_version"])
            if row["requested_catalog_version"] is not None
            else None
        ),
        previous_active_catalog_version=(
            str(row["previous_active_catalog_version"])
            if row["previous_active_catalog_version"] is not None
            else None
        ),
        state=T2CacheCatalogState(
            active_catalog_version=str(row["active_catalog_version"]),
            rollback_catalog_version=(
                str(row["rollback_catalog_version"])
                if row["rollback_catalog_version"] is not None
                else None
            ),
            revision=int(row["state_revision"]),
        ),
        receipt_digest=str(row["receipt_digest"]),
        recorded_at=row["recorded_at"],
    )


def _rotation_receipt(row: Mapping[str, Any]) -> T2CacheRotationReceipt:
    return T2CacheRotationReceipt(
        idempotency_key=str(row["idempotency_key"]),
        active_catalog_version=str(row["active_catalog_version"]),
        rollback_catalog_version=str(row["rollback_catalog_version"]),
        cutoff=row["cutoff"],
        dropped_catalog_versions=tuple(str(item) for item in row["dropped_catalog_versions"]),
        receipt_digest=str(row["receipt_digest"]),
        recorded_at=row["recorded_at"],
    )


__all__ = [
    "PostgresT2Cache",
    "PostgresT2CacheConfig",
    "T2CacheCatalogState",
    "T2CacheCatalogTransitionReceipt",
    "T2CacheEntry",
    "T2CacheLifecycleError",
    "T2CacheRotationReceipt",
]
