"""Loki off-path adversarial scenario generation contract tests."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.loki_adversarial import ChaosScenarioCandidate
from fdai.agents._framework.loki_scheduling import ChaosScheduleConfig
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.loki import Loki
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)


class _Generator:
    def __init__(self, candidates: Sequence[ChaosScenarioCandidate]) -> None:
        self.candidates = tuple(candidates)
        self.calls = 0

    async def generate_scenarios(self, design_ref: str) -> Sequence[ChaosScenarioCandidate]:
        self.calls += 1
        assert design_ref == "design:chaos-hardening"
        return self.candidates


class _RaisingGenerator:
    async def generate_scenarios(self, _design_ref: str) -> Sequence[ChaosScenarioCandidate]:
        raise AssertionError("hot path must not call the adversarial generator")


def _schedule(schedule_id: str, targets: tuple[str, ...]) -> ChaosScheduleConfig:
    return ChaosScheduleConfig(
        schedule_id=schedule_id,
        cadence=timedelta(days=7),
        targets=targets,
        causal_hypothesis_ref=f"hypothesis:{schedule_id}",
        refutation_query_ref=f"query:{schedule_id}",
        impact_envelope_id=f"impact:{schedule_id}",
        recovery_plan_id=f"recovery:{schedule_id}",
        dry_run_receipt=f"dry-run:{schedule_id}",
        start_at=_NOW,
    )


async def test_loki_adversarial_generation_accepts_only_inert_regression_passing_candidates() -> (
    None
):
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    existing = _schedule("existing", ("target-a", "target-b"))
    duplicate = ChaosScenarioCandidate(
        scenario_id="duplicate",
        schedule=existing,
        evidence_refs=("evidence:duplicate",),
    )
    weakened = ChaosScenarioCandidate(
        scenario_id="weakened",
        schedule=_schedule("weakened", ("target-a",)),
        evidence_refs=("evidence:weakened",),
    )
    accepted = ChaosScenarioCandidate(
        scenario_id="accepted",
        schedule=_schedule("accepted", ("target-c",)),
        evidence_refs=("evidence:accepted",),
    )
    generator = _Generator((duplicate, weakened, accepted))
    loki = Loki(
        bus=bus,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        scenario_generator=generator,
        scenario_corpus=(existing,),
    )

    accepted_count = await loki.run_adversarial_generation(
        design_ref="design:chaos-hardening",
    )

    assert accepted_count == 1
    assert generator.calls == 1
    payloads = [message.payload for message in bus.messages_on("object.chaos-experiment")]
    assert {payload["scenario_state"] for payload in payloads} == {
        "duplicate_coverage",
        "weakened_coverage",
        "accepted",
    }
    assert all(payload["kind"] == "adversarial_scenario_candidate" for payload in payloads)
    assert all(payload["inert"] is True for payload in payloads)
    assert all(payload["execution_authority"] is False for payload in payloads)
    assert loki.behavior_snapshot()["adversarial_scenario:accepted"] == 1
    assert loki.behavior_snapshot()["adversarial_scenario:duplicate_coverage"] == 1
    assert loki.behavior_snapshot()["adversarial_scenario:weakened_coverage"] == 1


async def test_loki_adversarial_generation_without_bus_does_not_accept_or_persist_candidate() -> (
    None
):
    store = InMemoryStateStore()
    accepted = ChaosScenarioCandidate(
        scenario_id="accepted",
        schedule=_schedule("accepted", ("target-c",)),
        evidence_refs=("evidence:accepted",),
    )
    loki = Loki(
        bus=None,
        state_store=store,
        clock=lambda: _NOW,
        scenario_generator=_Generator((accepted,)),
    )

    accepted_count = await loki.run_adversarial_generation(
        design_ref="design:chaos-hardening",
    )

    assert accepted_count == 0
    assert loki.behavior_snapshot()["adversarial_scenario:publication_unavailable"] == 1
    assert await store.read_states("pantheon/loki/adversarial-scenarios/", limit=10) == ()


async def test_loki_adversarial_generation_does_not_accept_until_audit_publishes() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store = InMemoryStateStore()
    accepted = ChaosScenarioCandidate(
        scenario_id="accepted-after-budget",
        schedule=_schedule("accepted-after-budget", ("target-c",)),
        evidence_refs=("evidence:accepted",),
    )
    generator = _Generator((accepted,))
    budget_now = 10.0
    loki = Loki(
        bus=bus,
        state_store=store,
        clock=lambda: _NOW,
        scenario_generator=generator,
    )
    loki._proposal_limiter = RateLimiter(
        per_minute=1,
        per_hour=2,
        now=lambda: budget_now,
    )
    assert await loki._publish_proposal(
        "object.chaos-experiment",
        {
            "correlation_id": "budget-primer",
            "idempotency_key": "budget-primer",
            "kind": "adversarial_scenario_candidate",
        },
    )
    bus.clear_history()

    accepted_count = await loki.run_adversarial_generation(
        design_ref="design:chaos-hardening",
    )

    assert accepted_count == 0
    assert bus.messages_on("object.chaos-experiment") == []
    assert list(loki._proposal_queue) == []
    assert loki.behavior_snapshot()["adversarial_scenario:audit_unpublished"] == 1
    assert await store.read_states("pantheon/loki/adversarial-scenarios/", limit=10) == ()

    budget_now = 71.0
    accepted_count = await loki.run_adversarial_generation(
        design_ref="design:chaos-hardening",
    )

    assert accepted_count == 1
    assert generator.calls == 2
    assert len(bus.messages_on("object.chaos-experiment")) == 1
    persisted = await store.read_states("pantheon/loki/adversarial-scenarios/", limit=10)
    assert len(persisted) == 1
    assert persisted[0]["state"] == "accepted_inert"


async def test_loki_rate_limited_process_local_chaos_proposal_is_not_flushed_later() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    budget_now = 10.0
    loki = Loki(bus=bus, clock=lambda: _NOW)
    loki._proposal_limiter = RateLimiter(
        per_minute=1,
        per_hour=2,
        now=lambda: budget_now,
    )
    assert await loki._publish_proposal(
        "object.chaos-experiment",
        {
            "correlation_id": "budget-primer",
            "idempotency_key": "budget-primer",
            "kind": "adversarial_scenario_candidate",
        },
    )
    bus.clear_history()

    proposal = await loki.propose_experiment(
        experiment_id="ordinary-rate-limited",
        action_type="tool.run-chaos-experiment",
        targets=("target-a",),
        correlation_id="ordinary-rate-limited",
        causal_hypothesis_ref="hypothesis:ordinary",
        refutation_query_ref="query:ordinary",
        impact_envelope_id="impact:ordinary",
        recovery_plan_id="recovery:ordinary",
        dry_run_receipt="dry-run:ordinary",
    )

    assert proposal.accepted is False
    assert proposal.reason == "publication_unavailable"
    assert bus.messages_on("object.chaos-experiment") == []
    assert list(loki._proposal_queue) == []

    budget_now = 71.0
    await loki.maintenance_tick()

    assert bus.messages_on("object.chaos-experiment") == []


async def test_loki_hot_path_never_invokes_adversarial_generator() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    loki = Loki(
        bus=bus,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        scenario_generator=_RaisingGenerator(),
    )

    await loki.maintenance_tick()
    await loki.propose_experiment(
        experiment_id="ordinary-proposal",
        action_type="tool.run-chaos-experiment",
        targets=("target-a",),
        correlation_id="ordinary-proposal",
        causal_hypothesis_ref="hypothesis:ordinary",
        refutation_query_ref="query:ordinary",
        impact_envelope_id="impact:ordinary",
        recovery_plan_id="recovery:ordinary",
        dry_run_receipt="dry-run:ordinary",
    )

    assert bus.messages_on("object.chaos-experiment")
    source = inspect.getsource(Loki.on_typed_message) + inspect.getsource(Loki.maintenance_tick)
    assert "generate_scenarios" not in source


async def test_adversarial_candidate_kind_is_audited_but_never_grounded_as_proposal() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus)
    forseti = Forseti(bus=bus)
    thor = Thor(bus=bus)
    saga = Saga()
    bus.subscribe("object.chaos-experiment", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.chaos-experiment", "Saga", saga.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)

    await bus.publish(
        "Loki",
        "object.chaos-experiment",
        {
            "kind": "adversarial_scenario_candidate",
            "correlation_id": "corr-adversarial-kind",
            "idempotency_key": "adversarial-kind-key",
            "scenario_id": "candidate-with-proposal-fields",
            "scenario_state": "accepted",
            "inert": True,
            "execution_authority": False,
            "experiment_id": "must-not-ground",
            "action_type": "tool.run-chaos-experiment",
            "targets": ["target-a"],
            "causal_hypothesis_ref": "hypothesis:complete",
            "refutation_query_ref": "query:complete",
            "impact_envelope_id": "impact:complete",
            "recovery_plan_id": "recovery:complete",
            "dry_run_receipt": "dry-run:complete",
            "human_approval_required": True,
            "evidence_refs": ["evidence:generated"],
        },
    )

    assert heimdall.behavior_snapshot()["chaos_experiment:ignored_non_proposal_kind"] == 1
    assert bus.messages_on("object.anomaly") == []
    assert bus.messages_on("object.verdict") == []
    assert bus.messages_on("object.action-run") == []
    assert len(saga.replay_for_correlation("corr-adversarial-kind")) == 1
