from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework import thor_persistence
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.cross_vertical_candidates import INITIAL_VERTICAL_DOMAINS
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.forseti import Forseti
from fdai.agents.thor import Thor
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), isolate_handlers=False)


def _run(
    correlation_id: str,
    *,
    state: ActionRunState = ActionRunState.SUCCEEDED,
    resource_id: str = "vm-1",
    terminal_published: bool = False,
    approval_expires_at: datetime | None = None,
) -> ActionRun:
    return ActionRun(
        correlation_id=correlation_id,
        action_type="ops.restart-service",
        resource_id=resource_id,
        state=state,
        verdict="auto" if state is not ActionRunState.HIL_PENDING else "hil",
        idempotency_key=f"{correlation_id}:idem",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
        rollback_contract="state_forward_only",
        approval_expires_at=approval_expires_at,
        terminal_published=terminal_published,
    )


def _thor_action_run(run: ActionRun) -> dict[str, object]:
    payload = run.to_dict()
    payload["producer_principal"] = "Thor"
    return payload


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={
            "remediate.disable-public-access": False,
            "ops.restart-service": False,
        },
        rollback_by_id={
            "remediate.disable-public-access": "state_forward_only",
            "ops.restart-service": "state_forward_only",
        },
    )


def _forseti(
    store: InMemoryStateStore, bus: InMemoryBus | None = None, *, now: datetime = _NOW
) -> Forseti:
    return Forseti(
        bus=bus,
        action_semantics=_semantics(),
        state_store=store,
        test_context_clock=lambda: now,
    )


def _event(correlation_id: str, event_type: str = "public_network_enabled") -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:event",
        "resource_id": "vm-1",
        "event_type": event_type,
    }


def _candidate(
    *,
    topic: str,
    correlation_id: str,
    action_type: str,
    utility: float,
    observed_at: datetime = _NOW,
) -> dict[str, Any]:
    principal = {
        "object.resilience-score": "Loki",
        "object.drift": "Heimdall",
        "object.cost-anomaly": "Njord",
    }[topic]
    payload: dict[str, Any] = {
        "producer_principal": principal,
        "kind": "cross_vertical_candidate",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:{topic}",
        "resource_id": "vm-1",
        "observed_at": observed_at.isoformat(),
        "action_type": action_type,
        "effects": [
            {
                "objective_id": "availability",
                "metric": "availability",
                "observation_window_seconds": 300,
                "utility": utility,
                "confidence": 0.9,
                "expected_min": 0.0,
                "expected_max": 1.0,
            }
        ],
        "evidence_refs": [f"evidence:{topic}"],
    }
    if topic == "object.resilience-score":
        payload["score"] = 0.5
    return payload


async def test_thor_restart_republishes_terminal_state_after_bus_absence() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    await store.save(_run("corr-thor-terminal"))

    await Thor(bus=None, state_store=store, clock=lambda: _NOW).rehydrate()
    assert await state.read_state("thor:run|corr-thor-terminal") is not None

    bus = _bus()
    await Thor(bus=bus, state_store=store, clock=lambda: _NOW).rehydrate()

    assert bus.messages_on("object.action-run")[-1].payload["state"] == "succeeded"


async def test_thor_restart_expires_hil_approval_windows() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    await store.save(
        _run(
            "corr-thor-expired",
            state=ActionRunState.HIL_PENDING,
            approval_expires_at=_NOW - timedelta(seconds=1),
        )
    )
    bus = _bus()

    await Thor(bus=bus, state_store=store, clock=lambda: _NOW).rehydrate()

    published = bus.messages_on("object.action-run")[-1].payload
    assert published["state"] == "rejected"
    assert published["outcome"] == "approval_expired"


async def test_thor_restart_honors_terminal_publication_checkpoint() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    await store.save(_run("corr-thor-published", terminal_published=True))
    bus = _bus()

    await Thor(bus=bus, state_store=store, clock=lambda: _NOW).rehydrate()

    assert bus.messages_on("object.action-run") == []


