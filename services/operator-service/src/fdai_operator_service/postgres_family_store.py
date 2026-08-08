"""PostgreSQL storage primitives for independently composed Operator families."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

_PROJECTION_PREFIX: Final = "operator-projection:"
_PROPOSAL_PREFIX: Final = "operator-proposal:"
_READINESS_SQL: Final = """
SELECT probe.ready
    FROM (VALUES (1)) AS probe(ready)
    LEFT JOIN (
            SELECT key, value, updated_at
                FROM state_kv
             LIMIT 0
    ) AS required_state ON FALSE
    LEFT JOIN (
            SELECT seq, event_id, correlation_id, actor, action_kind, mode,
                         entry, previous_hash, entry_hash, created_at
                FROM audit_log
             LIMIT 0
    ) AS required_audit ON FALSE
"""


class PostgresFamilyStoreUnavailableError(RuntimeError):
    """The authoritative PostgreSQL family store could not satisfy a request."""


class PostgresProposalConflictError(RuntimeError):
    """An idempotency key is already bound to different proposal content."""


PostgresFamilyStoreUnavailable = PostgresFamilyStoreUnavailableError
PostgresProposalConflict = PostgresProposalConflictError


@dataclass(frozen=True, slots=True)
class PostgresFamilyStoreConfig:
    """Bound PostgreSQL connection and statement timeouts for family adapters."""

    dsn: str
    statement_timeout_ms: int = 20_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PostgreSQL DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgreSQL timeouts MUST be positive")


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """Durable inert proposal acceptance loaded from the service outbox namespace."""

    proposal_id: str
    accepted_at: str
    duplicate: bool
    record: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StoredReplayEvent:
    """One monotonic audit event selected for an Operator replay stream."""

    sequence: int
    event: str
    data: Mapping[str, object]


class PostgresFamilyStore:
    """Read projections and atomically append proposal-only outbox records."""

    def __init__(self, config: PostgresFamilyStoreConfig) -> None:
        self._config = config

    async def probe_readiness(self) -> bool:
        """Verify required projection tables, columns, grants, and connectivity."""
        rows = await self._fetch_all(_READINESS_SQL, {})
        return len(rows) == 1 and rows[0].get("ready") == 1

    async def read_state(self, key: str) -> dict[str, object] | None:
        """Read one existing authoritative state record by its stable key."""
        rows = await self._fetch_all(
            "SELECT value FROM state_kv WHERE key = %(key)s",
            {"key": key},
        )
        return None if not rows else _json_object(rows[0].get("value"), label=key)

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        """Create one state record atomically and report whether this call won."""
        inserted, _ = await self._insert_if_absent(key=key, value=value)
        return inserted

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        """Replace one service-owned state record without applying external effects."""
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(
                        connection,
                        self._config.statement_timeout_ms,
                    )
                    await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key)
                        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        (key, json.dumps(dict(value), separators=(",", ":"), sort_keys=True)),
                    )
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL state store is unavailable"
            ) from exc

    async def find_state(
        self,
        *,
        prefix: str,
        field: str,
        value: str,
    ) -> dict[str, object] | None:
        """Find the newest state record matching one bounded JSON text field."""
        if not field.replace("_", "").isalnum():
            raise ValueError("state field MUST be an ASCII identifier")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = await self._fetch_all(
            """
            SELECT value
              FROM state_kv
             WHERE key LIKE %(prefix)s ESCAPE '\\'
               AND value ->> %(field)s = %(value)s
             ORDER BY updated_at DESC, key DESC
             LIMIT 1
            """,
            {"prefix": f"{escaped_prefix}%", "field": field, "value": value},
        )
        return None if not rows else _json_object(rows[0].get("value"), label=prefix)

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        """Read one explicitly materialized non-synthetic projection."""
        key = _projection_key(family, operation)
        rows = await self._fetch_all(
            "SELECT value FROM state_kv WHERE key = %(key)s",
            {"key": key},
        )
        if not rows:
            raise PostgresFamilyStoreUnavailable(
                f"authoritative {family} projection is unavailable for {operation}"
            )
        return _json_object(rows[0].get("value"), label=key)

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        """Atomically persist a typed proposal and return its durable outbox receipt."""
        request = {
            "family": family,
            "operation": operation,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
        }
        request_digest = _digest(request)
        proposal_id = f"operator-{request_digest[:32]}"
        accepted_at = datetime.now(UTC).isoformat()
        record: dict[str, object] = {
            "kind": "operator.proposal",
            "proposal_id": proposal_id,
            "request_digest": request_digest,
            "dispatch_status": "pending",
            "mode": "shadow",
            "accepted_at": accepted_at,
            **request,
        }
        key = _proposal_key(family, idempotency_key)
        inserted, stored = await self._insert_if_absent(key=key, value=record)
        stored_digest = stored.get("request_digest")
        if stored_digest != request_digest:
            raise PostgresProposalConflict(
                "idempotency key conflicts with a different durable Operator proposal"
            )
        stored_id = stored.get("proposal_id")
        stored_at = stored.get("accepted_at")
        if not isinstance(stored_id, str) or not isinstance(stored_at, str):
            raise PostgresFamilyStoreUnavailable("stored Operator proposal receipt is malformed")
        return StoredProposal(
            proposal_id=stored_id,
            accepted_at=stored_at,
            duplicate=not inserted,
            record=stored,
        )

    async def replay(
        self,
        *,
        stream: str,
        principal_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[StoredReplayEvent, ...]:
        """Read principal-scoped monotonic records from the authoritative audit ledger."""
        _bounded_component("stream", stream)
        _bounded_component("principal_id", principal_id)
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence MUST be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("replay limit MUST be in [1, 500]")
        rows = await self._fetch_all(
            """
            SELECT seq, action_kind, entry
              FROM audit_log
             WHERE seq > %(after_sequence)s
               AND (action_kind = %(stream)s OR entry ->> 'stream' = %(stream)s)
                             AND entry ->> 'principal_id' = %(principal_id)s
             ORDER BY seq ASC
             LIMIT %(limit)s
            """,
            {
                "after_sequence": after_sequence or 0,
                "stream": stream,
                "principal_id": principal_id,
                "limit": limit,
            },
        )
        events: list[StoredReplayEvent] = []
        for row in rows:
            sequence = row.get("seq")
            event = row.get("action_kind")
            if not isinstance(sequence, int) or not isinstance(event, str):
                raise PostgresFamilyStoreUnavailable("audit replay row is malformed")
            events.append(
                StoredReplayEvent(
                    sequence=sequence,
                    event=event,
                    data=_json_object(row.get("entry"), label=f"audit_log[{sequence}].entry"),
                )
            )
        return tuple(events)

    async def _insert_if_absent(
        self,
        *,
        key: str,
        value: Mapping[str, object],
    ) -> tuple[bool, dict[str, object]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(
                        connection,
                        self._config.statement_timeout_ms,
                    )
                    cursor = await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO NOTHING
                        RETURNING value
                        """,
                        (key, json.dumps(dict(value), separators=(",", ":"), sort_keys=True)),
                    )
                    inserted_row = await cursor.fetchone()
                    if inserted_row is not None:
                        return True, _json_object(inserted_row.get("value"), label=key)
                    cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR SHARE",
                        (key,),
                    )
                    existing_row = await cursor.fetchone()
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL proposal outbox is unavailable"
            ) from exc
        if existing_row is None:
            raise PostgresFamilyStoreUnavailable("durable Operator proposal disappeared")
        return False, _json_object(existing_row.get("value"), label=key)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(
                        connection,
                        self._config.statement_timeout_ms,
                    )
                    cursor = await connection.execute(statement, parameters)
                    return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL family store is unavailable"
            ) from exc


