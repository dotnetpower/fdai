"""Shadow-only growth writes preserving existing measured patterns on replay."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

import psycopg
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    _encode_operational_case,
    _encode_vector,
    _retention_key,
)


class PostgresShadowPatternWriter(PgVectorPatternLibrary):
    """Insert new shadow candidates without resetting or rebinding existing rows.

    Uses the ordinary writer's transaction-local retention lock and deletion
    fences. Completion in the measurement StateStore is a separate transaction;
    repeating this write after that completion fails is safe.
    """

    async def upsert_pattern(self, *, vector: Sequence[float], action: LearnedAction) -> None:
        if action.success_rate != 0.0 or action.reuse_count != 0:
            raise ValueError("growth writer accepts only new shadow statistics")
        literal = _encode_vector(vector)
        async with (
            asyncio.timeout(15),
            await psycopg.AsyncConnection.connect(
                self._config.dsn, connect_timeout=self._config.connect_timeout_s
            ) as connection,
        ):
            async with connection.transaction():
                await self._set_session_knobs(connection)
                await self._retention_lock(connection)
                keys = [_retention_key("signature", action.signature)]
                if action.operational_case is not None:
                    keys.append(
                        _retention_key("case", action.operational_case.case_ref.split(":")[1])
                    )
                blocked = await connection.execute(
                    "SELECT key FROM state_kv WHERE key = ANY(%s) LIMIT 1", (keys,)
                )
                if await blocked.fetchone() is not None:
                    raise PermissionError("pattern source or signature is pending deletion")
                cursor = await connection.execute(
                    """
                    INSERT INTO t1_pattern_library
                        (signature, rule_id, action_type, params, embedding,
                         source_incident_id, historical_success_rate, reuse_count,
                         operational_case)
                    VALUES (%s, %s, %s, %s::jsonb, %s::vector, %s, 0.0, 0, %s::jsonb)
                    ON CONFLICT (signature) DO UPDATE
                        SET signature = t1_pattern_library.signature
                    WHERE t1_pattern_library.rule_id = EXCLUDED.rule_id
                      AND t1_pattern_library.action_type = EXCLUDED.action_type
                      AND t1_pattern_library.params = EXCLUDED.params
                      AND t1_pattern_library.operational_case
                          IS NOT DISTINCT FROM EXCLUDED.operational_case
                    """,
                    (
                        action.signature,
                        action.rule_id,
                        action.action_type,
                        json.dumps(dict(action.params), allow_nan=False),
                        literal,
                        action.incident_id,
                        _encode_operational_case(action.operational_case),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("growth cannot replace a pattern's source or action identity")
