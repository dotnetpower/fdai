"""PostgreSQL CAS persistence for automation blueprint candidates."""

# ruff: noqa: S608 - all interpolated SQL fragments are module constants

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.blueprints import (
    AutomationBlueprintCandidate,
    AutomationBlueprintState,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile

_COLUMNS: Final = (
    "candidate_id, dedup_key, normalized_task_intent, schedule_class, schedule_expression, "
    "event_type, principal_id, resource_scope, delivery_intent, required_tools, "
    "isolation_profile, estimated_cost_microusd, evidence_fingerprints, proposer, confidence, "
    "created_at, expires_at, state, enabled, shadow_only, mutation_tool_ids, reviewed_by, "
    "review_reason, resulting_task_id"
    ", realized_usage_count"
)


@dataclass(frozen=True, slots=True)
class PostgresAutomationBlueprintStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresAutomationBlueprintStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresAutomationBlueprintStoreConfig timeouts MUST be positive")


class PostgresAutomationBlueprintStore:
    def __init__(self, *, config: PostgresAutomationBlueprintStoreConfig) -> None:
        self._config = config

    async def create(self, candidate: AutomationBlueprintCandidate) -> AutomationBlueprintCandidate:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            prior = await self._get_for_update(connection, candidate.candidate_id)
            if prior is not None:
                if (
                    prior.dedup_key == candidate.dedup_key
                    and prior.evidence_fingerprints == candidate.evidence_fingerprints
                ):
                    return prior
                raise ValueError("automation blueprint candidate id collision")
            active = await self._find_active(connection, candidate.dedup_key)
            if active is not None:
                return active
            latest = await self._find_latest(connection, candidate.dedup_key)
            if latest is not None and set(candidate.evidence_fingerprints) <= set(
                latest.evidence_fingerprints
            ):
                return latest
            cursor = await connection.execute(
                f"INSERT INTO automation_blueprint_candidate ({_COLUMNS}) "  # noqa: S608
                "VALUES (" + ", ".join(["%s"] * 25) + f") RETURNING {_COLUMNS}",  # noqa: S608
                _values(candidate),
            )
            row = await cursor.fetchone()
        if row is None:  # pragma: no cover - INSERT RETURNING invariant
            raise RuntimeError("automation blueprint insert returned no row")
        return _row_to_candidate(row)

    async def get(self, candidate_id: str) -> AutomationBlueprintCandidate:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM automation_blueprint_candidate "  # noqa: S608
                "WHERE candidate_id = %s",
                (candidate_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"automation blueprint {candidate_id!r} was not found")
        return _row_to_candidate(row)

    async def list_all(self) -> tuple[AutomationBlueprintCandidate, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM automation_blueprint_candidate "  # noqa: S608
                "ORDER BY created_at, candidate_id"
            )
            rows = await cursor.fetchall()
        return tuple(_row_to_candidate(row) for row in rows)

    async def transition(
        self,
        candidate: AutomationBlueprintCandidate,
        *,
        expected_state: AutomationBlueprintState,
    ) -> AutomationBlueprintCandidate | None:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            transition_sql = (
                "UPDATE automation_blueprint_candidate "
                "SET state = %s, reviewed_by = %s, review_reason = %s, "
                "resulting_task_id = %s, realized_usage_count = %s "
                "WHERE candidate_id = %s AND state = %s "
                f"RETURNING {_COLUMNS}"
            )
            cursor = await connection.execute(
                transition_sql,
                (
                    candidate.state.value,
                    candidate.reviewed_by,
                    candidate.review_reason,
                    candidate.resulting_task_id,
                    candidate.realized_usage_count,
                    candidate.candidate_id,
                    expected_state.value,
                ),
            )
            row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def expire(self, *, now: datetime) -> int:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                UPDATE automation_blueprint_candidate
                   SET state = 'expired', review_reason = 'candidate_expired'
                 WHERE state IN ('draft', 'accepted') AND expires_at <= %s
                """,
                (now,),
            )
            return cursor.rowcount

    async def _get_for_update(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        candidate_id: str,
    ) -> AutomationBlueprintCandidate | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM automation_blueprint_candidate "  # noqa: S608
            "WHERE candidate_id = %s FOR UPDATE",
            (candidate_id,),
        )
        row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def _find_active(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        dedup_key: str,
    ) -> AutomationBlueprintCandidate | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM automation_blueprint_candidate "  # noqa: S608
            "WHERE dedup_key = %s AND state IN ('draft', 'accepted') "
            "ORDER BY created_at DESC, candidate_id DESC LIMIT 1 FOR UPDATE",
            (dedup_key,),
        )
        row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def _find_latest(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        dedup_key: str,
    ) -> AutomationBlueprintCandidate | None:
        cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM automation_blueprint_candidate "  # noqa: S608
            "WHERE dedup_key = %s ORDER BY created_at DESC, candidate_id DESC LIMIT 1",
            (dedup_key,),
        )
        row = await cursor.fetchone()
        return _row_to_candidate(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _values(candidate: AutomationBlueprintCandidate) -> tuple[object, ...]:
    profile = candidate.isolation_profile
    return (
        candidate.candidate_id,
        candidate.dedup_key,
        candidate.normalized_task_intent,
        candidate.schedule_class,
        candidate.schedule_expression,
        candidate.event_type,
        candidate.principal_id,
        candidate.resource_scope,
        candidate.delivery_intent,
        json.dumps(list(candidate.required_tools)),
        json.dumps(
            {
                "profile_id": profile.profile_id,
                "max_session_seconds": profile.max_session_seconds,
                "max_context_chars": profile.max_context_chars,
                "max_tool_calls": profile.max_tool_calls,
                "allowed_tool_ids": sorted(profile.allowed_tool_ids),
                "command_sandbox_profile_id": profile.command_sandbox_profile_id,
            }
        ),
        candidate.estimated_cost_microusd,
        json.dumps(list(candidate.evidence_fingerprints)),
        candidate.proposer,
        candidate.confidence,
        candidate.created_at,
        candidate.expires_at,
        candidate.state.value,
        candidate.enabled,
        candidate.shadow_only,
        json.dumps(list(candidate.mutation_tool_ids)),
        candidate.reviewed_by,
        candidate.review_reason,
        candidate.resulting_task_id,
        candidate.realized_usage_count,
    )


def _row_to_candidate(row: dict[str, Any]) -> AutomationBlueprintCandidate:
    profile = cast(dict[str, Any], _json_value(row["isolation_profile"]))
    return AutomationBlueprintCandidate(
        candidate_id=str(row["candidate_id"]),
        dedup_key=str(row["dedup_key"]),
        normalized_task_intent=str(row["normalized_task_intent"]),
        schedule_class=str(row["schedule_class"]),
        schedule_expression=str(row["schedule_expression"]),
        event_type=str(row["event_type"]),
        principal_id=str(row["principal_id"]),
        resource_scope=str(row["resource_scope"]),
        delivery_intent=str(row["delivery_intent"]),
        required_tools=tuple(str(value) for value in _json_list(row["required_tools"])),
        isolation_profile=ScheduledRunIsolationProfile(
            profile_id=str(profile["profile_id"]),
            max_session_seconds=int(profile["max_session_seconds"]),
            max_context_chars=int(profile["max_context_chars"]),
            max_tool_calls=int(profile["max_tool_calls"]),
            allowed_tool_ids=frozenset(str(value) for value in profile["allowed_tool_ids"]),
            command_sandbox_profile_id=(
                str(profile["command_sandbox_profile_id"])
                if profile["command_sandbox_profile_id"] is not None
                else None
            ),
        ),
        estimated_cost_microusd=int(row["estimated_cost_microusd"]),
        evidence_fingerprints=tuple(
            str(value) for value in _json_list(row["evidence_fingerprints"])
        ),
        proposer=str(row["proposer"]),
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        state=AutomationBlueprintState(str(row["state"])),
        enabled=bool(row["enabled"]),
        shadow_only=bool(row["shadow_only"]),
        mutation_tool_ids=tuple(str(value) for value in _json_list(row["mutation_tool_ids"])),
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
        review_reason=str(row["review_reason"]) if row["review_reason"] is not None else None,
        resulting_task_id=(
            str(row["resulting_task_id"]) if row["resulting_task_id"] is not None else None
        ),
        realized_usage_count=int(row["realized_usage_count"]),
    )


def _json_value(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _json_list(value: object) -> list[object]:
    decoded = _json_value(value)
    if not isinstance(decoded, list):
        raise ValueError("automation blueprint JSON column MUST be an array")
    return decoded


__all__ = [
    "PostgresAutomationBlueprintStore",
    "PostgresAutomationBlueprintStoreConfig",
]
