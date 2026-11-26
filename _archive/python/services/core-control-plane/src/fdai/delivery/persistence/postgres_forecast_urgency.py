"""Exact Core-role read of forecast timing evidence from the existing episode/outbox pair."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.core.hil_resume.forecast_urgency import ForecastUrgencySource
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_forecast_episode import _episode_from_row


@dataclass(frozen=True, slots=True)
class PostgresForecastUrgencyReader:
    """Read one unambiguous retained source; never select caller JSON or mutate an episode."""

    config: PostgresStateStoreConfig

    async def read(self, episode_id: UUID) -> ForecastUrgencySource | None:
        try:
            async with await psycopg.AsyncConnection.connect(
                self.config.dsn,
                row_factory=dict_row,
                connect_timeout=self.config.connect_timeout_s,
            ) as connection:
                await connection.set_read_only(True)
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(min(self.config.statement_timeout_ms, 5000)),),
                )
                role = await (await connection.execute("SELECT current_user AS role")).fetchone()
                if role is None or role["role"] != "fdai_core":
                    raise PermissionError("forecast timing reader requires the Core SQL role")
                rows = await (
                    await connection.execute(
                        "SELECT episode.*, publication.payload AS forecast_payload "
                        "FROM forecast_episode AS episode "
                        "JOIN forecast_publication_outbox AS publication "
                        "ON publication.episode_id = episode.episode_id "
                        "WHERE episode.episode_id = %s "
                        "AND publication.topic = 'object.forecast' LIMIT 2",
                        (episode_id,),
                    )
                ).fetchall()
        except psycopg.Error as exc:
            raise RuntimeError("forecast timing source is unavailable") from exc
        if len(rows) != 1:
            return None
        return ForecastUrgencySource(_episode_from_row(rows[0]), rows[0]["forecast_payload"])


__all__ = ["PostgresForecastUrgencyReader"]
