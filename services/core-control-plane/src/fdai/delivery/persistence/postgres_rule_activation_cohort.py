"""PostgreSQL linearization for dormant Rule activation cohort commits."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres import PostgresStateStoreConfig

_INSERT_CANDIDATE = """
WITH latest AS (
    SELECT 1 FROM state_kv
    WHERE key = %s AND value = %s::jsonb
    FOR UPDATE
)
INSERT INTO state_kv (key, value)
SELECT %s, %s::jsonb FROM latest
WHERE clock_timestamp() < %s
ON CONFLICT (key) DO NOTHING
"""
_UPDATE_CANDIDATE = """
WITH latest AS (
    SELECT 1 FROM state_kv
    WHERE key = %s AND value = %s::jsonb
    FOR UPDATE
)
UPDATE state_kv
SET value = %s::jsonb, updated_at = CURRENT_TIMESTAMP
WHERE key = %s
  AND COALESCE((value ->> 'revision')::integer, 0) = %s
  AND clock_timestamp() < %s
  AND EXISTS (SELECT 1 FROM latest)
"""
_UPDATE_AND_INSERT_APPLIED = """
WITH guarded AS (
    UPDATE state_kv
    SET value = %s::jsonb, updated_at = CURRENT_TIMESTAMP
    WHERE key = %s
      AND value = %s::jsonb
      AND %s <= clock_timestamp()
      AND clock_timestamp() < %s
    RETURNING 1
)
INSERT INTO state_kv (key, value)
SELECT %s, %s::jsonb FROM guarded
RETURNING 1
"""


@dataclass(frozen=True, slots=True)
class PostgresRuleActivationCohortCommitStore:
    config: PostgresStateStoreConfig

    async def advance_prepare(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
    ) -> bool:
        async with await self._connect() as connection:
            if expected_revision == 0:
                cursor = await connection.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING",
                    (key, json.dumps(dict(value))),
                )
            else:
                cursor = await connection.execute(
                    "UPDATE state_kv SET value=%s::jsonb, updated_at=clock_timestamp() "
                    "WHERE key=%s AND COALESCE((value ->> 'revision')::integer, 0)=%s",
                    (json.dumps(dict(value)), key, expected_revision),
                )
            return cursor.rowcount == 1

    async def activate_candidate(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
        latest_prepare_key: str,
        expected_latest_prepare: Mapping[str, Any],
        lease_expires_at: datetime,
    ) -> bool:
        async with await self._connect() as connection:
            if expected_revision == 0:
                cursor = await connection.execute(
                    _INSERT_CANDIDATE,
                    (
                        latest_prepare_key,
                        json.dumps(dict(expected_latest_prepare)),
                        key,
                        json.dumps(dict(value)),
                        lease_expires_at,
                    ),
                )
            else:
                cursor = await connection.execute(
                    _UPDATE_CANDIDATE,
                    (
                        latest_prepare_key,
                        json.dumps(dict(expected_latest_prepare)),
                        json.dumps(dict(value)),
                        key,
                        expected_revision,
                        lease_expires_at,
                    ),
                )
            return cursor.rowcount == 1

    async def insert_applied(
        self,
        *,
        candidate_key: str,
        expected_candidate: Mapping[str, Any],
        replacement_candidate: Mapping[str, Any],
        insert_key: str,
        insert_value: Mapping[str, Any],
        applied_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        try:
            async with await self._connect() as connection:
                cursor = await connection.execute(
                    _UPDATE_AND_INSERT_APPLIED,
                    (
                        json.dumps(dict(replacement_candidate)),
                        candidate_key,
                        json.dumps(dict(expected_candidate)),
                        applied_at,
                        lease_expires_at,
                        insert_key,
                        json.dumps(dict(insert_value)),
                    ),
                )
                return await cursor.fetchone() is not None
        except psycopg.errors.UniqueViolation:
            return False

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        connection = await psycopg.AsyncConnection.connect(
            self.config.dsn,
            autocommit=False,
            connect_timeout=self.config.connect_timeout_s,
        )
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(self.config.statement_timeout_ms),),
        )
        return connection


__all__ = ["PostgresRuleActivationCohortCommitStore"]
