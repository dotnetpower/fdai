from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fdai.agents import heimdall as heimdall_module
from fdai.agents._framework import heimdall_action_observation as action_observation_module
from fdai.agents._framework import heimdall_forecast as forecast_module
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.shared.providers.cost_governance import CostAnalysisSample
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2028, 1, 2, tzinfo=UTC)
RELEASE = "sha256:" + "8" * 64


class RecordingBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, principal: str, topic: str, payload: Mapping[str, Any]) -> None:
        self.messages.append((principal, topic, dict(payload)))
        await asyncio.sleep(0)


class BlockingBus(RecordingBus):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, principal: str, topic: str, payload: Mapping[str, Any]) -> None:
        self.messages.append((principal, topic, dict(payload)))
        self.entered.set()
        await self.release.wait()


class YieldingWriteStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        self.entered.set()
        await self.release.wait()
        await super().write_state(key, value)


def _raw_event(key: str = "dup-race", *, change: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "idempotency_key": key,
        "event_id": f"event:{key}",
        "correlation_id": f"corr:{key}",
        "source": "unit-test",
        "event_type": "change.requested" if change else "availability.probe_failed",
        "resource_id": "resource-a",
        "occurred_at": NOW.isoformat(),
    }
    if change:
        raw["change"] = {
            "id": f"change:{key}",
            "target_ref": "resource-a",
            "actor_ref": "operator@example.com",
            "occurred_at": NOW.isoformat(),
        }
    return raw


async def test_huginn_serializes_duplicate_ingress_without_durable_journal() -> None:
    bus = RecordingBus()
    huginn = Huginn(bus=bus, clock=lambda: NOW + timedelta(seconds=1))  # type: ignore[arg-type]

    first, second = await asyncio.gather(huginn.ingest(_raw_event()), huginn.ingest(_raw_event()))

    assert sum(result is not None for result in (first, second)) == 1
    assert sum(topic == "object.event" for _, topic, _ in bus.messages) == 1
    assert huginn.behavior_snapshot()["deduped"] == 1


