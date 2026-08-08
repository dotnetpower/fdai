from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.case_history import CaseHistoryMaterializer, CaseHistoryRetentionService
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import (
    ForecastPublicationOutboxItem,
    forecast_publication_id,
)
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator, ForecastTargetSpec
from fdai.core.detection.forecast_observation import MetricForecastObservationProvider
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.core.learning import RuleCandidateHint
from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _outcome(index: int) -> ForecastOutcome:
    return ForecastOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=index + 1),
            "idempotency_key": f"forecast-outcome-{index}",
            "correlation_id": f"corr-{index}",
            "prediction_id": UUID(int=index + 100),
            "detector_id": "capacity-linear",
            "detector_version": "1.0.0",
            "access_scope_digest": "a" * 64,
            "target_digest": "b" * 64,
            "metric": "capacity_percent",
            "feature_cutoff": T0,
            "horizon_started_at": T0,
            "horizon_ended_at": T0 + timedelta(hours=1),
            "direction": "rising",
            "threshold": 90.0,
            "predicted_value": 95.0,
            "interval_lower": 91.0,
            "interval_upper": 99.0,
            "observed_value": 70.0,
            "actual_breach_at": None,
            "label": "false_positive",
            "evidence_refs": [f"metric-window:{index}"],
            "telemetry_completeness": "complete",
            "closed_at": T0 + timedelta(hours=2, minutes=index),
            "mode": "shadow",
        }
    )


async def test_forecast_outcome_flows_to_audit_case_history_and_mimir() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    agents = (
        Heimdall(bus=bus),
        Saga(),
        Muninn(
            case_history=CaseHistoryMaterializer(
                metadata=metadata,
                artifacts=artifacts,
            )
        ),
        Norns(forecast_error_threshold=2),
        Mimir(),
    )
    for agent in agents:
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)

    heimdall, saga, _muninn, _norns, mimir = agents
    assert isinstance(heimdall, Heimdall)
    assert isinstance(saga, Saga)
    assert isinstance(mimir, Mimir)
    assert await heimdall.publish_forecast_outcome(_outcome(1))
    assert await heimdall.publish_forecast_outcome(_outcome(2))
    assert bus.dead_letters == []
    indexed = next(
        message.payload
        for message in bus.published
        if message.topic == "object.context-index"
        and message.payload.get("correlation_id") == "corr-2"
    )

    latest = await metadata.latest(
        str(indexed["case_id"]),
        access_scope_digest="a" * 64,
    )
    assert latest is not None
    assert await artifacts.get(latest.storage_ref) is not None
    assert len(saga.replay_for_correlation("corr-2")) >= 1
    candidates = mimir.pending_candidates()
    assert len(candidates) == 1
    assert candidates[0]["source_signal"] == "forecast_case_history"
    assert candidates[0]["source_signal"] == "forecast_case_history"
    assert candidates[0]["norns_consensus"]["unanimous"] is True


async def test_huginn_retention_tick_drives_muninn_artifact_deletion() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await materializer.seal_forecast_outcome(
        _outcome(1),
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
    )
    storage_ref = record.storage_ref
    assert storage_ref is not None
    clock = [T0 + timedelta(days=59)]
    huginn = Huginn(bus=bus)
    muninn = Muninn(
        case_history_retention=CaseHistoryRetentionService(
            metadata=metadata,
            artifacts=artifacts,
        ),
        case_history_clock=lambda: clock[0],
    )
    muninn.bind_bus(bus)
    for topic in muninn.spec.subscribes:
        bus.subscribe(topic, "Muninn", muninn.on_typed_message)

    await huginn.ingest(
        {
            "event_id": "case-history-retention:1",
            "idempotency_key": "case-history-retention:1",
            "correlation_id": "case-history-retention:1",
            "source": "case-history-retention-scheduler",
            "event_type": "case_history.retention_due",
            "attributes": {"as_of": (T0 + timedelta(days=365)).isoformat()},
        }
    )
    assert await artifacts.get(storage_ref) is not None

    clock[0] = T0 + timedelta(days=61)
    await huginn.ingest(
        {
            "event_id": "case-history-retention:2",
            "idempotency_key": "case-history-retention:2",
            "correlation_id": "case-history-retention:2",
            "source": "case-history-retention-scheduler",
            "event_type": "case_history.retention_due",
            "attributes": {"as_of": T0.isoformat()},
        }
    )

    assert await artifacts.get(storage_ref) is None
    tombstone = await metadata.latest(record.case_id, access_scope_digest="a" * 64)
    assert tombstone is not None
    assert tombstone.deleted_at == T0 + timedelta(days=61)
    assert muninn.behavior_snapshot()["case_history:deleted"] == 1


