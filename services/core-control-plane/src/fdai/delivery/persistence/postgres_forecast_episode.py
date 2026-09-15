"""PostgreSQL forecast episode ledger with atomic terminal outbox."""

# ruff: noqa: S608 - interpolated SQL fragments are module-owned column constants.

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeClosure,
    ForecastEpisodeState,
    ForecastEvaluationKind,
    ForecastPublicationOutboxItem,
    forecast_publication_id,
)
from fdai.core.detection.forecast_operational_metrics import (
    reduce_forecast_operational_metrics,
)
from fdai.core.detection.forecast_outcome import ForecastObservation
from fdai.shared.contracts.models import ForecastOutcome, Mode

_EPISODE_COLUMNS = """
episode_id, correlation_id, detector_id, detector_version, scorer_version,
access_scope_digest, target_ref, metric, feature_cutoff, horizon_started_at,
horizon_ended_at, telemetry_grace_seconds, direction, threshold, evaluation_kind,
evidence_refs, predicted_value, interval_lower, interval_upper, abstain_reason,
mode, state, revision
""".replace("\n", " ").strip()


@dataclass(frozen=True, slots=True)
class PostgresForecastEpisodeStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("forecast episode Postgres DSN MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("forecast episode Postgres timeouts MUST be positive")


class PostgresForecastEpisodeStore:
    def __init__(self, *, config: PostgresForecastEpisodeStoreConfig) -> None:
        self._config = config

    async def verify_schema(self) -> None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            await connection.execute("SELECT closure_observation FROM forecast_episode LIMIT 0")
            await connection.execute("SELECT 1 FROM forecast_publication_outbox LIMIT 0")

    async def health_snapshot(self, *, now: datetime) -> Mapping[str, object]:
        _aware("health snapshot time", now)
        async with await self._connect() as connection, connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            await self._timeout(connection)
            episodes = await connection.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE state = 'closed') AS closed, "
                "COUNT(*) FILTER (WHERE state = 'open' AND closure_due_at < %s) AS overdue, "
                "COUNT(*) FILTER (WHERE closure_due_at <= %s) AS due_total, "
                "COUNT(*) FILTER (WHERE state = 'closed' AND closure_due_at <= %s) AS due_closed, "
                "COUNT(*) FILTER (WHERE evaluation_kind = 'abstained') AS abstained, "
                "COUNT(*) FILTER (WHERE state = 'closed' "
                "AND evaluation_kind = 'abstained') AS abstained_closed, "
                "COUNT(*) FILTER (WHERE state = 'closed' "
                "AND closure_observation IS NULL) AS observation_missing, "
                "COUNT(*) FILTER (WHERE closure_observation->>'telemetry_completeness' "
                "= 'complete') AS observation_complete, "
                "COUNT(*) FILTER (WHERE closure_observation->>'telemetry_completeness' "
                "= 'partial') AS observation_partial, "
                "COUNT(*) FILTER (WHERE closure_observation->>'telemetry_completeness' "
                "= 'unavailable') AS observation_unavailable "
                "FROM forecast_episode",
                (now, now, now),
            )
            episode_row = await episodes.fetchone()
            labels = await connection.execute(
                "SELECT payload->>'label' AS label, payload->>'miss_origin' AS miss_origin, "
                "COUNT(*) AS count FROM forecast_publication_outbox "
                "WHERE topic = 'object.forecast-outcome' "
                "GROUP BY payload->>'label', payload->>'miss_origin'",
            )
            lead_times = await connection.execute(
                "SELECT COUNT(*) FILTER (WHERE "
                "(outcome.payload->>'actual_breach_at')::timestamptz > episode.created_at"
                ") AS sample_count, "
                "COUNT(*) FILTER (WHERE "
                "(outcome.payload->>'actual_breach_at')::timestamptz <= episode.created_at"
                ") AS non_positive_count, "
                "AVG(EXTRACT(EPOCH FROM ("
                "(outcome.payload->>'actual_breach_at')::timestamptz - "
                "episode.created_at"
                "))) FILTER (WHERE "
                "(outcome.payload->>'actual_breach_at')::timestamptz > episode.created_at"
                ") AS mean_seconds, "
                "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM ("
                "(outcome.payload->>'actual_breach_at')::timestamptz - "
                "episode.created_at"
                "))) FILTER (WHERE "
                "(outcome.payload->>'actual_breach_at')::timestamptz > episode.created_at"
                ") AS median_seconds "
                "FROM forecast_publication_outbox AS outcome "
                "JOIN forecast_episode AS episode USING (episode_id) "
                "WHERE outcome.topic = 'object.forecast-outcome' "
                "AND outcome.payload->>'label' IN ('true_positive', 'magnitude_error')",
            )
            publication = await connection.execute(
                "SELECT COUNT(*) FILTER (WHERE published_at IS NULL "
                "AND dead_lettered_at IS NULL AND available_at <= %s) AS pending_due, "
                "COUNT(*) FILTER (WHERE published_at IS NULL "
                "AND dead_lettered_at IS NULL AND available_at > %s) AS pending_future, "
                "COUNT(*) FILTER (WHERE dead_lettered_at IS NOT NULL) AS dead_lettered, "
                "MIN(created_at) FILTER (WHERE published_at IS NULL "
                "AND dead_lettered_at IS NULL AND available_at <= %s) AS oldest_pending_at "
                "FROM forecast_publication_outbox",
                (now, now, now),
            )
            publication_row = await publication.fetchone()
            deletion = await connection.execute(
                "SELECT COUNT(*) FILTER (WHERE deleted_at IS NULL AND deletion_due_at < %s) "
                "AS overdue_deletions, "
                "COUNT(*) FILTER (WHERE deletion_started_at IS NOT NULL AND deleted_at IS NULL) "
                "AS pending_deletions FROM case_history",
                (now,),
            )
            deletion_row = await deletion.fetchone()
            outcome_rows = await labels.fetchall()
            lead_time_row = await lead_times.fetchone()
        total = int(episode_row["total"]) if episode_row else 0
        closed = int(episode_row["closed"]) if episode_row else 0
        due_total = int(episode_row["due_total"]) if episode_row else 0
        due_closed = int(episode_row["due_closed"]) if episode_row else 0
        outcome_counts = _aggregate_outcome_counts(outcome_rows)
        lead_time_sample_count = (
            int(lead_time_row["sample_count"]) if lead_time_row is not None else 0
        )
        operational_metrics = reduce_forecast_operational_metrics(
            episode_count=closed,
            abstained_count=int(episode_row["abstained_closed"]) if episode_row else 0,
            outcome_counts=outcome_counts,
            mean_lead_time_seconds=(
                float(lead_time_row["mean_seconds"])
                if lead_time_row is not None and lead_time_row["mean_seconds"] is not None
                else None
            ),
            median_lead_time_seconds=(
                float(lead_time_row["median_seconds"])
                if lead_time_row is not None and lead_time_row["median_seconds"] is not None
                else None
            ),
            lead_time_sample_count=lead_time_sample_count,
            non_positive_lead_time_count=(
                int(lead_time_row["non_positive_count"]) if lead_time_row is not None else 0
            ),
        )
        return {
            "episodes": {
                "total": total,
                "closed": closed,
                "open": total - closed,
                "overdue": int(episode_row["overdue"]) if episode_row else 0,
                "abstained": int(episode_row["abstained"]) if episode_row else 0,
                "closure_completeness": due_closed / due_total if due_total else None,
            },
            "outcomes": [
                {
                    "label": row["label"],
                    "miss_origin": row["miss_origin"],
                    "count": int(row["count"]),
                }
                for row in outcome_rows
            ],
            "operational_metrics": operational_metrics.to_dict(),
            "observations": {
                completeness: int(episode_row[f"observation_{completeness}"]) if episode_row else 0
                for completeness in ("complete", "partial", "unavailable", "missing")
            },
            "publication": {
                "pending": int(publication_row["pending_due"]) if publication_row else 0,
                "future": int(publication_row["pending_future"]) if publication_row else 0,
                "dead_lettered": (int(publication_row["dead_lettered"]) if publication_row else 0),
                "oldest_pending_at": (
                    publication_row["oldest_pending_at"].isoformat()
                    if publication_row and publication_row["oldest_pending_at"]
                    else None
                ),
            },
            "retention": {
                "overdue": int(deletion_row["overdue_deletions"]) if deletion_row else 0,
                "pending": int(deletion_row["pending_deletions"]) if deletion_row else 0,
            },
        }

    async def record(
        self,
        episode: ForecastEpisode,
        *,
        forecast_payload: Mapping[str, object] | None = None,
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO forecast_episode ("
                f"{_EPISODE_COLUMNS}, target_digest, closure_due_at"
                ") VALUES ("
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (episode_id) DO NOTHING RETURNING episode_id",
                (*_episode_values(episode), episode.target_digest, episode.closure_due_at),
            )
            if await cursor.fetchone() is not None:
                if forecast_payload is not None:
                    await self._insert_publication(
                        connection,
                        episode_id=episode.episode_id,
                        topic="object.forecast",
                        payload=forecast_payload,
                        available_at=episode.feature_cutoff,
                    )
                return True
            existing = await self._select_episode(connection, episode.episode_id)
            if existing != episode:
                raise ValueError("forecast episode identity conflict")
            return False

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastEpisode, ...]:
        _aware("claim time", now)
        _aware("lease time", lease_until)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH due AS ("
                "SELECT episode_id FROM forecast_episode "
                "WHERE state = 'open' AND closure_due_at <= %s "
                "AND (closure_leased_until IS NULL OR closure_leased_until <= %s) "
                "ORDER BY closure_due_at, episode_id FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE forecast_episode AS episode SET "
                "closure_leased_until = %s, closure_attempts = closure_attempts + 1, "
                "revision = revision + 1, updated_at = %s FROM due "
                "WHERE episode.episode_id = due.episode_id "
                f"RETURNING {_qualified_columns('episode')}",
                (now, now, limit, lease_until, now),
            )
            return tuple(_episode_from_row(row) for row in await cursor.fetchall())

    async def close(self, closure: ForecastEpisodeClosure) -> bool:
        _aware("closed_at", closure.closed_at)
        observation = _observation_mapping(closure.observation)
        serialized_observation = (
            json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if observation is not None
            else None
        )
        outcome = (
            ForecastOutcome.model_validate(closure.outcome_payload)
            if closure.outcome_payload is not None
            else None
        )
        if closure.observation is not None:
            observed_breach = closure.observation.actual_breach_at
            if observed_breach is not None and observed_breach > closure.closed_at:
                raise ValueError("forecast closure observation MUST NOT follow closure time")
            if outcome is not None and any(
                getattr(closure.observation, field) != getattr(outcome, field)
                for field in (
                    "observed_value",
                    "actual_breach_at",
                    "telemetry_completeness",
                    "intervention_refs",
                    "scoring_exclusions",
                )
            ):
                raise ValueError("forecast closure observation contradicts its terminal outcome")
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE forecast_episode SET state = 'closed', revision = revision + 1, "
                "closure_leased_until = NULL, closed_at = %s, closure_reason = %s, "
                "outcome_id = %s, updated_at = %s, closure_observation = %s::jsonb "
                "WHERE episode_id = %s AND state = 'open' AND revision = %s "
                "RETURNING episode_id",
                (
                    closure.closed_at,
                    closure.reason.value,
                    outcome.outcome_id if outcome else None,
                    closure.closed_at,
                    serialized_observation,
                    closure.episode_id,
                    closure.expected_revision,
                ),
            )
            if await cursor.fetchone() is None:
                existing = await connection.execute(
                    "SELECT episode.state, episode.outcome_id, episode.closure_reason, "
                    "episode.closure_observation, publication.payload AS outcome_payload "
                    "FROM forecast_episode AS episode "
                    "LEFT JOIN forecast_publication_outbox AS publication "
                    "ON publication.episode_id = episode.episode_id "
                    "AND publication.topic = 'object.forecast-outcome' "
                    "WHERE episode.episode_id = %s",
                    (closure.episode_id,),
                )
                row = await existing.fetchone()
                stored_outcome_id = row["outcome_id"] if row is not None else None
                if (
                    row is not None
                    and row["state"] == "closed"
                    and row["closure_reason"] == closure.reason.value
                    and row["closure_observation"] == observation
                    and row["outcome_payload"]
                    == (outcome.model_dump(mode="json") if outcome else None)
                    and (
                        (outcome is None and stored_outcome_id is None)
                        or (
                            outcome is not None
                            and stored_outcome_id is not None
                            and UUID(str(stored_outcome_id)) == outcome.outcome_id
                        )
                    )
                ):
                    return False
                raise ValueError("forecast episode closure conflict")
            if outcome is not None:
                await self._insert_publication(
                    connection,
                    episode_id=closure.episode_id,
                    topic="object.forecast-outcome",
                    payload=outcome.model_dump(mode="json"),
                    available_at=closure.closed_at,
                )
            return True

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastPublicationOutboxItem, ...]:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "WITH pending AS ("
                "SELECT publication_id FROM forecast_publication_outbox "
                "WHERE published_at IS NULL AND dead_lettered_at IS NULL "
                "AND available_at <= %s "
                "AND (leased_until IS NULL OR leased_until <= %s) "
                "ORDER BY available_at, publication_id FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE forecast_publication_outbox AS item SET "
                "leased_until = %s, claim_count = claim_count + 1 FROM pending "
                "WHERE item.publication_id = pending.publication_id "
                "RETURNING item.publication_id, item.episode_id, item.topic, "
                "item.payload, item.publish_fail_count AS attempts",
                (now, now, limit, lease_until),
            )
            return tuple(_outbox_from_row(row) for row in await cursor.fetchall())

    async def complete_publication(
        self,
        publication_id: UUID,
        *,
        published_at: datetime,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "UPDATE forecast_publication_outbox SET published_at = %s, leased_until = NULL, "
                "last_error = NULL WHERE publication_id = %s AND published_at IS NULL",
                (published_at, publication_id),
            )

    async def release_publication(
        self,
        publication_id: UUID,
        *,
        available_at: datetime,
        error: str,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "UPDATE forecast_publication_outbox SET available_at = %s, leased_until = NULL, "
                "publish_fail_count = publish_fail_count + 1, last_error = %s "
                "WHERE publication_id = %s AND published_at IS NULL",
                (available_at, error[:512], publication_id),
            )

    async def dead_letter_publication(
        self,
        publication_id: UUID,
        *,
        failed_at: datetime,
        error: str,
    ) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await connection.execute(
                "UPDATE forecast_publication_outbox SET dead_lettered_at = %s, "
                "leased_until = NULL, last_error = %s WHERE publication_id = %s "
                "AND published_at IS NULL",
                (failed_at, error[:512], publication_id),
            )

    async def _insert_publication(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        episode_id: UUID,
        topic: str,
        payload: Mapping[str, object],
        available_at: datetime,
    ) -> None:
        publication_id = forecast_publication_id(episode_id=episode_id, topic=topic)
        await connection.execute(
            "INSERT INTO forecast_publication_outbox "
            "(publication_id, episode_id, topic, payload, available_at) "
            "VALUES (%s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (publication_id) DO NOTHING",
            (
                publication_id,
                episode_id,
                topic,
                json.dumps(dict(payload), default=str),
                available_at,
            ),
        )

    async def _select_episode(
        self,
        connection: psycopg.AsyncConnection[Any],
        episode_id: UUID,
    ) -> ForecastEpisode | None:
        cursor = await connection.execute(
            f"SELECT {_EPISODE_COLUMNS} FROM forecast_episode WHERE episode_id = %s",
            (episode_id,),
        )
        row = await cursor.fetchone()
        return _episode_from_row(row) if row is not None else None

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            _psycopg_dsn(self._config.dsn),
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _aggregate_outcome_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Combine label counts while preserving separate miss-origin rows."""

    counts: dict[str, int] = {}
    for row in rows:
        label = row.get("label")
        if label is None:
            continue
        key = str(label)
        counts[key] = counts.get(key, 0) + int(row["count"])
    return counts


def _episode_values(episode: ForecastEpisode) -> tuple[object, ...]:
    return (
        episode.episode_id,
        episode.correlation_id,
        episode.detector_id,
        episode.detector_version,
        episode.scorer_version,
        episode.access_scope_digest,
        episode.target_ref,
        episode.metric,
        episode.feature_cutoff,
        episode.horizon_started_at,
        episode.horizon_ended_at,
        episode.telemetry_grace_seconds,
        episode.direction,
        episode.threshold,
        episode.evaluation_kind.value,
        list(episode.evidence_refs),
        episode.predicted_value,
        episode.interval_lower,
        episode.interval_upper,
        episode.abstain_reason,
        episode.mode.value,
        episode.state.value,
        episode.revision,
    )


def _qualified_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in _EPISODE_COLUMNS.split(","))


def _episode_from_row(row: Mapping[str, Any]) -> ForecastEpisode:
    return ForecastEpisode(
        episode_id=UUID(str(row["episode_id"])),
        correlation_id=str(row["correlation_id"]),
        detector_id=str(row["detector_id"]),
        detector_version=str(row["detector_version"]),
        scorer_version=str(row["scorer_version"]),
        access_scope_digest=str(row["access_scope_digest"]),
        target_ref=str(row["target_ref"]),
        metric=str(row["metric"]),
        feature_cutoff=row["feature_cutoff"],
        horizon_started_at=row["horizon_started_at"],
        horizon_ended_at=row["horizon_ended_at"],
        telemetry_grace_seconds=int(row["telemetry_grace_seconds"]),
        direction=str(row["direction"]),
        threshold=float(row["threshold"]),
        evaluation_kind=ForecastEvaluationKind(str(row["evaluation_kind"])),
        evidence_refs=tuple(str(value) for value in row["evidence_refs"]),
        predicted_value=(
            float(row["predicted_value"]) if row["predicted_value"] is not None else None
        ),
        interval_lower=(
            float(row["interval_lower"]) if row["interval_lower"] is not None else None
        ),
        interval_upper=(
            float(row["interval_upper"]) if row["interval_upper"] is not None else None
        ),
        abstain_reason=(str(row["abstain_reason"]) if row["abstain_reason"] is not None else None),
        mode=Mode(str(row["mode"])),
        state=ForecastEpisodeState(str(row["state"])),
        revision=int(row["revision"]),
    )


def _outbox_from_row(row: Mapping[str, Any]) -> ForecastPublicationOutboxItem:
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        raise RuntimeError("forecast outcome outbox payload MUST be an object")
    return ForecastPublicationOutboxItem(
        publication_id=UUID(str(row["publication_id"])),
        episode_id=UUID(str(row["episode_id"])),
        topic=str(row["topic"]),
        payload=dict(payload),
        attempts=int(row["attempts"]),
    )


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"forecast episode {name} MUST be timezone-aware")


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _observation_mapping(observation: ForecastObservation | None) -> dict[str, object] | None:
    if observation is None:
        return None
    if observation.observed_value is not None and (
        isinstance(observation.observed_value, bool)
        or not isinstance(observation.observed_value, (int, float))
        or not math.isfinite(observation.observed_value)
    ):
        raise ValueError("forecast closure observation value MUST be finite numeric evidence")
    if not observation.evidence_refs or len(observation.evidence_refs) > 64:
        raise ValueError("forecast closure observation requires 1..64 evidence references")
    if len(observation.intervention_refs) > 64:
        raise ValueError("forecast closure observation exceeds intervention reference limit")
    references = (*observation.evidence_refs, *observation.intervention_refs)
    if any(not isinstance(value, str) or not 1 <= len(value) <= 512 for value in references):
        raise ValueError("forecast closure observation references MUST be bounded non-empty text")
    if observation.actual_breach_at is not None:
        _aware("actual breach time", observation.actual_breach_at)
    payload: dict[str, object] = {
        "schema_version": "1.1.0" if observation.scoring_exclusions else "1.0.0",
        "observed_value": observation.observed_value,
        "actual_breach_at": (
            observation.actual_breach_at.isoformat()
            if observation.actual_breach_at is not None
            else None
        ),
        "telemetry_completeness": observation.telemetry_completeness.value,
        "evidence_refs": list(observation.evidence_refs),
        "intervention_refs": list(observation.intervention_refs),
    }
    if observation.scoring_exclusions:
        payload["scoring_exclusions"] = list(observation.scoring_exclusions)
    return payload


__all__ = ["PostgresForecastEpisodeStore", "PostgresForecastEpisodeStoreConfig"]