def test_thor_terminal_overflow_keeps_process_local_idempotency_fence() -> None:
    thor = Thor(clock=lambda: _NOW)
    thor._max_retained_runs = 1  # noqa: SLF001
    first = _run("corr-thor-first", terminal_published=True)
    first_key = first.idempotency_key
    thor.action_runs[first.correlation_id] = first
    thor._idempotency_runs[first_key] = first  # noqa: SLF001
    second = _run("corr-thor-second", terminal_published=True)
    thor.action_runs[second.correlation_id] = second
    thor._idempotency_runs[second.idempotency_key] = second  # noqa: SLF001

    thor_persistence.evict_terminal_overflow(thor)

    assert first.correlation_id not in thor.action_runs
    assert thor._idempotency_runs[first_key] is first  # noqa: SLF001


async def test_thor_restart_publishes_contended_unclaimed_runs() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    await store.save(_run("corr-thor-a", state=ActionRunState.VERDICTED))
    await store.save(_run("corr-thor-b", state=ActionRunState.VERDICTED))
    bus = _bus()

    await Thor(bus=bus, state_store=store, clock=lambda: _NOW).rehydrate()

    published = [message.payload for message in bus.messages_on("object.action-run")]
    assert {payload["correlation_id"] for payload in published} == {"corr-thor-a", "corr-thor-b"}
    assert {payload["outcome"] for payload in published} == {
        "resource_claim_contended_after_restart"
    }


