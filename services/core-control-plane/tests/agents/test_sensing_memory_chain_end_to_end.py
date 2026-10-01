from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.agents._framework import heimdall_forecast
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_operational_agents import rehydrate_operational_agents
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.muninn import Muninn
from fdai.agents.var import Var
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.readiness import DetectionReadinessDimension
from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def _action_semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"ops.restart-service": False},
        rollback_by_id={"ops.restart-service": "state_forward_only"},
    )


class _TopicFailOnceBus:
    def __init__(self, *, fail_topic: str) -> None:
        self.fail_topic = fail_topic
        self.failed = False
        self.payloads: dict[str, list[dict[str, object]]] = {}

    def subscribe(self, topic, agent_name, handler):  # noqa: ANN001, ANN201
        del topic, agent_name, handler

    async def publish(self, principal, topic, payload):  # noqa: ANN001, ANN201
        assert principal in {"Huginn", "Muninn"}
        if topic == self.fail_topic and not self.failed:
            self.failed = True
            raise RuntimeError(f"{topic} unavailable")
        self.payloads.setdefault(topic, []).append(dict(payload))


def _change_raw() -> dict[str, object]:
    return {
        "id": "raw-change-1",
        "event_id": "raw-change-1",
        "idempotency_key": "raw-change-1",
        "correlation_id": "corr-change-1",
        "resource_id": "resource-1",
        "source": "activity-log",
        "event_type": "change.planned",
        "occurred_at": T0.isoformat(),
        "change": {
            "id": "change-1",
            "target_ref": "resource-1",
            "actor_ref": "operator@example.com",
            "change_type": "planned",
            "occurred_at": T0.isoformat(),
        },
    }


async def test_huginn_retries_missing_change_without_republishing_event() -> None:
    store = InMemoryStateStore()
    bus = _TopicFailOnceBus(fail_topic="object.change")
    huginn = Huginn(bus=bus, state_store=store, clock=lambda: T0, dedup_clock=lambda: T0)

    with pytest.raises(RuntimeError, match="object.change unavailable"):
        await huginn.ingest(_change_raw())

    assert len(bus.payloads["object.event"]) == 1
    assert "object.change" not in bus.payloads

    recovered = Huginn(
        bus=bus,
        state_store=store,
        clock=lambda: T0 + timedelta(seconds=90),
        dedup_clock=lambda: T0 + timedelta(seconds=90),
    )
    await recovered.ingest(_change_raw())

    assert len(bus.payloads["object.event"]) == 1
    assert len(bus.payloads["object.change"]) == 1
    assert bus.payloads["object.event"][0]["idempotency_key"]
    assert bus.payloads["object.change"][0]["idempotency_key"]


def _forecast_outcome() -> ForecastOutcome:
    return ForecastOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=101),
            "idempotency_key": "forecast-outcome-r10",
            "correlation_id": "corr-forecast-r10",
            "prediction_id": UUID(int=201),
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
            "evidence_refs": ["metric-window:r10"],
            "telemetry_completeness": "complete",
            "closed_at": T0 + timedelta(hours=2),
            "mode": "shadow",
        }
    )


async def test_direct_forecast_outcome_uses_retryable_outbox() -> None:
    store = InMemoryForecastEpisodeStore()
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_store=store, forecast_clock=lambda: T0)

    assert await heimdall.publish_forecast_outcome(_forecast_outcome())
    assert len(bus.messages_on("object.forecast-outcome")) == 1
    assert store.published


async def test_forecast_tick_timeout_records_incomplete_not_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SlowEvaluator:
        async def evaluate(self, *, now: datetime) -> int:
            del now
            await asyncio.sleep(0.01)
            return 1

    class _NoopCloser:
        async def close_due(self, *, now: datetime) -> int:
            del now
            return 0

    monkeypatch.setattr(heimdall_forecast, "_FORECAST_PROVIDER_TIMEOUT_SECONDS", 0.001)
    heimdall = Heimdall(
        forecast_store=InMemoryForecastEpisodeStore(),
        forecast_evaluator=_SlowEvaluator(),
        forecast_closer=_NoopCloser(),
        forecast_clock=lambda: T0,
    )

    await heimdall.on_typed_message(
        "object.event",
        {
            "event_id": "forecast-evaluation:r10-timeout",
            "idempotency_key": "forecast-evaluation:r10-timeout",
            "correlation_id": "forecast-evaluation:r10-timeout",
            "source": "forecast-evaluation-scheduler",
            "event_type": "forecast.evaluation_due",
        },
    )

    behavior = heimdall.behavior_snapshot()
    assert behavior["forecast_tick:incomplete"] == 1
    assert "forecast_tick:completed" not in behavior