async def test_forged_retention_tick_does_not_run_deletion() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await materializer.seal_forecast_outcome(
        _outcome(1),
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
    )
    muninn = Muninn(
        case_history_retention=CaseHistoryRetentionService(
            metadata=metadata,
            artifacts=artifacts,
        ),
        case_history_clock=lambda: T0 + timedelta(days=61),
    )
    await muninn.on_typed_message(
        "object.event",
        {
            "event_id": "case-history-retention:forged",
            "idempotency_key": "case-history-retention:forged",
            "correlation_id": "case-history-retention:forged",
            "source": "external-ingress",
            "event_type": "case_history.retention_due",
        },
    )
    assert record.storage_ref is not None
    assert await artifacts.get(record.storage_ref) is not None
    assert muninn.behavior_snapshot()["case_history:retention_invalid"] == 1


async def test_duplicate_outcome_does_not_double_count_learning() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(forecast_error_threshold=2)
    mimir = Mimir()
    for agent in (norns, mimir):
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    payload = {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "corr-1",
        "idempotency_key": "case-index-1",
        "case_id": "case-1",
        "revision": 1,
        "manifest_digest": "a" * 64,
        "access_scope_digest": "b" * 64,
        "purpose": "forecast-error-analysis",
        "outcome_label": "false_positive",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "metric": "capacity_percent",
        "case_ref": f"case-history:case-1:1:{'a' * 64}",
    }
    await bus.publish("Muninn", "object.context-index", payload)
    await bus.publish("Muninn", "object.context-index", payload)
    assert mimir.pending_candidates() == ()


async def test_norns_routes_grounded_case_analysis_hint() -> None:
    class _Analyzer:
        async def analyze(self, payload: dict[str, object]):
            return RuleCandidateHint(
                proposal_kind="threshold_adjustment",
                target_ref=str(payload["detector_id"]),
                pattern="Use a seasonal baseline before changing the threshold.",
                evidence_refs=(str(payload["case_ref"]),),
                confidence=0.8,
            )

    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(
        forecast_error_threshold=1,
        case_history_analyzer=_Analyzer(),  # type: ignore[arg-type]
    )
    mimir = Mimir()
    for agent in (norns, mimir):
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    payload = {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "corr-analysis",
        "idempotency_key": "case-index-analysis",
        "case_id": "case-analysis",
        "revision": 1,
        "manifest_digest": "a" * 64,
        "access_scope_digest": "b" * 64,
        "purpose": "forecast-error-analysis",
        "outcome_label": "false_negative",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "metric": "capacity_percent",
        "case_ref": f"case-history:case-analysis:1:{'a' * 64}",
    }
    await bus.publish("Muninn", "object.context-index", payload)
    candidates = mimir.pending_candidates()
    assert len(candidates) == 1
    assert candidates[0]["source_signal"] == "forecast_case_history_analysis"
    assert candidates[0]["target_rule_id"] == "capacity-linear"


