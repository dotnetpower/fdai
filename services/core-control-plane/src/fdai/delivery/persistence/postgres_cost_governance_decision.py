"""PostgreSQL adapter for retained Cost Governance W4-W5 lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.shared.providers.cost_governance_decision import (
    CostDecisionOutcome,
    CostEpisodePersistenceRecord,
    CostEpisodeSettlement,
    CostEvidenceRecord,
    CostRecoveryAttempt,
)


class PostgresCostGovernanceDecisionStore:
    """Append decision lineage and CAS legal-hold/purge metadata."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn or statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("cost decision store configuration MUST be valid")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def append_cost_episode(
        self,
        record: CostEpisodePersistenceRecord,
        *,
        expected_revision: int,
    ) -> bool:
        """Append one immutable episode revision and initialize retention."""

        if record.revision != expected_revision + 1:
            raise ValueError("episode record revision MUST follow expected revision")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                current = await conn.execute(
                    """
                    SELECT revision
                      FROM cost_governance_episode
                     WHERE episode_id = %s
                     ORDER BY revision DESC
                     LIMIT 1
                     FOR UPDATE
                    """,
                    (record.episode_id,),
                )
                row = await current.fetchone()
                actual_revision = cast(int, row["revision"]) if row is not None else 0
                if actual_revision != expected_revision:
                    return False
                inserted = await conn.execute(
                    """
                    INSERT INTO cost_governance_episode (
                        episode_id, revision, package_id, idempotency_key,
                        outcome, reason, decision_frame_digest, terminal,
                        observation_mode, recorded_at, retention_until
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        record.episode_id,
                        record.revision,
                        "fdai-cost-governance",
                        record.idempotency_key,
                        record.outcome.value,
                        record.reason,
                        record.decision_frame_digest,
                        record.terminal,
                        record.outcome is CostDecisionOutcome.HOLD,
                        record.recorded_at,
                        record.retention_until,
                    ),
                )
                if inserted.rowcount != 1:
                    return False
                if expected_revision == 0:
                    retention = await conn.execute(
                        """
                        INSERT INTO cost_governance_retention (
                            episode_id, revision, retention_until, purge_after,
                            legal_hold, legal_hold_ref, updated_at
                        )
                        VALUES (%s, 1, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            record.episode_id,
                            record.retention_until,
                            record.retention_until,
                            record.legal_hold,
                            record.legal_hold_ref,
                            record.recorded_at,
                        ),
                    )
                    if retention.rowcount != 1:
                        raise RuntimeError("episode retention initialization conflicted")
                    await conn.execute(
                        """
                        INSERT INTO cost_governance_retention_event (
                            episode_id, revision, event_kind, legal_hold_ref,
                            recorded_at, idempotency_key
                        )
                        VALUES (%s, 1, 'created', %s, %s, %s)
                        """,
                        (
                            record.episode_id,
                            record.legal_hold_ref,
                            record.recorded_at,
                            f"retention-created:{record.idempotency_key}",
                        ),
                    )
                return True

    async def append_cost_recovery_attempt(
        self,
        episode_id: str,
        attempt_index: int,
        attempt: CostRecoveryAttempt,
    ) -> bool:
        """Append one ordered recovery attempt; duplicates remain no-ops."""

        if attempt_index != list(type(attempt.step)).index(attempt.step):
            raise ValueError("recovery attempt index MUST match the fixed step order")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                latest = await conn.execute(
                    """
                    SELECT revision
                      FROM cost_governance_episode
                     WHERE episode_id = %s
                     ORDER BY revision DESC
                     LIMIT 1
                     FOR UPDATE
                    """,
                    (episode_id,),
                )
                row = await latest.fetchone()
                if row is None:
                    return False
                revision = cast(int, row["revision"])
                current = await conn.execute(
                    """
                    SELECT MAX(attempt_index) AS attempt_index
                      FROM cost_governance_recovery
                     WHERE episode_id = %s AND episode_revision = %s
                    """,
                    (episode_id, revision),
                )
                current_row = await current.fetchone()
                last_index = (
                    cast(int, current_row["attempt_index"])
                    if current_row is not None and current_row["attempt_index"] is not None
                    else -1
                )
                if attempt_index != last_index + 1:
                    return False
                inserted = await conn.execute(
                    """
                    INSERT INTO cost_governance_recovery (
                        episode_id, episode_revision, attempt_index, step, status,
                        hypothesis_id, input_frame_digest, output_frame_digest,
                        autonomy_ceiling, attempted_at, independent_source_authority,
                        evidence_refs
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        episode_id,
                        revision,
                        attempt_index,
                        attempt.step.value,
                        attempt.status.value,
                        attempt.hypothesis_id,
                        attempt.input_frame_digest,
                        (attempt.output_frame.digest if attempt.output_frame is not None else None),
                        _ceiling(attempt.autonomy_ceiling.name),
                        attempt.attempted_at,
                        attempt.independent_source_authority,
                        Jsonb(list(attempt.evidence_refs)),
                    ),
                )
                return inserted.rowcount == 1

    async def append_cost_settlement(self, settlement: CostEpisodeSettlement) -> bool:
        """Append one settlement and all effect rows atomically."""

        payload = _settlement_payload(settlement)
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                revision = await self._latest_revision(conn, settlement.episode_id)
                if revision is None:
                    return False
                inserted = await conn.execute(
                    """
                    INSERT INTO cost_governance_settlement (
                        episode_id, episode_revision, settlement_digest, terminal,
                        realized_savings, rollback_request_id, recovery_observed, settled_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        settlement.episode_id,
                        revision,
                        digest,
                        settlement.terminal,
                        settlement.realized_savings,
                        (
                            settlement.rollback_request.request_id
                            if settlement.rollback_request is not None
                            else None
                        ),
                        settlement.recovery_observed,
                        settlement.settled_at,
                    ),
                )
                if inserted.rowcount != 1:
                    return False
                sql_cursor = conn.cursor()
                await sql_cursor.executemany(
                    """
                    INSERT INTO cost_governance_effect_settlement (
                        episode_id, episode_revision, effect_id, effect_kind,
                        status, reason, terminal, observation_digest,
                        completeness_digest, settled_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    tuple(
                        (
                            settlement.episode_id,
                            revision,
                            effect.effect_id,
                            effect.kind.value,
                            effect.status.value,
                            effect.reason,
                            effect.terminal,
                            effect.observation_digest,
                            effect.completeness_digest,
                            effect.settled_at,
                        )
                        for effect in settlement.effects
                    ),
                )
                return True

    async def append_cost_evidence(self, record: CostEvidenceRecord) -> bool:
        """Append one attributed evidence item with replay-safe deduplication."""

        async with await self._connect() as conn:
            await self._timeout(conn)
            revision = await self._latest_revision(conn, record.episode_id)
            if revision != record.episode_revision:
                return False
            inserted = await conn.execute(
                """
                INSERT INTO cost_governance_evidence (
                    episode_id, episode_revision, evidence_sequence, evidence_ref,
                    evidence_digest, source_authority, recorded_at, idempotency_key
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    record.episode_id,
                    record.episode_revision,
                    record.evidence_sequence,
                    record.evidence_ref,
                    record.evidence_digest,
                    record.source_authority,
                    record.recorded_at,
                    record.idempotency_key,
                ),
            )
            return inserted.rowcount == 1

    async def read_cost_episode(
        self,
        episode_id: str,
    ) -> CostEpisodePersistenceRecord | None:
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT e.episode_id, e.revision, e.idempotency_key, e.outcome,
                       e.reason, e.decision_frame_digest, e.terminal, e.recorded_at,
                       e.retention_until, r.legal_hold, r.legal_hold_ref, r.purged_at
                  FROM cost_governance_episode e
                  JOIN cost_governance_retention r USING (episode_id)
                 WHERE e.episode_id = %s
                 ORDER BY e.revision DESC
                 LIMIT 1
                """,
                (episode_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return CostEpisodePersistenceRecord(
            episode_id=str(row["episode_id"]),
            revision=cast(int, row["revision"]),
            idempotency_key=str(row["idempotency_key"]),
            outcome=CostDecisionOutcome(str(row["outcome"])),
            reason=str(row["reason"]),
            decision_frame_digest=str(row["decision_frame_digest"]),
            terminal=cast(bool, row["terminal"]),
            recorded_at=cast(datetime, row["recorded_at"]),
            retention_until=cast(datetime, row["retention_until"]),
            legal_hold=cast(bool, row["legal_hold"]),
            legal_hold_ref=(
                str(row["legal_hold_ref"]) if row["legal_hold_ref"] is not None else None
            ),
            purged_at=cast(datetime | None, row["purged_at"]),
        )

    async def compare_and_set_cost_retention(
        self,
        episode_id: str,
        *,
        expected_revision: int,
        legal_hold: bool,
        legal_hold_ref: str | None,
        recorded_at: datetime,
    ) -> bool:
        """CAS legal hold and append its immutable transition event."""

        if legal_hold != (legal_hold_ref is not None):
            raise ValueError("legal hold and reference MUST be supplied together")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                updated = await conn.execute(
                    """
                    UPDATE cost_governance_retention
                       SET revision = revision + 1,
                           legal_hold = %s,
                           legal_hold_ref = %s,
                           updated_at = %s
                     WHERE episode_id = %s
                       AND revision = %s
                       AND purged_at IS NULL
                    """,
                    (
                        legal_hold,
                        legal_hold_ref,
                        recorded_at,
                        episode_id,
                        expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    return False
                await conn.execute(
                    """
                    INSERT INTO cost_governance_retention_event (
                        episode_id, revision, event_kind, legal_hold_ref,
                        recorded_at, idempotency_key
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        episode_id,
                        expected_revision + 1,
                        "hold-applied" if legal_hold else "hold-released",
                        legal_hold_ref,
                        recorded_at,
                        f"retention:{episode_id}:{expected_revision + 1}",
                    ),
                )
                return True

    async def purge_due_cost_episodes(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]:
        """Append bounded purge tombstones without deleting audit lineage."""

        if not 1 <= limit <= 500:
            raise ValueError("cost purge limit MUST be in [1, 500]")
        purged: list[str] = []
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                due = await conn.execute(
                    """
                    SELECT episode_id, revision
                      FROM cost_governance_retention
                     WHERE purge_after <= %s
                       AND NOT legal_hold
                       AND purged_at IS NULL
                     ORDER BY purge_after, episode_id
                     LIMIT %s
                     FOR UPDATE SKIP LOCKED
                    """,
                    (now, limit),
                )
                for row in await due.fetchall():
                    episode_id = str(row["episode_id"])
                    revision = cast(int, row["revision"]) + 1
                    await conn.execute(
                        """
                        UPDATE cost_governance_retention
                           SET revision = %s, purged_at = %s, updated_at = %s
                         WHERE episode_id = %s
                        """,
                        (revision, now, now, episode_id),
                    )
                    await conn.execute(
                        """
                        INSERT INTO cost_governance_retention_event (
                            episode_id, revision, event_kind, recorded_at, idempotency_key
                        )
                        VALUES (%s, %s, 'purged', %s, %s)
                        """,
                        (
                            episode_id,
                            revision,
                            now,
                            f"retention-purged:{episode_id}:{revision}",
                        ),
                    )
                    purged.append(episode_id)
        return tuple(purged)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        )

    async def _timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )

    async def _latest_revision(
        self,
        conn: psycopg.AsyncConnection[dict[str, Any]],
        episode_id: str,
    ) -> int | None:
        cursor = await conn.execute(
            """
            SELECT revision
              FROM cost_governance_episode
             WHERE episode_id = %s
             ORDER BY revision DESC
             LIMIT 1
            """,
            (episode_id,),
        )
        row = await cursor.fetchone()
        return cast(int, row["revision"]) if row is not None else None


def _ceiling(name: str) -> str:
    return name.lower().replace("_", "-")


def _settlement_payload(settlement: CostEpisodeSettlement) -> bytes:
    value = {
        "decision_frame_digest": settlement.decision_frame_digest,
        "effects": [
            {
                "completeness_digest": item.completeness_digest,
                "effect_id": item.effect_id,
                "kind": item.kind.value,
                "observation_digest": item.observation_digest,
                "observed_value": (
                    str(item.observed_value) if item.observed_value is not None else None
                ),
                "reason": item.reason,
                "status": item.status.value,
                "terminal": item.terminal,
            }
            for item in settlement.effects
        ],
        "episode_id": settlement.episode_id,
        "realized_savings": str(settlement.realized_savings),
        "recovery_observed": settlement.recovery_observed,
        "rollback_request_id": (
            settlement.rollback_request.request_id
            if settlement.rollback_request is not None
            else None
        ),
        "settled_at": settlement.settled_at.isoformat(),
        "terminal": settlement.terminal,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


__all__ = ["PostgresCostGovernanceDecisionStore"]
