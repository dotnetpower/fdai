"""Scalar learning model/receipt/audit transactions in a private loopback schema."""

from __future__ import annotations

import asyncio
import runpy
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from fdai.core.assurance_twin import EffectModelStatus, StateStoreEffectModelRegistry
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.core.measurement.runners import DynamicLearningRunner
from fdai.core.mscp_profile.response_outcome import response_outcome_audit_entry
from fdai.delivery.measurement.postgres_growth import PostgresResponseOutcomeSource
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _NOW, _CurrentFixtureSource, _model
from tests.persistence.test_postgres_forecast_episode import (
    forecast_database as forecast_database,
)


@pytest.fixture
async def feedback_database(forecast_database: str) -> AsyncIterator[str]:
    statements: list[str] = []
    migration = Path(__file__).resolve().parents[4] / "alembic/versions/20260705_0001_base.py"
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(str(migration))["upgrade"]()
    async with await psycopg.AsyncConnection.connect(forecast_database) as connection:
        for statement in statements:
            if "audit_log" in statement:
                await connection.execute(statement)
        await connection.execute(
            "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
    yield forecast_database


def _registry(dsn: str) -> StateStoreEffectModelRegistry:
    return StateStoreEffectModelRegistry(
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn)),
        clock=lambda: _NOW + timedelta(minutes=6),
        feedback_source=_CurrentFixtureSource(),
    )


@pytest.mark.integration
async def test_audit_failure_rolls_back_model_receipt_and_replays_source(
    feedback_database: str,
) -> None:
    dsn = feedback_database
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    registry = _registry(dsn)
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    for index in (1, 2):
        snapshot = _feedback(index).prediction_snapshot
        assert snapshot is not None
        await retain_prediction(store, snapshot, recorded_at=_NOW)
        await store.append_audit_entry(response_outcome_audit_entry(_feedback(index)))
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute("""
            CREATE FUNCTION reject_second_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.action_kind = 'dynamic.effect_model.challenger.updated'
                   AND NEW.entry->>'response_outcome_id' =
                       '00000000-0000-0000-0000-000000000066' THEN
                    RAISE EXCEPTION 'injected second feedback audit failure';
                END IF;
                RETURN NEW;
            END
            $$
        """)
        await connection.execute(
            "CREATE TRIGGER reject_second_feedback BEFORE INSERT ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION reject_second_feedback()"
        )

    def runner() -> DynamicLearningRunner:
        return DynamicLearningRunner(
            outcome_source=PostgresResponseOutcomeSource(dsn=dsn, state_store=store),
            registry=_registry(dsn),
            audit_store=store,
        )

    with pytest.raises(psycopg.errors.RaiseException, match="injected second feedback"):
        await runner().run_once()
    watermark = await store.read_state("measurement:dynamic_learning:watermark")
    assert watermark is not None
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute(
            "SELECT seq FROM audit_log WHERE action_kind = 'measurement.action_outcome.v1' "
            "AND entry->>'outcome_id' = %s",
            (str(_feedback(1).outcome_id),),
        )
        first_source = await cursor.fetchone()
    assert first_source is not None and watermark["seq"] == first_source[0]
    persisted = await _registry(dsn).get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )
    assert persisted is not None and persisted.sample_count == 1
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute("DROP TRIGGER reject_second_feedback ON audit_log")
        await connection.execute("DROP FUNCTION reject_second_feedback()")
    replayed = await runner().run_once()
    assert replayed.accepted_count == 1
    assert replayed.total_outcomes == 1
    persisted = await _registry(dsn).get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )
    assert persisted is not None and persisted.sample_count == 2
    assert await store.verify_chain()


@pytest.mark.integration
@pytest.mark.parametrize("duplicate", [True, False])
async def test_two_postgres_consumers_commit_one_receipt_per_event(
    feedback_database: str, duplicate: bool
) -> None:
    dsn = feedback_database
    await _registry(dsn).register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    for index in (1, 2):
        snapshot = _feedback(index).prediction_snapshot
        assert snapshot is not None
        await retain_prediction(store, snapshot, recorded_at=_NOW)
    results = await asyncio.gather(
        _registry(dsn).update_from_outcome(_feedback(1)),
        _registry(dsn).update_from_outcome(_feedback(1 if duplicate else 2)),
    )
    expected = 1 if duplicate else 2
    assert sum(result.accepted for result in results) == expected
    registry = _registry(dsn)
    model = await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
    )
    assert model is not None and model.sample_count == expected
    assert (await registry.update_from_outcome(_feedback(1))).reason == "outcome_already_applied"


@pytest.mark.integration
async def test_first_pending_growth_record_is_created_with_its_audit_in_postgres(
    feedback_database: str,
) -> None:
    from fdai.core.measurement.pattern_growth import OutcomeRecord
    from fdai.core.measurement.pending_growth import PendingPatternGrowth

    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=feedback_database))
    pending = PendingPatternGrowth(store)
    record = OutcomeRecord("action-1", "ops.scale-out", _NOW, True, True, False)
    audit = {
        "actor": "fixture",
        "action_kind": "measurement.pattern_growth.pending_test",
        "mode": "shadow",
        "recorded_at": _NOW.isoformat(),
    }
    await pending.defer(record, audit)
    restarted = PendingPatternGrowth(
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=feedback_database))
    )
    assert await restarted.records() == (record,)
    await restarted.finish(record, audit)
    assert await pending.records() == ()
    assert await store.verify_chain()


@pytest.mark.integration
@pytest.mark.parametrize("status", [EffectModelStatus.ACTIVE, EffectModelStatus.CHALLENGER])
async def test_model_checksum_survives_actual_jsonb_numeric_normalization(
    feedback_database: str, status: EffectModelStatus
) -> None:
    registry = _registry(feedback_database)
    model = replace(_model(status), bias_correction=1e20)
    assert await registry.register(model, registered_by="Mimir")
    loaded = await registry.get(
        status=status, action_type_id=model.action_type_id, metric=model.metric
    )
    assert loaded == model