async def test_forecast_tick_flows_through_heimdall_owned_topics() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = InMemoryForecastEpisodeStore()
    points = tuple(
        MetricPoint(
            metric_name="capacity_percent",
            at=T0 + timedelta(seconds=index),
            value=float(index),
            labels={"resource_id": "resource-1"},
        )
        for index in range(10)
    ) + (
        MetricPoint(
            metric_name="capacity_percent",
            at=T0 + timedelta(seconds=100),
            value=109.0,
            labels={"resource_id": "resource-1"},
        ),
        MetricPoint(
            metric_name="capacity_percent",
            at=T0 + timedelta(seconds=109),
            value=109.0,
            labels={"resource_id": "resource-1"},
        ),
    )
    metric_provider = StaticMetricProvider(points)
    evaluator = ForecastEpisodeEvaluator(
        source=MetricSeriesSource(metric_provider),
        store=store,
        targets=(
            ForecastTargetSpec(
                detector_id="capacity-linear",
                detector_version="1.0.0",
                scorer_version="1.0.0",
                access_scope_digest="a" * 64,
                resource_ref="resource-1",
                metric="capacity_percent",
                threshold=20.0,
                horizon_seconds=100,
                lookback_seconds=300,
                telemetry_grace_seconds=20,
            ),
        ),
    )
    clock = [T0 + timedelta(seconds=10)]
    heimdall = Heimdall(
        bus=bus,
        forecast_clock=lambda: clock[0],
        forecast_evaluator=evaluator,
        forecast_closer=ForecastClosureCoordinator(
            store=store,
            observations=MetricForecastObservationProvider(metric_provider),
        ),
        forecast_store=store,
    )
    await heimdall.on_typed_message(
        "object.event",
        {
            "event_id": "forecast-evaluation:1",
            "idempotency_key": "forecast-evaluation:1",
            "correlation_id": "forecast-evaluation:1",
            "source": "forecast-evaluation-scheduler",
            "event_type": "forecast.evaluation_due",
        },
    )
    assert len(bus.messages_on("object.forecast")) == 1
    clock[0] = T0 + timedelta(seconds=130)
    await heimdall.on_typed_message(
        "object.event",
        {
            "event_id": "forecast-evaluation:2",
            "idempotency_key": "forecast-evaluation:2",
            "correlation_id": "forecast-evaluation:2",
            "source": "forecast-evaluation-scheduler",
            "event_type": "forecast.evaluation_due",
        },
    )
    outcomes = bus.messages_on("object.forecast-outcome")
    assert len(outcomes) == 1
    assert outcomes[0].payload["label"] == "true_positive"


async def test_poison_publication_does_not_starve_following_item() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = InMemoryForecastEpisodeStore()
    episode = _outcome(1)
    poison_id = forecast_publication_id(
        episode_id=episode.prediction_id or episode.outcome_id,
        topic="object.forecast-outcome",
    )
    valid_id = forecast_publication_id(
        episode_id=episode.prediction_id or episode.outcome_id,
        topic="object.forecast",
    )
    store.outbox[poison_id] = ForecastPublicationOutboxItem(
        publication_id=poison_id,
        episode_id=episode.prediction_id or episode.outcome_id,
        topic="object.forecast-outcome",
        payload={"malformed": True},
        attempts=0,
    )
    store.outbox[valid_id] = ForecastPublicationOutboxItem(
        publication_id=valid_id,
        episode_id=episode.prediction_id or episode.outcome_id,
        topic="object.forecast",
        payload={
            "correlation_id": "corr-valid",
            "idempotency_key": "forecast-valid",
        },
        attempts=0,
    )
    heimdall = Heimdall(bus=bus, forecast_store=store)
    assert await heimdall._publish_forecast_outbox(now=T0) == 1
    assert poison_id in store.dead_lettered
    assert len(bus.messages_on("object.forecast")) == 1


async def test_norns_invalid_analysis_result_falls_back_to_inert_candidate() -> None:
    class _InvalidAnalyzer:
        async def analyze(self, payload: dict[str, object]) -> object:
            return {"unsafe": payload["case_ref"]}

    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(
        forecast_error_threshold=1,
        case_history_analyzer=_InvalidAnalyzer(),  # type: ignore[arg-type]
    )
    mimir = Mimir()
    for agent in (norns, mimir):
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    payload = {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "corr-invalid",
        "idempotency_key": "case-index-invalid",
        "case_id": "case-invalid",
        "revision": 1,
        "manifest_digest": "a" * 64,
        "access_scope_digest": "b" * 64,
        "purpose": "forecast-error-analysis",
        "outcome_label": "false_positive",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "metric": "capacity_percent",
        "case_ref": f"case-history:case-invalid:1:{'a' * 64}",
    }

    await bus.publish("Muninn", "object.context-index", payload)

    candidates = mimir.pending_candidates()
    assert len(candidates) == 1
    assert candidates[0]["source_signal"] == "forecast_case_history"
    assert norns.behavior_snapshot()["forecast_case:analysis_invalid"] == 1
