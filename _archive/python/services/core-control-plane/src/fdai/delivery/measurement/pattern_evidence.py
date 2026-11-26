"""Publish pattern evidence and measured statistics from verified enforce-mode outcomes.

The producer reads only the audit log (verified outcome joined with its growth context), writes
holdout envelopes to the measurement state store, and later updates the measured success rate of
patterns that shadow growth already admitted. It creates no pattern, proposes no action, and holds
no execution or promotion authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai.core.measurement.pattern_evidence import (
    HOLDOUT_STATE_PREFIX,
    HoldoutPolicy,
    MeasuredStatistics,
    ScoredOutcome,
    StatisticsPolicy,
    holdout_envelopes,
    measured_statistics,
    pattern_signature,
)
from fdai.core.tiers.t1_lightweight.contextual_reuse import OperationalCaseContext
from fdai.delivery.measurement.outcome_contract import accepted_outcome_timestamp
from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    _retention_key,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore
from psycopg.rows import dict_row

_LOGGER = logging.getLogger(__name__)
_OUTCOME_KIND = "measurement.action_outcome.v1"
_CONTEXT_KIND = "measurement.growth_context.v1"
_MAX_OUTCOMES = 20_000


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def scored_outcome(
    outcome: Mapping[str, Any], context: Mapping[str, Any], *, recorded_at: Any
) -> ScoredOutcome | None:
    """Reduce one outcome and its growth context, or ``None`` when it cannot name a pattern.

    An unverified outcome with no reported rollback is a technical failure and MUST be counted;
    a verified one needs an explicit rollback state, so an unknown success is never promoted.
    """
    action_type = outcome.get("action_type_id")
    rule_id = context.get("rule_id")
    params = context.get("params")
    verified = outcome.get("verification_passed")
    rolled_back = outcome.get("rollback_succeeded")
    scorable = outcome.get("scorable")
    if (
        outcome.get("execution_mode") != "enforce"
        or not isinstance(action_type, str)
        or not isinstance(rule_id, str)
        or not isinstance(params, Mapping)
        or not isinstance(verified, bool)
        or not isinstance(scorable, bool)
        or not (isinstance(rolled_back, bool) or (rolled_back is None and not verified))
    ):
        return None
    observed_at = accepted_outcome_timestamp(outcome.get("observed_at"), recorded_at=recorded_at)
    if observed_at is None:
        return None
    case_raw = context.get("operational_case")
    case = None
    if isinstance(case_raw, Mapping):
        try:
            case = OperationalCaseContext.from_mapping(case_raw)
        except ValueError:
            return None
    signature = pattern_signature(
        action_type_id=action_type, params=params, rule_id=rule_id, operational_case=case
    )
    if signature is None:
        return None
    return ScoredOutcome(
        signature=signature,
        observed_at=observed_at,
        scorable=scorable,
        verified=verified,
        rolled_back=rolled_back is True,
    )


class PostgresPatternEvidenceSource:
    """Read bounded verified outcomes joined with their latest growth context."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn:
            raise ValueError("dsn MUST be non-empty")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def outcomes(self) -> list[ScoredOutcome]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row, connect_timeout=self._connect_timeout_s
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )
            cursor = await connection.execute(
                """
                SELECT outcome.entry AS outcome, outcome.created_at AS recorded_at,
                       context.entry AS context
                FROM (
                    SELECT DISTINCT ON (entry->>'action_id') entry, created_at
                    FROM audit_log
                    WHERE action_kind = %s AND entry->>'action_id' IS NOT NULL
                    ORDER BY entry->>'action_id', seq DESC
                ) AS outcome
                JOIN LATERAL (
                    SELECT entry FROM audit_log
                    WHERE action_kind = %s AND entry->>'action_id' = outcome.entry->>'action_id'
                    ORDER BY seq DESC LIMIT 1
                ) AS context ON TRUE
                ORDER BY outcome.created_at DESC
                LIMIT %s
                """,
                (_OUTCOME_KIND, _CONTEXT_KIND, _MAX_OUTCOMES),
            )
            rows = await cursor.fetchall()
        scored = (
            scored_outcome(
                _mapping(row["outcome"]),
                _mapping(row["context"]),
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )
        return [item for item in scored if item is not None]


@dataclass(frozen=True, slots=True)
class PatternEvidenceReport:
    outcomes: int
    envelopes_written: int
    complete_envelopes: int
    patterns_updated: int


class PatternEvidenceProducer:
    """Two idempotent steps around shadow growth: holdout evidence first, statistics after."""

    def __init__(
        self,
        *,
        source: PostgresPatternEvidenceSource,
        state_store: StateStore,
        statistics_writer: PostgresPatternStatisticsWriter,
        holdout_policy: HoldoutPolicy | None = None,
        statistics_policy: StatisticsPolicy | None = None,
    ) -> None:
        self._source = source
        self._state_store = state_store
        self._statistics_writer = statistics_writer
        self._holdout_policy = holdout_policy or HoldoutPolicy()
        self._statistics_policy = statistics_policy or StatisticsPolicy()

    async def publish_holdout_evidence(self) -> PatternEvidenceReport:
        outcomes = await self._source.outcomes()
        envelopes = holdout_envelopes(outcomes, policy=self._holdout_policy)
        for signature, envelope in envelopes.items():
            await self._state_store.write_state(f"{HOLDOUT_STATE_PREFIX}{signature}", envelope)
        return PatternEvidenceReport(
            outcomes=len(outcomes),
            envelopes_written=len(envelopes),
            complete_envelopes=sum(1 for value in envelopes.values() if value["complete"]),
            patterns_updated=0,
        )

    async def apply_measured_statistics(self) -> PatternEvidenceReport:
        outcomes = await self._source.outcomes()
        measured = measured_statistics(outcomes, policy=self._statistics_policy)
        observed = frozenset(item.signature for item in outcomes if item.scorable)
        updated = await self._statistics_writer.apply(
            measured, observed=observed, state_store=self._state_store
        )
        return PatternEvidenceReport(
            outcomes=len(outcomes),
            envelopes_written=0,
            complete_envelopes=0,
            patterns_updated=updated,
        )


class PostgresPatternStatisticsWriter(PgVectorPatternLibrary):
    """Update only the measured statistics of patterns that already exist.

    Absent patterns are skipped, so this writer can never create a pattern. A signature pending
    deletion is skipped under the same retention lock the ordinary writer uses. A pattern whose
    verified outcomes this producer observed but that fall below the minimum is reset to unproven,
    which is the demotion path; patterns it never observed keep their statistics untouched.
    """

    async def apply(
        self,
        measured: Mapping[str, MeasuredStatistics],
        *,
        observed: frozenset[str],
        state_store: StateStore,
    ) -> int:
        async with (
            asyncio.timeout(30),
            await psycopg.AsyncConnection.connect(
                self._config.dsn, connect_timeout=self._config.connect_timeout_s
            ) as connection,
        ):
            async with connection.transaction():
                await self._set_session_knobs(connection)
                await self._retention_lock(connection)
                cursor = await connection.execute(
                    "SELECT signature, historical_success_rate, reuse_count FROM t1_pattern_library"
                )
                existing = {row[0]: (float(row[1]), int(row[2])) for row in await cursor.fetchall()}
                blocked_cursor = await connection.execute(
                    "SELECT key FROM state_kv WHERE key = ANY(%s)",
                    ([_retention_key("signature", signature) for signature in existing],),
                )
                blocked = {row[0] for row in await blocked_cursor.fetchall()}
                changes: list[tuple[str, float, int, float, int]] = []
                for signature, (old_rate, old_count) in existing.items():
                    if (
                        signature not in observed
                        or _retention_key("signature", signature) in blocked
                    ):
                        continue
                    target = measured.get(signature)
                    rate, count = (
                        (float(target.success_rate), int(target.reuse_count))
                        if target is not None
                        else (0.0, 0)
                    )
                    if (rate, count) != (old_rate, old_count):
                        await connection.execute(
                            "UPDATE t1_pattern_library "
                            "SET historical_success_rate = %s, reuse_count = %s "
                            "WHERE signature = %s",
                            (rate, count, signature),
                        )
                        changes.append((signature, old_rate, old_count, rate, count))
        for signature, old_rate, old_count, rate, count in changes:
            try:
                await state_store.append_audit_entry(
                    {
                        "actor": "fdai.delivery.measurement.pattern_promotion",
                        "action_kind": "measurement.pattern_statistics",
                        "mode": Mode.SHADOW.value,
                        "pattern_id": signature,
                        "previous_success_rate": old_rate,
                        "previous_outcome_count": old_count,
                        "measured_success_rate": rate,
                        "measured_outcome_count": count,
                        "direction": "demoted" if rate < old_rate else "measured",
                        "promotion_authority": False,
                        "execution_authority": False,
                        "recorded_at": datetime.now(tz=UTC).isoformat(),
                    }
                )
            except Exception:  # noqa: BLE001 - the durable update already committed
                _LOGGER.warning("pattern_statistics_audit_failed", exc_info=True)
        return len(changes)


__all__ = [
    "PatternEvidenceProducer",
    "PatternEvidenceReport",
    "PostgresPatternEvidenceSource",
    "PostgresPatternStatisticsWriter",
    "scored_outcome",
]
