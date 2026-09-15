"""Real Core-role forecast source joins on a disposable loopback PostgreSQL database."""

from __future__ import annotations

import runpy
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fdai.core.detection.forecast_episode import forecast_episode_id
from fdai.core.detection.forecast_evaluation import _forecast_payload
from fdai.core.hil_resume.forecast_urgency import ForecastUrgencySource, verify_forecast_urgency
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
)
from fdai.delivery.persistence.postgres_forecast_urgency import PostgresForecastUrgencyReader

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
pytestmark = pytest.mark.integration
_forecast = runpy.run_path(
    str(
        _support["ROOT"]
        / ("services/core-control-plane/tests/core/detection/test_forecast_episode.py")
    )
)
T0 = _forecast["T0"]


def source():
    episode = _forecast["_episode"]()
    episode = replace(episode, correlation_id=f"forecast:{episode.episode_id}")
    return ForecastUrgencySource(
        episode,
        {
            **_forecast_payload(episode),
            "approval_timing": {
                "schema_version": "1.0.0",
                "confidence_level": "0.95",
                "predicted_breach_at": (T0 + timedelta(seconds=200)).isoformat(),
            },
        },
    )


@pytest.mark.parametrize("offset_hours", [0, 9])
async def test_real_forecast_store_and_current_reader_share_exact_source_but_not_operator_role(
    database,
    offset_hours,
):
    with psycopg.connect(database) as admin:
        _support["_run_migration"](
            admin,
            _support["ROOT"] / "alembic/versions/20260723_0053_forecast_episode.py",
            "upgrade",
        )
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE ON forecast_episode, "
            "forecast_publication_outbox TO fdai_core"
        )
    dsn = _role(database, "fdai_core")
    store = PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(dsn=dsn))
    original = source()
    if offset_hours:
        zone = timezone(timedelta(hours=offset_hours))
        episode = replace(
            original.episode,
            feature_cutoff=original.episode.feature_cutoff.astimezone(zone),
            horizon_started_at=original.episode.horizon_started_at.astimezone(zone),
            horizon_ended_at=original.episode.horizon_ended_at.astimezone(zone),
        )
        episode_id = forecast_episode_id(
            access_scope_digest=episode.access_scope_digest,
            detector_id=episode.detector_id,
            detector_version=episode.detector_version,
            target_ref=episode.target_ref,
            metric=episode.metric,
            feature_cutoff=episode.feature_cutoff,
            horizon_ended_at=episode.horizon_ended_at,
        )
        episode = replace(episode, episode_id=episode_id, correlation_id=f"forecast:{episode_id}")
        original = replace(
            original,
            episode=episode,
            payload={
                **_forecast_payload(episode),
                "approval_timing": original.payload["approval_timing"],
            },
        )
    assert await store.record(original.episode, forecast_payload=original.payload)
    reader = PostgresForecastUrgencyReader(PostgresStateStoreConfig(dsn=dsn))
    retained = await reader.read(original.episode.episode_id)
    assert retained == original
    assert (
        verify_forecast_urgency(
            retained,
            episode_id=original.episode.episode_id,
            target_ref=original.episode.target_ref,
            at=T0,
        )
        is not None
    )
    assert await reader.read(uuid4()) is None
    for role in ("fdai_operator", "postgres"):
        with pytest.raises(PermissionError):
            await PostgresForecastUrgencyReader(
                PostgresStateStoreConfig(dsn=_role(database, role))
            ).read(original.episode.episode_id)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE forecast_episode SET state='closed', closed_at=%s, "
            "closure_reason='scored' WHERE episode_id=%s",
            (T0, original.episode.episode_id),
        )
    closed = await reader.read(original.episode.episode_id)
    assert (
        verify_forecast_urgency(
            closed,
            episode_id=original.episode.episode_id,
            target_ref=original.episode.target_ref,
            at=T0,
        )
        is None
    )