async def test_huginn_cancelled_event_publish_finishes_change_and_dedup() -> None:
    bus = BlockingBus()
    store = InMemoryStateStore()
    huginn = Huginn(
        bus=bus,  # type: ignore[arg-type]
        state_store=store,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    task = asyncio.create_task(huginn.ingest(_raw_event("change-race", change=True)))
    await bus.entered.wait()
    task.cancel()
    bus.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert [topic for _, topic, _ in bus.messages] == ["object.event", "object.change"]
    assert await huginn.ingest(_raw_event("change-race", change=True)) is None


async def test_huginn_cancelled_discovery_projection_records_retryable_claim() -> None:
    entered = asyncio.Event()

    async def projector(payload: Mapping[str, Any]) -> None:
        entered.set()
        await asyncio.Event().wait()

    raw = _raw_event("inventory-race")
    raw["payload"] = {
        "inventory_change": {
            "resource": {"resource_id": "resource-a", "type": "compute.vm"},
        }
    }
    store = InMemoryStateStore()
    huginn = Huginn(
        state_store=store,
        discovery_projector=projector,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    task = asyncio.create_task(huginn.ingest(raw))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert huginn.behavior_snapshot()["discovery_projection:cancelled"] == 1


async def test_freyr_cost_evidence_is_not_visible_until_durable_write_finishes() -> None:
    store = YieldingWriteStore()
    freyr = Freyr(state_store=store)
    payload = {
        "producer_principal": "Njord",
        "resource_id": "resource-a",
        "evidence_ref": "cost-evidence:1",
        "correlation_id": "corr-a",
        "observed_at": NOW.isoformat(),
    }
    task = asyncio.create_task(freyr._retain_cost_evidence(payload))  # noqa: SLF001
    await store.entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert freyr._cost_evidence == {}  # noqa: SLF001


async def test_freyr_pending_capacity_sample_retries_after_cancelled_publish() -> None:
    bus = BlockingBus()
    freyr = Freyr(bus=bus, state_store=InMemoryStateStore())  # type: ignore[arg-type]
    task = asyncio.create_task(
        freyr.ingest_utilization(
            resource_id="resource-a",
            utilization=0.9,
            correlation_id="corr-a",
            observed_at=NOW.isoformat(),
            sample_key="sample-a",
        )
    )
    await bus.entered.wait()
    task.cancel()
    bus.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    retry_bus = RecordingBus()
    freyr.bus = retry_bus  # type: ignore[assignment]
    await freyr.ingest_utilization(
        resource_id="resource-a",
        utilization=0.9,
        correlation_id="corr-a",
        observed_at=NOW.isoformat(),
        sample_key="sample-a",
    )

    assert [topic for _, topic, _ in retry_bus.messages] == ["object.capacity-forecast"]


class BlockingAdvisory:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> None:
        self.entered.set()
        await asyncio.Event().wait()

    def estimate_cost_effect(self, action_type: str) -> None:
        return None


class DelayByAmountAdvisory:
    def __init__(self) -> None:
        self.release_old = asyncio.Event()

    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> None:
        if sample.amount_usd == Decimal("100"):
            await self.release_old.wait()
        return None

    def estimate_cost_effect(self, action_type: str) -> None:
        return None


async def test_njord_provider_timeout_leaves_sample_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fdai.agents.njord._ADVISORY_TIMEOUT_SECONDS", 0.01)
    provider = BlockingAdvisory()
    njord = Njord(
        advisory_provider=provider,  # type: ignore[arg-type]
        package_enabled=True,
        allow_unbound_activation_reader=True,
        state_store=InMemoryStateStore(),
    )
    sample = _cost_sample(Decimal("200"), NOW)

    assert await njord._analyze(sample, sample_key="cost-sample-a") is None  # noqa: SLF001
    assert njord.behavior_snapshot()["cost_sample:provider_timeout"] == 1

    njord._advisory_provider = _NoFindingAdvisory()  # noqa: SLF001
    assert await njord._analyze(sample, sample_key="cost-sample-a") is None  # noqa: SLF001
    assert njord.behavior_snapshot()["cost_sample:no_finding"] == 1


async def test_njord_newer_sample_survives_older_provider_completion() -> None:
    provider = DelayByAmountAdvisory()
    njord = Njord(
        advisory_provider=provider,  # type: ignore[arg-type]
        package_enabled=True,
        allow_unbound_activation_reader=True,
        state_store=InMemoryStateStore(),
    )
    older = _cost_sample(Decimal("100"), NOW)
    newer = _cost_sample(Decimal("200"), NOW + timedelta(minutes=1))
    older_task = asyncio.create_task(njord._analyze(older, sample_key="older"))  # noqa: SLF001
    await asyncio.sleep(0)
    await njord._analyze(newer, sample_key="newer")  # noqa: SLF001
    provider.release_old.set()
    await older_task

    assert njord._latest["scope-a"] == (200.0, newer.observed_at.isoformat())  # noqa: SLF001


async def test_njord_memory_does_not_advance_until_sample_state_is_durable() -> None:
    store = YieldingWriteStore()
    njord = Njord(state_store=store)
    task = asyncio.create_task(njord._remember_sample(_cost_sample(Decimal("123"), NOW)))  # noqa: SLF001
    await store.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert njord._counts == {}  # noqa: SLF001
    assert njord._latest == {}  # noqa: SLF001


async def test_loki_cancelled_publication_releases_process_local_reservation() -> None:
    bus = BlockingBus()
    loki = Loki(bus=bus, blast_radius_cap=1)  # type: ignore[arg-type]
    task = asyncio.create_task(_propose(loki))
    await bus.entered.wait()
    task.cancel()
    bus.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert loki._in_flight_targets == set()  # noqa: SLF001


async def test_loki_resilience_score_memory_waits_for_durable_write() -> None:
    store = YieldingWriteStore()
    loki = Loki(state_store=store)
    candidate = {
        "resource_id": "resource-a",
        "score": 0.7,
        "observed_at": NOW.isoformat(),
    }
    task = asyncio.create_task(loki._remember_resilience_score(candidate))  # noqa: SLF001
    await store.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert loki._resilience_scores == {}  # noqa: SLF001


async def test_loki_maintenance_does_not_expire_active_publication() -> None:
    bus = BlockingBus()
    current = NOW

    def clock() -> datetime:
        return current

    loki = Loki(
        bus=bus,  # type: ignore[arg-type]
        blast_radius_cap=1,
        clock=clock,
        reservation_ttl=timedelta(seconds=1),
    )
    task = asyncio.create_task(_propose(loki))
    await bus.entered.wait()
    current = NOW + timedelta(seconds=5)
    await loki.maintenance_tick()
    assert loki._in_flight_targets == {"resource-a"}  # noqa: SLF001
    bus.release.set()
    await task


async def test_heimdall_forecast_tick_bounds_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast_module, "_FORECAST_PROVIDER_TIMEOUT_SECONDS", 0.01)
    heimdall = Heimdall(
        forecast_evaluator=_BlockingEvaluator(),  # type: ignore[arg-type]
        forecast_closer=_NoopCloser(),  # type: ignore[arg-type]
        forecast_store=InMemoryForecastEpisodeStore(),
        forecast_clock=lambda: NOW,
    )
    await heimdall._run_forecast_tick(_forecast_tick())  # noqa: SLF001

    assert heimdall.behavior_snapshot()["forecast_episode:evaluation_timeout"] == 1


async def test_heimdall_action_observation_hook_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(action_observation_module, "_ACTION_OBSERVATION_TIMEOUT_SECONDS", 0.01)

    async def hook(payload: dict[str, Any]) -> bool:
        await asyncio.Event().wait()
        return True

    heimdall = Heimdall(action_observation_hook=hook)
    await heimdall._observe_action_run({"correlation_id": "corr-a"})  # noqa: SLF001

    assert heimdall.behavior_snapshot()["action_effect_observation:timeout"] == 1


async def test_heimdall_rule_generation_validation_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(heimdall_module, "_RULE_VALIDATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(heimdall_module, "RuleGenerationBuildResultEvent", _FakeBuildResultEvent)
    heimdall = Heimdall()
    heimdall.bind_rule_generation_validation_handler(_BlockingRuleValidationHandler())  # type: ignore[arg-type]

    await heimdall._validate_rule_generation({"producer_principal": "Mimir"})  # noqa: SLF001

    assert heimdall.behavior_snapshot()["rule_generation_validation:timeout"] == 1


async def test_heimdall_publish_once_completes_state_after_cancellation() -> None:
    bus = BlockingBus()
    store = InMemoryStateStore()
    heimdall = Heimdall(bus=bus, state_store=store)  # type: ignore[arg-type]
    payload = {
        "producer_principal": "Heimdall",
        "correlation_id": "corr-a",
        "idempotency_key": "heimdall-publication-a",
    }
    task = asyncio.create_task(heimdall._publish_once("object.anomaly", payload))  # noqa: SLF001
    await bus.entered.wait()
    task.cancel()
    bus.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await heimdall._publish_once("object.anomaly", payload) is False  # noqa: SLF001
    assert len(bus.messages) == 1


def _cost_sample(amount: Decimal, observed_at: datetime) -> CostAnalysisSample:
    return CostAnalysisSample(
        scope_id="scope-a",
        resource_id="resource-a",
        amount_usd=amount,
        correlation_id="corr-a",
        observed_at=observed_at,
        source_authority="unit-test-cost",
        completeness=Decimal("1"),
        ontology_release_digest=RELEASE,
    )


class _NoFindingAdvisory:
    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> None:
        return None

    def estimate_cost_effect(self, action_type: str) -> None:
        return None


async def _propose(loki: Loki) -> Any:
    return await loki.propose_experiment(
        experiment_id="experiment-a",
        action_type="tool.run-chaos-experiment",
        targets=("resource-a",),
        causal_hypothesis_ref="causal-a",
        refutation_query_ref="query-a",
        impact_envelope_id="impact-a",
        recovery_plan_id="recovery-a",
        dry_run_receipt="dry-run-a",
    )


class _BlockingEvaluator:
    async def evaluate(self, *, now: datetime) -> int:
        del now
        await asyncio.Event().wait()
        return 0


class _NoopCloser:
    async def close_due(self, *, now: datetime) -> int:
        del now
        return 0


def _forecast_tick() -> dict[str, object]:
    return {
        "source": "forecast-evaluation-scheduler",
        "event_id": "forecast-evaluation:tick-a",
        "idempotency_key": "forecast-evaluation:tick-a",
        "correlation_id": "forecast-evaluation:tick-a",
    }


class _FakeRequest:
    correlation_id = "rule-validation-corr"


class _FakeBuildResult:
    request = _FakeRequest()


class _FakeBuildResultEvent:
    model_fields: dict[str, object] = {}

    @classmethod
    def model_validate(cls, payload: Mapping[str, Any]) -> _FakeBuildResult:
        del payload
        return _FakeBuildResult()


class _BlockingRuleValidationHandler:
    async def handle(self, build_result: _FakeBuildResult) -> None:
        del build_result
        await asyncio.Event().wait()