class UnavailablePostgresFamilyStore(PostgresFamilyStore):
    """Fail immediately when PostgreSQL family storage is not configured."""

    def __init__(self) -> None:
        super().__init__(PostgresFamilyStoreConfig("postgresql://unavailable.invalid/fdai"))

    async def read_state(self, key: str) -> dict[str, object] | None:
        del key
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        del key, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        del key, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def find_state(
        self,
        *,
        prefix: str,
        field: str,
        value: str,
    ) -> dict[str, object] | None:
        del prefix, field, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        del family, operation
        raise PostgresFamilyStoreUnavailable("authoritative projection is unavailable")

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del family, operation, principal_id, idempotency_key, payload
        raise PostgresFamilyStoreUnavailable("proposal outbox is unavailable")

    async def replay(
        self,
        *,
        stream: str,
        principal_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[StoredReplayEvent, ...]:
        del stream, principal_id, after_sequence, limit
        raise PostgresFamilyStoreUnavailable("authoritative replay is unavailable")


def _projection_key(family: str, operation: str) -> str:
    _bounded_component("family", family)
    _bounded_component("operation", operation)
    return f"{_PROJECTION_PREFIX}{family}:{operation}"


def _proposal_key(family: str, idempotency_key: str) -> str:
    _bounded_component("family", family)
    if not idempotency_key.strip() or len(idempotency_key) > 256:
        raise ValueError("idempotency_key MUST be a bounded non-empty string")
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_PROPOSAL_PREFIX}{family}:{digest}"


def _bounded_component(name: str, value: str) -> None:
    if not value.strip() or len(value) > 128:
        raise ValueError(f"{name} MUST be a bounded non-empty string")


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PostgresFamilyStoreUnavailable(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    return f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value


async def _set_statement_timeout(
    connection: psycopg.AsyncConnection[object],
    timeout_ms: int,
) -> None:
    await connection.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (str(timeout_ms),),
    )


__all__ = [
    "PostgresFamilyStore",
    "PostgresFamilyStoreConfig",
    "PostgresFamilyStoreUnavailable",
    "PostgresProposalConflict",
    "StoredProposal",
    "StoredReplayEvent",
    "UnavailablePostgresFamilyStore",
]