def test_default_muninn_health_marks_forecast_learning_unavailable() -> None:
    muninn = Muninn(durable_state_store=InMemoryStateStore())

    health = muninn.health()

    assert health["status"] == "degraded"
    assert health["forecast_learning"] == {
        "case_history_available": False,
        "evidence_state": "materializer_unbound",
    }


async def test_detection_readiness_keys_include_pass_and_stale_status() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: T0)

    async def emit_pass(pass_id: str, observed_at: datetime) -> None:
        for dimension in DetectionReadinessDimension:
            await heimdall.on_typed_message(
                "object.event",
                {
                    "producer_principal": "Huginn",
                    "event_type": "detection.readiness.observed",
                    "correlation_id": f"corr-{pass_id}",
                    "idempotency_key": f"readiness-{pass_id}-{dimension.value}",
                    "resource_id": "cluster-1",
                    "attributes": {
                        "pass_id": pass_id,
                        "dimension": dimension.value,
                        "status": "passed",
                        "observed_at": observed_at.isoformat(),
                        "expires_at": (observed_at + timedelta(minutes=1)).isoformat(),
                        "source": "probe",
                        "evidence_digest": "a" * 64,
                    },
                },
            )

    await emit_pass("pass-a", T0 - timedelta(minutes=2))
    await emit_pass("pass-b", T0)

    payloads = [record.payload for record in bus.messages_on("object.drift")]
    assert len(payloads) == 2
    assert payloads[0]["idempotency_key"] != payloads[1]["idempotency_key"]
    assert payloads[0]["pass_id"] == "pass-a"
    assert payloads[1]["pass_id"] == "pass-b"
    assert payloads[0]["content_digest"]
    assert payloads[1]["content_digest"]
    assert payloads[0]["readiness_status"] == "stale"
    assert payloads[1]["readiness_status"] == "ready"


async def test_var_and_muninn_startup_recovery_hooks_republish_pending_work() -> None:
    store = InMemoryStateStore()
    bus = _TopicFailOnceBus(fail_topic="object.context-index")
    muninn = Muninn(durable_state_store=store)
    muninn.bind_bus(bus)
    payload = {
        "producer_principal": "Muninn",
        "kind": "semantic_retrieval_failure",
        "correlation_id": "corr-context-r10",
        "idempotency_key": "semantic-feedback:r10",
    }
    with pytest.raises(RuntimeError, match="object.context-index unavailable"):
        await muninn._publish_with_outbox(  # noqa: SLF001 - startup recovery regression
            "pantheon/muninn/operational-outbox/test/r10",
            "object.context-index",
            payload,
        )

    var_bus = InMemoryBus(registry=load_pantheon())
    var = Var(bus=var_bus, state_store=store, action_semantics=_action_semantics())
    await var.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": "corr-var-r10",
            "idempotency_key": "action-run:var-r10",
            "action_type": "ops.restart-service",
            "resource_id": "resource-1",
            "state": "hil_pending",
        },
    )
    var.bus = None
    assert await var.decide(
        "corr-var-r10",
        approver="reviewer@example.com",
        decision="approve",
    )

    recovery_bus = InMemoryBus(registry=load_pantheon())
    recovered_var = Var(
        bus=recovery_bus,
        state_store=store,
        action_semantics=_action_semantics(),
    )
    recovered_muninn = Muninn(durable_state_store=store)
    recovered_muninn.bind_bus(bus)
    await rehydrate_operational_agents({"Var": recovered_var, "Muninn": recovered_muninn})

    assert len(recovery_bus.messages_on("object.approval")) == 1
    assert bus.payloads["object.context-index"][0]["correlation_id"] == "corr-context-r10"
