"""PostgreSQL adapters for typed conversation policies and proactive briefings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_user_context_projection_queue import (
    enqueue_projection_upsert,
)
from fdai.shared.providers.briefing import (
    BriefingConflictError,
    BriefingDeliveryMode,
    BriefingKind,
    BriefingRun,
    BriefingRunStatus,
    BriefingSpec,
    BriefingSubscription,
    ConversationPolicyKind,
    ConversationPolicyRecord,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAudience,
    ContinuationMode,
    ScheduledResultOrigin,
)


@dataclass(frozen=True, slots=True)
class PostgresBriefingStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresBriefingStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresBriefingStoreConfig timeouts MUST be positive")


class _PostgresBase:
    def __init__(self, *, config: PostgresBriefingStoreConfig) -> None:
        self._config: Final = config

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


class PostgresConversationPolicyStore(_PostgresBase):
    async def put(
        self, record: ConversationPolicyRecord, *, expected_revision: int | None = None
    ) -> ConversationPolicyRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT revision FROM conversation_policy "
                "WHERE principal_id = %s AND policy_id = %s FOR UPDATE",
                (record.principal_id, record.policy_id),
            )
            row = await cursor.fetchone()
            current = int(row["revision"]) if row is not None else 0
            if expected_revision is not None and expected_revision != current:
                raise BriefingConflictError(
                    f"policy revision mismatch: expected {expected_revision}, current {current}"
                )
            revision = current + 1
            try:
                await connection.execute(
                    "INSERT INTO conversation_policy "
                    "(principal_id, policy_id, kind, enabled, revision, confirmed_at, "
                    "source_turn_id, briefing_spec, response_defaults) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) "
                    "ON CONFLICT (principal_id, policy_id) DO UPDATE SET "
                    "kind = EXCLUDED.kind, enabled = EXCLUDED.enabled, "
                    "revision = EXCLUDED.revision, confirmed_at = EXCLUDED.confirmed_at, "
                    "source_turn_id = EXCLUDED.source_turn_id, "
                    "briefing_spec = EXCLUDED.briefing_spec, "
                    "response_defaults = EXCLUDED.response_defaults",
                    (
                        record.principal_id,
                        record.policy_id,
                        record.kind.value,
                        record.enabled,
                        revision,
                        record.confirmed_at,
                        record.source_turn_id,
                        (_spec_json(record.briefing_spec) if record.briefing_spec else None),
                        json.dumps(dict(record.response_defaults)),
                    ),
                )
            except psycopg.errors.ForeignKeyViolation as exc:
                raise BriefingConflictError("policy source turn was not found") from exc
            await enqueue_projection_upsert(
                connection,
                projection_kind="policy",
                principal_id=record.principal_id,
                record_id=record.policy_id,
            )
        return ConversationPolicyRecord(
            policy_id=record.policy_id,
            principal_id=record.principal_id,
            kind=record.kind,
            enabled=record.enabled,
            revision=revision,
            confirmed_at=record.confirmed_at,
            source_turn_id=record.source_turn_id,
            briefing_spec=record.briefing_spec,
            response_defaults=dict(record.response_defaults),
        )

    async def list_for_principal(
        self, *, principal_id: str
    ) -> tuple[ConversationPolicyRecord, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, policy_id, kind, enabled, revision, confirmed_at, "
                "source_turn_id, briefing_spec, response_defaults FROM conversation_policy "
                "WHERE principal_id = %s ORDER BY policy_id",
                (principal_id,),
            )
            return tuple(_policy(row) for row in await cursor.fetchall())

    async def delete(
        self,
        *,
        principal_id: str,
        policy_id: str,
        expected_revision: int,
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'policy:' || principal_id || ':' || policy_id "
                "FROM conversation_policy WHERE principal_id = %s AND policy_id = %s "
                "AND revision = %s "
                "ON CONFLICT (object_id) DO NOTHING",
                (principal_id, policy_id, expected_revision),
            )
            cursor = await connection.execute(
                "DELETE FROM conversation_policy WHERE principal_id = %s AND policy_id = %s "
                "AND revision = %s "
                "RETURNING policy_id",
                (principal_id, policy_id, expected_revision),
            )
            return await cursor.fetchone() is not None


class PostgresBriefingSubscriptionStore(_PostgresBase):
    async def create(self, record: BriefingSubscription) -> BriefingSubscription:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO briefing_subscription "
                    "(principal_id, subscription_id, name, spec, cron_expression, timezone, "
                    "delivery_modes, channel_binding_ref, enabled, next_run_at, created_at, "
                    "max_lateness_seconds, continuation_mode, continuation_origin, "
                    "continuation_ttl_seconds, revision) VALUES "
                    "(%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, "
                    "%s, %s::jsonb, %s, 1)",
                    (
                        record.principal_id,
                        record.subscription_id,
                        record.name,
                        _spec_json(record.spec),
                        record.cron_expression,
                        record.timezone,
                        json.dumps([mode.value for mode in record.delivery_modes]),
                        record.channel_binding_ref,
                        record.enabled,
                        record.next_run_at,
                        record.created_at,
                        record.max_lateness_seconds,
                        record.continuation_mode.value,
                        (
                            _origin_json(record.continuation_origin)
                            if record.continuation_origin is not None
                            else None
                        ),
                        record.continuation_ttl_seconds,
                    ),
                )
                await enqueue_projection_upsert(
                    connection,
                    projection_kind="briefing_subscription",
                    principal_id=record.principal_id,
                    record_id=record.subscription_id,
                )
            except psycopg.errors.UniqueViolation as exc:
                raise BriefingConflictError(
                    f"subscription {record.subscription_id!r} already exists"
                ) from exc
        return _with_subscription_revision(record, 1)

    async def list_for_principal(self, *, principal_id: str) -> tuple[BriefingSubscription, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                _SUBSCRIPTION_SELECT
                + " WHERE principal_id = %s ORDER BY next_run_at, subscription_id",
                (principal_id,),
            )
            return tuple(_subscription(row) for row in await cursor.fetchall())

    async def claim_due(
        self, *, now: datetime, limit: int, lease_owner: str, lease_seconds: int
    ) -> tuple[BriefingSubscription, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT principal_id, subscription_id FROM briefing_subscription "
                "WHERE enabled AND next_run_at <= %s "
                "AND (lease_until IS NULL OR lease_until <= %s) "
                "ORDER BY next_run_at, subscription_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (now, now, limit),
            )
            keys = [
                (row["principal_id"], row["subscription_id"]) for row in await cursor.fetchall()
            ]
            if not keys:
                return ()
            lease_until = now + timedelta(seconds=lease_seconds)
            claimed: list[BriefingSubscription] = []
            for principal_id, subscription_id in keys:
                await connection.execute(
                    "UPDATE briefing_subscription SET lease_owner = %s, lease_until = %s "
                    "WHERE principal_id = %s AND subscription_id = %s",
                    (lease_owner, lease_until, principal_id, subscription_id),
                )
                read = await connection.execute(
                    _SUBSCRIPTION_SELECT + " WHERE principal_id = %s AND subscription_id = %s",
                    (principal_id, subscription_id),
                )
                row = await read.fetchone()
                if row is not None:
                    claimed.append(_subscription(row))
        return tuple(claimed)

    async def advance(
        self,
        *,
        subscription_id: str,
        principal_id: str,
        expected_revision: int,
        next_run_at: datetime,
    ) -> BriefingSubscription:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE briefing_subscription SET next_run_at = %s, revision = revision + 1, "
                "lease_owner = NULL, lease_until = NULL WHERE principal_id = %s "
                "AND subscription_id = %s AND revision = %s RETURNING revision",
                (next_run_at, principal_id, subscription_id, expected_revision),
            )
            if await cursor.fetchone() is None:
                raise BriefingConflictError("subscription revision mismatch or record not found")
            read = await connection.execute(
                _SUBSCRIPTION_SELECT + " WHERE principal_id = %s AND subscription_id = %s",
                (principal_id, subscription_id),
            )
            row = await read.fetchone()
            if row is None:
                raise LookupError(f"subscription {subscription_id!r} not found")
        return _subscription(row)

    async def delete(
        self,
        *,
        principal_id: str,
        subscription_id: str,
        expected_revision: int,
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'briefing-subscription:' || principal_id || ':' || subscription_id "
                "FROM briefing_subscription WHERE principal_id = %s AND subscription_id = %s "
                "AND revision = %s "
                "ON CONFLICT (object_id) DO NOTHING",
                (principal_id, subscription_id, expected_revision),
            )
            cursor = await connection.execute(
                "DELETE FROM briefing_subscription WHERE principal_id = %s "
                "AND subscription_id = %s AND revision = %s RETURNING subscription_id",
                (principal_id, subscription_id, expected_revision),
            )
            return await cursor.fetchone() is not None


class PostgresBriefingRunStore(_PostgresBase):
    async def create(self, run: BriefingRun) -> BriefingRun:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                cursor = await connection.execute(
                    "INSERT INTO briefing_run "
                    "(principal_id, run_id, subscription_id, conversation_id, scheduled_for, "
                    "started_at, status, idempotency_key, title, body_markdown, item_count, "
                    "evidence_refs, source_errors, continuation_mode, continuation_origin, "
                    "result_digest) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
                    "%s::jsonb, %s, %s::jsonb, %s) "
                    "ON CONFLICT (principal_id, idempotency_key) DO NOTHING RETURNING run_id",
                    (
                        run.principal_id,
                        run.run_id,
                        run.subscription_id,
                        run.conversation_id,
                        run.scheduled_for,
                        run.started_at,
                        run.status.value,
                        run.idempotency_key,
                        run.title,
                        run.body_markdown,
                        run.item_count,
                        json.dumps(run.evidence_refs),
                        json.dumps(run.source_errors),
                        run.continuation_mode.value,
                        (
                            _origin_json(run.continuation_origin)
                            if run.continuation_origin is not None
                            else None
                        ),
                        run.result_digest,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise BriefingConflictError(f"briefing run {run.run_id!r} conflicts") from exc
            if await cursor.fetchone() is None:
                read = await connection.execute(
                    _RUN_SELECT + " WHERE principal_id = %s AND idempotency_key = %s",
                    (run.principal_id, run.idempotency_key),
                )
                row = await read.fetchone()
                if row is None or _run(row) != run:
                    raise BriefingConflictError(
                        f"briefing idempotency key {run.idempotency_key!r} conflicts"
                    )
                return _run(row)
        return run

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> tuple[BriefingRun, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            cursor = await connection.execute(
                _RUN_SELECT + " WHERE principal_id = %s ORDER BY started_at DESC LIMIT %s",
                (principal_id, limit),
            )
            return tuple(_run(row) for row in await cursor.fetchall())

    async def purge_before(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> tuple[BriefingRun, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH selected AS ("
                "SELECT principal_id, run_id FROM briefing_run "
                "WHERE started_at < %s ORDER BY started_at, run_id "
                "FOR UPDATE SKIP LOCKED LIMIT %s"
                ") DELETE FROM briefing_run AS run USING selected "
                "WHERE run.principal_id = selected.principal_id "
                "AND run.run_id = selected.run_id "
                "RETURNING run.principal_id, run.run_id, run.subscription_id, "
                "run.conversation_id, run.scheduled_for, run.started_at, run.status, "
                "run.idempotency_key, run.title, run.body_markdown, run.item_count, "
                "run.evidence_refs, run.source_errors, run.continuation_mode, "
                "run.continuation_origin, run.result_digest",
                (before, limit),
            )
            return tuple(_run(row) for row in await cursor.fetchall())


_SUBSCRIPTION_SELECT = (
    "SELECT principal_id, subscription_id, name, spec, cron_expression, timezone, "
    "delivery_modes, channel_binding_ref, enabled, next_run_at, created_at, "
    "max_lateness_seconds, continuation_mode, continuation_origin, "
    "continuation_ttl_seconds, revision FROM briefing_subscription"
)
_RUN_SELECT = (
    "SELECT principal_id, run_id, subscription_id, conversation_id, scheduled_for, "
    "started_at, status, idempotency_key, title, body_markdown, item_count, "
    "evidence_refs, source_errors, continuation_mode, continuation_origin, result_digest "
    "FROM briefing_run"
)


def _spec_json(spec: BriefingSpec) -> str:
    raw = asdict(spec)
    raw["kind"] = spec.kind.value
    return json.dumps(raw)


def _spec(raw: dict[str, Any]) -> BriefingSpec:
    return BriefingSpec(
        kind=BriefingKind(str(raw["kind"])),
        lookback_seconds=int(raw["lookback_seconds"]),
        minimum_severity=str(raw["minimum_severity"]),
        categories=tuple(raw.get("categories", ())),
        max_items=int(raw["max_items"]),
        include_pending_approvals=bool(raw["include_pending_approvals"]),
        include_failed_actions=bool(raw["include_failed_actions"]),
        scope_ref=(str(raw["scope_ref"]) if raw.get("scope_ref") is not None else None),
    )


def _policy(row: dict[str, Any]) -> ConversationPolicyRecord:
    return ConversationPolicyRecord(
        policy_id=str(row["policy_id"]),
        principal_id=str(row["principal_id"]),
        kind=ConversationPolicyKind(str(row["kind"])),
        enabled=bool(row["enabled"]),
        revision=int(row["revision"]),
        confirmed_at=row["confirmed_at"],
        source_turn_id=str(row["source_turn_id"]),
        briefing_spec=_spec(dict(row["briefing_spec"])) if row["briefing_spec"] else None,
        response_defaults=dict(row["response_defaults"]),
    )


def _with_subscription_revision(
    record: BriefingSubscription, revision: int
) -> BriefingSubscription:
    return BriefingSubscription(
        subscription_id=record.subscription_id,
        principal_id=record.principal_id,
        name=record.name,
        spec=record.spec,
        cron_expression=record.cron_expression,
        timezone=record.timezone,
        delivery_modes=record.delivery_modes,
        enabled=record.enabled,
        next_run_at=record.next_run_at,
        created_at=record.created_at,
        revision=revision,
        channel_binding_ref=record.channel_binding_ref,
        max_lateness_seconds=record.max_lateness_seconds,
        continuation_mode=record.continuation_mode,
        continuation_origin=record.continuation_origin,
        continuation_ttl_seconds=record.continuation_ttl_seconds,
    )


def _subscription(row: dict[str, Any]) -> BriefingSubscription:
    return BriefingSubscription(
        subscription_id=str(row["subscription_id"]),
        principal_id=str(row["principal_id"]),
        name=str(row["name"]),
        spec=_spec(dict(row["spec"])),
        cron_expression=str(row["cron_expression"]),
        timezone=str(row["timezone"]),
        delivery_modes=tuple(BriefingDeliveryMode(str(item)) for item in row["delivery_modes"]),
        enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"],
        created_at=row["created_at"],
        revision=int(row["revision"]),
        channel_binding_ref=(
            str(row["channel_binding_ref"]) if row["channel_binding_ref"] else None
        ),
        max_lateness_seconds=int(row["max_lateness_seconds"]),
        continuation_mode=ContinuationMode(str(row["continuation_mode"])),
        continuation_origin=(
            _origin(row["continuation_origin"]) if row["continuation_origin"] is not None else None
        ),
        continuation_ttl_seconds=int(row["continuation_ttl_seconds"]),
    )


def _run(row: dict[str, Any]) -> BriefingRun:
    return BriefingRun(
        run_id=str(row["run_id"]),
        subscription_id=(str(row["subscription_id"]) if row["subscription_id"] else None),
        principal_id=str(row["principal_id"]),
        conversation_id=(str(row["conversation_id"]) if row["conversation_id"] else None),
        scheduled_for=row["scheduled_for"],
        started_at=row["started_at"],
        status=BriefingRunStatus(str(row["status"])),
        idempotency_key=str(row["idempotency_key"]),
        title=str(row["title"]),
        body_markdown=str(row["body_markdown"]),
        item_count=int(row["item_count"]),
        evidence_refs=tuple(row["evidence_refs"]),
        source_errors=tuple(row["source_errors"]),
        continuation_mode=ContinuationMode(str(row["continuation_mode"])),
        continuation_origin=(
            _origin(row["continuation_origin"]) if row["continuation_origin"] is not None else None
        ),
        result_digest=(str(row["result_digest"]) if row["result_digest"] else None),
    )


def _origin_json(origin: ScheduledResultOrigin) -> str:
    return json.dumps(
        {
            "audience": origin.audience.value,
            "channel_kind": origin.channel_kind,
            "channel_ref": origin.channel_ref,
            "conversation_ref": origin.conversation_ref,
            "thread_ref": origin.thread_ref,
        },
        sort_keys=True,
    )


def _origin(raw: Any) -> ScheduledResultOrigin:
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError("briefing continuation origin MUST be a JSON object")
    return ScheduledResultOrigin(
        channel_kind=str(value["channel_kind"]),
        channel_ref=str(value["channel_ref"]),
        conversation_ref=str(value["conversation_ref"]),
        thread_ref=(str(value["thread_ref"]) if value.get("thread_ref") is not None else None),
        audience=ContinuationAudience(str(value["audience"])),
    )


__all__ = [
    "PostgresBriefingRunStore",
    "PostgresBriefingStoreConfig",
    "PostgresBriefingSubscriptionStore",
    "PostgresConversationPolicyStore",
]
