from __future__ import annotations

import os
import runpy
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fdai.core.detection.forecast_episode import ForecastClosureReason, ForecastEpisodeClosure
from fdai.core.detection.forecast_outcome import (
    ForecastExpectation,
    ForecastObservation,
    close_forecast,
)
from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
    _aggregate_outcome_counts,
    _observation_mapping,
)
from fdai.shared.contracts.models import TelemetryCompleteness

from tests.core.detection.test_forecast_episode import T0, _episode


@pytest.fixture
async def forecast_database() -> AsyncIterator[str]:
    """Apply the forecast DDL in a private loopback schema and verify cleanup."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("forecast migration regression requires a loopback database")
    root = Path(__file__).resolve().parents[4]
    paths = (
        "alembic/versions/20260723_0053_forecast_episode.py",
        "alembic/versions/20260723_0057_publication_failure_count.py",
        "service-migrations/branches/core-control-plane/versions/"
        "20260914_core_forecast_closure_observation.py",
    )
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        for path in paths:
            runpy.run_path(str(root / path))["upgrade"]()
    schema = f"forecast_observation_test_{uuid4().hex}"
    created = False
    try:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            for statement in statements:
                await connection.execute(statement)
            await connection.execute(
                "CREATE TABLE case_history (deleted_at TIMESTAMPTZ, "
                "deletion_due_at TIMESTAMPTZ, deletion_started_at TIMESTAMPTZ)"
            )
        created = True
        yield make_conninfo(dsn, options=f"-c search_path={schema}")
    finally:
        if created:
            async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
                await connection.execute("SET statement_timeout = '15s'")
                await connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
                cursor = await connection.execute(
                    "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s",
                    (schema,),
                )
                assert await cursor.fetchone() == (0,)


def test_config_rejects_empty_dsn_and_invalid_timeouts() -> None:
    with pytest.raises(ValueError, match="DSN"):
        PostgresForecastEpisodeStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresForecastEpisodeStoreConfig(dsn="postgresql://example", statement_timeout_ms=0)


def test_operational_metrics_sum_false_negatives_across_miss_origins() -> None:
    assert _aggregate_outcome_counts(
        (
            {"label": "false_negative", "miss_origin": "model", "count": 2},
            {"label": "false_negative", "miss_origin": "pipeline", "count": 3},
            {"label": "true_positive", "miss_origin": None, "count": 4},
        )
    ) == {"false_negative": 5, "true_positive": 4}


def test_closure_observation_mapping_retains_incomplete_breach_and_intervention() -> None:
    observed_at = T0 + timedelta(minutes=30)
    observation = ForecastObservation(
        observed_value=96.0,
        actual_breach_at=observed_at,
        telemetry_completeness=TelemetryCompleteness.PARTIAL,
        evidence_refs=("metric-window:example",),
        intervention_refs=("action-receipt:example",),
    )
    assert _observation_mapping(observation) == {
        "schema_version": "1.1.0",
        "observed_value": 96.0,
        "actual_breach_at": observed_at.isoformat(),
        "telemetry_completeness": "partial",
        "evidence_refs": ["metric-window:example"],
        "intervention_refs": ["action-receipt:example"],
        "scoring_exclusions": ["intervention_affected"],
    }
    assert _observation_mapping(None) is None


def test_closure_observation_mapping_retains_scoring_exclusions_separately() -> None:
    observation = ForecastObservation(
        observed_value=96.0,
        actual_breach_at=T0 + timedelta(minutes=30),
        telemetry_completeness=TelemetryCompleteness.COMPLETE,
        evidence_refs=("metric-window:example",),
        scoring_exclusions=("intervention_history_unavailable",),
    )
    payload = _observation_mapping(observation)
    assert payload is not None
    assert payload["schema_version"] == "1.1.0"
    assert payload["telemetry_completeness"] == "complete"
    assert payload["scoring_exclusions"] == ["intervention_history_unavailable"]


@pytest.mark.parametrize("references", [(), ("",), ("x" * 513,), ("ref",) * 65])
def test_closure_observation_mapping_rejects_unbounded_evidence(
    references: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="observation"):
        _observation_mapping(
            ForecastObservation(
                observed_value=None,
                actual_breach_at=None,
                telemetry_completeness=TelemetryCompleteness.UNAVAILABLE,
                evidence_refs=references,
            )
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_closure_observation_mapping_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite numeric"):
        _observation_mapping(
            ForecastObservation(
                observed_value=value,
                actual_breach_at=None,
                telemetry_completeness=TelemetryCompleteness.COMPLETE,
                evidence_refs=("metric-window:example",),
            )
        )


async def test_future_closure_observation_is_rejected_before_database_io() -> None:
    episode = _episode()
    store = PostgresForecastEpisodeStore(
        config=PostgresForecastEpisodeStoreConfig(dsn="postgresql://example")
    )
    with pytest.raises(ValueError, match="MUST NOT follow closure"):
        await store.close(
            ForecastEpisodeClosure(
                episode_id=episode.episode_id,
                expected_revision=1,
                closed_at=episode.closure_due_at,
                reason=ForecastClosureReason.ABSTAINED_NO_BREACH,
                outcome_payload=None,
                observation=ForecastObservation(
                    observed_value=96.0,
                    actual_breach_at=episode.closure_due_at + timedelta(seconds=1),
                    telemetry_completeness=TelemetryCompleteness.PARTIAL,
                    evidence_refs=("metric-window:example",),
                ),
            )
        )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_schema_is_available_after_migration(forecast_database: str) -> None:
    store = PostgresForecastEpisodeStore(
        config=PostgresForecastEpisodeStoreConfig(dsn=forecast_database)
    )
    await store.verify_schema()


async def test_case_projections_create_restart_and_purge_in_real_postgres(
    forecast_database: str,
) -> None:
    import psycopg
    from fdai.core.case_history import CaseHistoryMaterializer, CaseHistoryRetentionService
    from fdai.core.case_history.derived import (
        CaseHistoryDerivedRetention,
        CaseHistoryProjectionStore,
    )
    from fdai.core.case_history.testing import (
        InMemoryCaseHistoryArtifactStore,
        InMemoryCaseHistoryMetadataStore,
    )
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

    from tests.core.case_history.test_service import SCOPE, _seal

    root = Path(__file__).resolve().parents[4]
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(str(root / "alembic/versions/20260705_0001_base.py"))["upgrade"]()
    async with await psycopg.AsyncConnection.connect(forecast_database) as connection:
        for statement in statements:
            if "audit_log" in statement:
                await connection.execute(statement)
        await connection.execute(
            "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
    config = PostgresStateStoreConfig(dsn=forecast_database)
    store = PostgresStateStore(config=config)
    metadata, artifacts = InMemoryCaseHistoryMetadataStore(), InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    projections = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    assert await projections.write_state_if_absent("pattern-one", value)
    assert await projections.write_state_if_absent("pattern-two", value)
    restarted = CaseHistoryProjectionStore(
        store=PostgresStateStore(config=config),
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    assert await restarted.read_state("pattern-one") == value
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=CaseHistoryDerivedRetention(store=store, materializer=materializer),
    )
    assert await retention.delete_due(now=source.deletion_due_at) == (source.case_id,)
    assert await restarted.read_state("pattern-one") is None
    assert await restarted.read_state("pattern-two") is None
    assert await store.verify_chain()
    async with await psycopg.AsyncConnection.connect(forecast_database) as connection:
        cursor = await connection.execute(
            "SELECT value->'entries' FROM state_kv WHERE key = %s",
            (f"case-history-derived:v1:{SCOPE}",),
        )
        assert await cursor.fetchone() == ({},)

    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore

    from tests.core.operational_context.test_test_context import NOW, _claim, _TransitionAdmission

    contexts = GovernedTestContextStore(
        store=store, admission=_TransitionAdmission(), clock=lambda: NOW
    )
    draft = replace(_claim(), state="proposed", reviewed_by="")
    await contexts.record_transition(draft, expected_revision=0, now=NOW)
    reviewed = replace(draft, state="reviewed", revision=2, reviewed_by="reviewer-two")
    await contexts.record_transition(reviewed, expected_revision=1, now=NOW)
    restarted_contexts = GovernedTestContextStore(
        store=PostgresStateStore(config=config),
        admission=_TransitionAdmission(),
        clock=lambda: NOW,
    )
    query = {
        "target_ref": draft.target_ref,
        "access_scope_digest": draft.access_scope_digest,
        "signal_code": draft.signal_code,
        "at": NOW,
    }
    assert await restarted_contexts.read(**query) == reviewed
    revoked = replace(reviewed, state="revoked", revision=3)
    await restarted_contexts.record_transition(revoked, expected_revision=2, now=NOW)
    assert await contexts.read(**query) == revoked
    assert await store.verify_chain()

    from tests.persistence.test_state_store_forecast_context import exercise_history_amendment

    await exercise_history_amendment(store, legacy=True)
    await _exercise_collector_postgres(forecast_database, store)


async def _exercise_collector_postgres(dsn, state):
    import hashlib
    import json

    import psycopg
    from fdai.core.ontology_platform.state_transitions import (
        OperationalStateTransition,
        StateTransitionAuthority,
        StateTransitionBatch,
        StateTransitionCoverage,
        StateTransitionLane,
    )
    from fdai.delivery.persistence.state_store_forecast_context import (
        StateStoreForecastContextProvider,
    )
    from fdai.runtime.forecast_learning import build_forecast_history_collector
    from fdai.shared.providers.forecast_context import ForecastContextRequest

    from tests.core.operational_context.test_test_context import NOW, _TransitionAdmission

    statements = []
    root = Path(__file__).resolve().parents[4]
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(
            str(
                root
                / "service-migrations/branches/core-control-plane/versions"
                / "20260902_core_operational_state_transitions.py"
            )
        )["upgrade"]()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        for statement in statements:
            await connection.execute(statement)
    bindings, coverage, transitions = [], [], []
    for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows"):
        stateful = kind in {"resource_lifecycle", "excluded_windows"}
        bindings.append(
            {
                "kind": kind,
                "access_scope_digest": "a" * 64,
                "target_ref": "collected-resource",
                "state_type": kind,
                "to_states": ["active", "inactive"],
                "active_states": ["active"] if stateful else [],
                "source_identity": "source-example",
                "source_revision": "revision-example",
                "freshness_seconds": 300,
            }
        )
        coverage.append(
            StateTransitionCoverage.create(
                subject_ref="collected-resource",
                state_type=kind,
                coverage_start_at=NOW - timedelta(hours=25),
                coverage_end_at=NOW,
                recorded_at=NOW,
                source_identity="source-example",
                source_revision="revision-example",
                watermark="checkpoint-one",
                evidence_ref="coverage:" + kind,
                complete=True,
            )
        )
        transitions.append(
            OperationalStateTransition.create(
                idempotency_key=kind,
                subject_ref="collected-resource",
                subject_type="Resource",
                state_type=kind,
                from_state="inactive",
                to_state="active",
                lane=StateTransitionLane.OBSERVED,
                authority=StateTransitionAuthority.PROVIDER,
                effective_at=NOW - timedelta(hours=2) if stateful else NOW - timedelta(minutes=30),
                evidence_cutoff=NOW,
                recorded_at=NOW,
                source_identity="source-example",
                source_revision="revision-example",
                producer_id="observer-example",
                producer_version="1.0.0",
                freshness_ceiling_seconds=300,
                completeness_basis_points=10000,
                evidence_refs=("event:" + kind,),
            )
        )
    collector = build_forecast_history_collector(dsn=dsn, bindings_json=json.dumps(bindings))
    assert collector is not None
    assert await collector._store.append(
        StateTransitionBatch.create(
            transitions=tuple(transitions), coverage=tuple(coverage), recorded_at=NOW
        )
    )
    provider = StateStoreForecastContextProvider(
        state, admission=_TransitionAdmission(), collector=collector, clock=lambda: NOW
    )
    request = ForecastContextRequest(
        access_scope_digest="a" * 64,
        target_digest=hashlib.sha256(b"collected-resource").hexdigest(),
        horizon_started_at=NOW - timedelta(hours=1),
        horizon_ended_at=NOW,
        as_of=NOW,
    )
    result = await provider.read(request)
    assert result.complete and result.resource_deleted and result.excluded_window
    assert len(result.intervention_refs) == 2
    assert await StateStoreForecastContextProvider(state).read(request) == result
    assert await state.verify_chain()

    from fdai.shared.providers.forecast_context import ForecastContextUnavailableError

    unmapped = OperationalStateTransition.create(
        idempotency_key="unmapped-action",
        subject_ref="collected-resource",
        subject_type="Resource",
        state_type="actions",
        from_state="active",
        to_state="unreviewed",
        lane=StateTransitionLane.OBSERVED,
        authority=StateTransitionAuthority.PROVIDER,
        effective_at=NOW - timedelta(minutes=15),
        evidence_cutoff=NOW,
        recorded_at=NOW,
        source_identity="source-example",
        source_revision="revision-example",
        producer_id="observer-example",
        producer_version="1.0.0",
        freshness_ceiling_seconds=300,
        completeness_basis_points=10000,
        evidence_refs=("event:unmapped-action",),
    )
    assert await collector._store.append(
        StateTransitionBatch.create(
            transitions=(unmapped,), coverage=tuple(coverage), recorded_at=NOW
        )
    )
    with pytest.raises(ForecastContextUnavailableError, match="source record mismatch"):
        await collector.collect(request)
    filtered = await collector._store.read(
        subject_refs=("collected-resource",),
        state_types=("actions",),
        to_states=("active",),
        start_at=request.horizon_started_at,
        end_at=NOW,
        known_at=NOW,
        limit=64,
    )
    assert len(filtered.transitions) == 1 and filtered.transitions[0].to_state == "active"


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_publication_claims_do_not_increment_failure_count(forecast_database: str) -> None:
    dsn = forecast_database
    store = PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(dsn=dsn))
    episode = _episode(
        episode_id=uuid4(),
        correlation_id=f"live-{os.getpid()}",
    )
    payload = {
        "correlation_id": episode.correlation_id,
        "idempotency_key": f"forecast:{episode.episode_id}",
    }
    try:
        await store.record(episode, forecast_payload=payload)
        first = await store.claim_publications(
            now=T0,
            limit=1,
            lease_until=T0 + timedelta(seconds=1),
        )
        second = await store.claim_publications(
            now=T0 + timedelta(seconds=2),
            limit=1,
            lease_until=T0 + timedelta(seconds=3),
        )
        assert first[0].attempts == second[0].attempts == 0
        await store.release_publication(
            second[0].publication_id,
            available_at=T0 + timedelta(seconds=4),
            error="transient",
        )
        third = await store.claim_publications(
            now=T0 + timedelta(seconds=5),
            limit=1,
            lease_until=T0 + timedelta(seconds=6),
        )
        assert third[0].attempts == 1
        await store.dead_letter_publication(
            third[0].publication_id,
            failed_at=T0 + timedelta(seconds=5),
            error="permanent",
        )
        assert (
            await store.claim_publications(
                now=T0 + timedelta(seconds=7),
                limit=1,
                lease_until=T0 + timedelta(seconds=8),
            )
            == ()
        )
    finally:
        import psycopg

        plain = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        async with await psycopg.AsyncConnection.connect(plain) as connection:
            await connection.execute(
                "DELETE FROM forecast_publication_outbox WHERE episode_id = %s",
                (episode.episode_id,),
            )
            await connection.execute(
                "DELETE FROM forecast_episode WHERE episode_id = %s",
                (episode.episode_id,),
            )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_health_snapshot_executes_operational_accuracy_query(forecast_database: str) -> None:
    dsn = forecast_database
    store = PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(dsn=dsn))
    issued_at = datetime.now(tz=UTC)
    episode = _episode(
        episode_id=uuid4(),
        correlation_id=f"metrics-{os.getpid()}",
        feature_cutoff=issued_at,
        horizon_started_at=issued_at,
        horizon_ended_at=issued_at + timedelta(hours=1),
    )
    outcome = close_forecast(
        ForecastExpectation(
            prediction_id=episode.episode_id,
            correlation_id=episode.correlation_id,
            detector_id=episode.detector_id,
            detector_version=episode.detector_version,
            access_scope_digest=episode.access_scope_digest,
            target_ref=episode.target_ref,
            metric=episode.metric,
            feature_cutoff=episode.feature_cutoff,
            horizon_started_at=episode.horizon_started_at,
            horizon_ended_at=episode.horizon_ended_at,
            direction="rising",
            threshold=episode.threshold,
            predicted_value=episode.predicted_value or 0.0,
            interval_lower=episode.interval_lower or 0.0,
            interval_upper=episode.interval_upper or 0.0,
            evidence_refs=episode.evidence_refs,
        ),
        ForecastObservation(
            observed_value=95.0,
            actual_breach_at=issued_at + timedelta(minutes=30),
            telemetry_completeness=TelemetryCompleteness.COMPLETE,
            evidence_refs=("metric-window:outcome",),
        ),
        closed_at=issued_at + timedelta(hours=1, minutes=5),
    )
    try:
        await store.record(episode)
        assert await store.close(
            ForecastEpisodeClosure(
                episode_id=episode.episode_id,
                expected_revision=episode.revision,
                closed_at=outcome.closed_at,
                reason=ForecastClosureReason.SCORED,
                outcome_payload=outcome.model_dump(mode="json"),
            )
        )

        snapshot = await store.health_snapshot(now=outcome.closed_at)
        metrics = snapshot["operational_metrics"]

        assert isinstance(metrics, dict)
        assert metrics["episode_count"] >= 1
        assert metrics["episode_count"] == snapshot["episodes"]["closed"]
        assert metrics["lead_time_sample_count"] >= 1
        assert metrics["non_positive_lead_time_count"] >= 0
        assert 1_799.0 <= metrics["mean_lead_time_seconds"] <= 1_800.0
        assert 1_799.0 <= metrics["median_lead_time_seconds"] <= 1_800.0
        assert metrics["execution_authority"] is False
    finally:
        import psycopg

        plain = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        async with await psycopg.AsyncConnection.connect(plain) as connection:
            await connection.execute(
                "DELETE FROM forecast_publication_outbox WHERE episode_id = %s",
                (episode.episode_id,),
            )
            await connection.execute(
                "DELETE FROM forecast_episode WHERE episode_id = %s",
                (episode.episode_id,),
            )


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
@pytest.mark.parametrize("completeness", list(TelemetryCompleteness))
async def test_closure_observation_survives_restart_and_rejects_conflicting_retry(
    monkeypatch: pytest.MonkeyPatch,
    completeness: TelemetryCompleteness,
    forecast_database: str,
) -> None:
    import psycopg
    from fdai.core.detection.forecast_episode import ForecastEvaluationKind
    from psycopg.rows import dict_row

    root = Path(__file__).resolve().parents[4]
    migration = runpy.run_path(
        str(
            root
            / "service-migrations/branches/core-control-plane/versions"
            / "20260914_core_forecast_closure_observation.py"
        )
    )
    statements: list[str] = []
    monkeypatch.setattr(migration["op"], "execute", statements.append)
    config = PostgresForecastEpisodeStoreConfig(dsn=forecast_database)
    store = PostgresForecastEpisodeStore(config=config)
    await store.verify_schema()
    episode = _episode(
        evaluation_kind=ForecastEvaluationKind.PREDICTED_NO_BREACH,
        predicted_value=None,
        interval_lower=None,
        interval_upper=None,
    )
    await store.record(episode)
    observation = ForecastObservation(
        observed_value=96.0,
        actual_breach_at=T0 + timedelta(minutes=30),
        telemetry_completeness=completeness,
        evidence_refs=("metric-window:example",),
        intervention_refs=("action-receipt:example",),
    )
    closure = ForecastEpisodeClosure(
        episode_id=episode.episode_id,
        expected_revision=episode.revision,
        closed_at=episode.closure_due_at,
        reason=ForecastClosureReason.ABSTAINED_NO_BREACH,
        outcome_payload=None,
        observation=observation,
    )
    assert await store.close(closure)
    restarted = PostgresForecastEpisodeStore(config=config)
    assert not await restarted.close(closure)
    with pytest.raises(ValueError, match="closure conflict"):
        await restarted.close(
            replace(closure, observation=replace(observation, observed_value=97.0))
        )
    async with await psycopg.AsyncConnection.connect(
        forecast_database, row_factory=dict_row
    ) as connection:
        cursor = await connection.execute(
            "SELECT closure_observation FROM forecast_episode WHERE episode_id = %s",
            (episode.episode_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["closure_observation"] == _observation_mapping(observation)
    snapshot = await restarted.health_snapshot(now=episode.closure_due_at)
    assert snapshot["observations"][completeness.value] == 1
    assert snapshot["observations"]["missing"] == 0
    assert snapshot["outcomes"] == []
    migration["downgrade"]()
    async with await psycopg.AsyncConnection.connect(forecast_database) as connection:
        for statement in statements:
            await connection.execute(statement)
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'forecast_episode' "
            "AND column_name = 'closure_observation'"
        )
        assert await cursor.fetchone() == (0,)