async def test_vidar_startup_recovers_unpublished_terminal_rollback() -> None:
    state = InMemoryStateStore()
    calls = 0

    async def rollback(_command: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "rollback:ok"

    action = _thor_action_run(_run("corr-vidar"))
    vidar = Vidar(executors={"state_forward_only": rollback}, state_store=state)
    await vidar.rollback(action)

    bus = _bus()
    restarted = Vidar(bus=bus, executors={"state_forward_only": rollback}, state_store=state)
    recovered = await restarted.recover_rollbacks()

    assert recovered == 1
    assert calls == 1
    assert bus.messages_on("object.rollback")[-1].payload["state"] == "succeeded"


async def test_vidar_process_local_terminal_fence_survives_lru_eviction() -> None:
    calls: list[str] = []

    async def rollback(command: dict[str, Any]) -> str:
        calls.append(str(command["correlation_id"]))
        return "rollback:ok"

    vidar = Vidar(executors={"state_forward_only": rollback}, allow_process_local_rollback=True)
    vidar._MAX_RECORDS = 1  # noqa: SLF001
    action = _thor_action_run(_run("corr-vidar-local"))
    await vidar.rollback(action)
    await vidar.rollback(_thor_action_run(_run("corr-vidar-new")))
    await vidar.rollback(action)

    assert calls == ["corr-vidar-local", "corr-vidar-new"]


async def test_vidar_health_reports_recovered_durable_publication_backlog() -> None:
    state = InMemoryStateStore()

    async def rollback(_command: dict[str, Any]) -> str:
        return "rollback:ok"

    await Vidar(executors={"state_forward_only": rollback}, state_store=state).rollback(
        _thor_action_run(_run("corr-health"))
    )
    vidar = Vidar(state_store=state)
    await vidar.recover_rollbacks()

    assert vidar.health()["rollback_publication_pending"] == 1


async def test_forseti_restart_fails_closed_when_arbitration_context_is_missing() -> None:
    state = InMemoryStateStore()
    await _forseti(state)._emit_arbitration_request(
        resource_id="vm-1",
        advice={"cost": "scale_down", "capacity": "scale_up"},
        correlation_id="corr-arb-missing",
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.on_typed_message(
        "object.arbitration-decision",
        {
            "producer_principal": "Odin",
            "correlation_id": "corr-arb-missing",
            "idempotency_key": "arb-decision:corr-arb-missing",
            "winning_domain": "cost",
            "losing_domains": ["capacity"],
            "margin": 1.0,
        },
    )

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["reason"] == "arbitration_unresolved"
    assert verdict["resource_id"] == "vm-1"


async def test_forseti_restart_expires_pending_cross_vertical_candidates() -> None:
    state = InMemoryStateStore()
    first = _forseti(state, now=_NOW)
    payload = _candidate(
        topic="object.cost-anomaly",
        correlation_id="corr-cross-timeout",
        action_type="ops.scale-in",
        utility=-0.5,
    )
    await first.on_typed_message("object.cost-anomaly", payload)
    bus = _bus()
    restarted = _forseti(state, bus, now=_NOW + timedelta(seconds=31))

    restored = await restarted.rehydrate()

    assert restored >= 1
    assert bus.messages_on("object.verdict")[-1].payload["reason"] == (
        "cross_vertical_candidate_timeout"
    )


async def test_forseti_durable_completed_candidate_set_suppresses_replay() -> None:
    state = InMemoryStateStore()
    await state.write_state_if_absent(
        "pantheon/forseti/cross-vertical-completed|corr-cross-done",
        {
            "kind": "cross_vertical_completed",
            "correlation_id": "corr-cross-done",
            "reason": "ready",
            "recorded_at": _NOW.isoformat(),
        },
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.on_typed_message(
        "object.cost-anomaly",
        _candidate(
            topic="object.cost-anomaly",
            correlation_id="corr-cross-done",
            action_type="ops.scale-in",
            utility=-0.5,
        ),
    )

    assert bus.messages_on("object.arbitration-request") == []


async def test_forseti_restart_restores_partial_domain_advice_join() -> None:
    state = InMemoryStateStore()
    await _forseti(state).on_typed_message(
        "object.cost-anomaly",
        {
            "producer_principal": "Njord",
            "correlation_id": "corr-domain-cost",
            "idempotency_key": "corr-domain-cost:cost",
            "resource_id": "vm-1",
            "recommendation": "scale_down",
            "impact": 0.2,
            "observed_at": _NOW.isoformat(),
        },
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.on_typed_message(
        "object.capacity-forecast",
        {
            "producer_principal": "Freyr",
            "correlation_id": "corr-domain-capacity",
            "idempotency_key": "corr-domain-capacity:capacity",
            "resource_id": "vm-1",
            "recommendation": "scale_up",
            "impact": 1.0,
            "observed_at": _NOW.isoformat(),
        },
    )

    assert bus.messages_on("object.arbitration-request")[-1].payload["resource_id"] == "vm-1"


async def test_forseti_restart_restores_revoked_rule_ceiling() -> None:
    state = InMemoryStateStore()
    await _forseti(state).on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "idempotency_key": "rule:revoke:disable-public",
            "correlation_id": "corr-rule",
            "action_type": "remediate.disable-public-access",
            "state": "revoked",
        },
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.judge(_event("corr-rule-event"))

    assert bus.messages_on("object.verdict")[-1].payload["risk_verdict"] == "hil"


async def test_forseti_restart_restores_detection_readiness_ceiling() -> None:
    state = InMemoryStateStore()
    await _forseti(state).on_typed_message(
        "object.drift",
        {
            "producer_principal": "Heimdall",
            "kind": "detection_readiness",
            "correlation_id": "corr-readiness",
            "idempotency_key": "corr-readiness:drift",
            "resource_id": "vm-1",
            "decision": "ready",
            "authority_ceiling": "shadow",
        },
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.judge(_event("corr-readiness-event"))

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "detection_readiness_ceiling"


async def test_forseti_no_rule_fold_survives_restart() -> None:
    state = InMemoryStateStore()
    first_bus = _bus()
    await _forseti(state, first_bus).judge(_event("corr-no-rule", "unknown_event"))
    second_bus = _bus()
    restarted = _forseti(state, second_bus)
    await restarted.rehydrate()

    await restarted.judge(_event("corr-no-rule", "unknown_event"))

    assert len(first_bus.messages_on("object.verdict")) == 1
    assert second_bus.messages_on("object.verdict") == []


async def test_forseti_durable_arbitration_completion_suppresses_old_decision() -> None:
    state = InMemoryStateStore()
    await state.write_state_if_absent(
        "pantheon/forseti/arbitration-completed|corr-arb-done",
        {
            "kind": "arbitration_completed",
            "correlation_id": "corr-arb-done",
            "outcome": "resolved",
            "recorded_at": _NOW.isoformat(),
        },
    )
    bus = _bus()
    restarted = _forseti(state, bus)
    await restarted.rehydrate()

    await restarted.on_typed_message(
        "object.arbitration-decision",
        {
            "producer_principal": "Odin",
            "correlation_id": "corr-arb-done",
            "idempotency_key": "arb-decision:corr-arb-done",
            "winning_domain": "cost",
            "losing_domains": ["capacity"],
            "margin": 1.0,
        },
    )

    assert bus.messages_on("object.verdict") == []


def test_every_published_payload_has_correlation_and_idempotency_key() -> None:
    for topic in INITIAL_VERTICAL_DOMAINS:
        assert topic
