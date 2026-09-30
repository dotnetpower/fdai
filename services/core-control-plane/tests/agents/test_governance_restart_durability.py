from __future__ import annotations

from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.adapters import InMemoryAuditChain, InMemoryGithubIssueAdapter
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.provider_adapters import StateStoreAuditChainAdapter
from fdai.agents._framework.rate_limiter import RateLimiter
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.saga_handoff import HandoffIssueCheckpoint, SagaHandoffJournal
from fdai.agents.bragi import Bragi
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _action_run(correlation_id: str = "corr-action") -> dict[str, object]:
    payload: dict[str, object] = {
        "state": "hil_pending",
        "correlation_id": correlation_id,
        "idempotency_key": f"action:{correlation_id}",
        "action_idempotency_key": f"action:{correlation_id}",
        "action_id": f"action-{correlation_id}",
        "action_type": "ops.restart-service",
        "resource_id": "resource-1",
        "params": {"service": "api"},
        "quorum_required": 1,
        "initiator_principal": "operator@example.com",
        "rollback_contract": "state_forward_only",
        "verdict": "hil",
    }
    payload["action_run_identity"] = action_run_identity_digest(payload)
    return payload


async def test_var_rehydrates_action_document_and_shadow_tickets() -> None:
    store = InMemoryStateStore()
    var = Var(state_store=store)

    await var.on_typed_message("object.action-run", _action_run())
    await var.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "kind": "document_ingestion",
            "audited_topic": "object.verdict",
            "stage": "protection_check",
            "decision": "hil",
            "correlation_id": "corr-document",
            "idempotency_key": "document:corr-document",
            "document_id": "document-1",
            "upload_id": "upload-1",
        },
    )
    await var.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "audited_topic": "object.action-run",
            "shadow_mode": True,
            "operator_reviewed": False,
            "shadow_observation_id": "shadow-1",
            "correlation_id": "corr-shadow",
            "idempotency_key": "shadow:corr-shadow",
            "action_type": "ops.restart-service",
            "observed_at": "2028-01-02T00:00:00+00:00",
            "policy_escape": False,
        },
    )

    restarted = Var(state_store=store)
    await restarted.recover_approvals()

    tickets = {ticket.correlation_id: ticket for ticket in restarted.pending_tickets()}
    assert "corr-action" in tickets
    assert tickets["corr-document"].document_id == "document-1"
    assert tickets["corr-document"].upload_id == "upload-1"
    assert restarted.pending_shadow_reviews()[0].correlation_id == "shadow-1"


async def test_var_durable_ticket_survives_projection_overflow_and_final_evidence() -> None:
    store = InMemoryStateStore()
    var = Var(state_store=store)
    original_cap = var._MAX_PENDING
    var._MAX_PENDING = 1
    await var.on_typed_message("object.action-run", _action_run("oldest"))
    await var.on_typed_message("object.action-run", _action_run("newest"))

    restarted = Var(state_store=store)
    restarted._MAX_PENDING = original_cap
    assert await restarted.decide("oldest", approver="approver@example.com", decision="approve")
    assert restarted.conversation_evidence_available({})


async def test_odin_replays_original_arbitration_decision_after_restart() -> None:
    store = InMemoryStateStore()
    bus = _bus()
    odin = Odin(bus=bus, state_store=store, weights={"cost": 10.0, "capacity": 1.0})
    request = {
        "correlation_id": "arb-1",
        "idempotency_key": "arbitration:arb-1",
        "domains_in_conflict": ["cost", "capacity"],
        "impacts": {"cost": 1, "capacity": 1},
        "resource_id": "resource-1",
    }

    first = await odin.arbitrate(request)
    restarted = Odin(bus=bus, state_store=store, weights={"cost": 1.0, "capacity": 10.0})
    replay = await restarted.arbitrate(request)

    assert first.winning_domain == "cost"
    assert replay == first
    assert bus.messages_on("object.arbitration-decision")[-1].payload["winning_domain"] == "cost"
    result = await restarted.introspect("portfolio", {})
    assert result.facts["portfolio_window"] == "process_local_since_start"


async def test_bragi_turn_index_outbox_and_progress_recover_after_restart() -> None:
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store)
    await bragi.ask(session_id="session-1", user_id="operator", question="unknown one")
    await bragi.on_typed_message(
        "object.verdict",
        {
            "correlation_id": "corr-progress",
            "idempotency_key": "verdict:corr-progress",
            "risk_verdict": "hil",
        },
    )

    bus = _bus()
    restarted = Bragi(state_store=store)
    restarted.bind_bus(bus)
    progress, published = await restarted.recover_state()
    second = await restarted.ask(
        session_id="session-1",
        user_id="operator",
        question="unknown two",
    )

    assert progress == 1
    assert published == 1
    assert second.turn_index == 1
    assert restarted.progress_for("corr-progress")
    assert [message.payload["turn_index"] for message in bus.messages_on("object.turn")] == [0, 1]


async def test_saga_audit_outbox_republishes_after_restart() -> None:
    store = InMemoryStateStore()
    saga = Saga(audit_chain=InMemoryAuditChain(), durable_state_store=store)
    await saga.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": "corr-run",
            "idempotency_key": "run:corr-run",
            "state": "succeeded",
            "action_type": "ops.restart-service",
            "resource_id": "resource-1",
            "terminal_at": "2028-01-02T00:00:00+00:00",
        },
    )

    bus = _bus()
    restarted = Saga(audit_chain=InMemoryAuditChain(), durable_state_store=store)
    restarted.bind_bus(bus)
    assert await restarted.recover_audit_outbox() == 1
    assert bus.messages_on("object.audit-entry")[0].payload["audited_topic"] == "object.action-run"


async def test_saga_handoff_checkpoint_cas_rejects_regression() -> None:
    store = InMemoryStateStore()
    journal = SagaHandoffJournal(
        local_store=Saga().state_store,
        durable_store=store,
    )
    published = HandoffIssueCheckpoint(
        fingerprint="fp-1",
        correlation_id="corr-1",
        issue_number=1,
        created=True,
        occurrence_count=1,
        audit_recorded=True,
        published=True,
    )
    stale = HandoffIssueCheckpoint(
        fingerprint="fp-1",
        correlation_id="corr-1",
        issue_number=1,
        created=True,
        occurrence_count=1,
    )
    await journal.write_checkpoint("esc-1", published)
    await journal.write_checkpoint("esc-1", stale)
    recovered = await journal.read_checkpoint("esc-1")
    assert recovered is not None
    assert recovered.published is True
    assert recovered.audit_recorded is True


async def test_saga_issue_fingerprint_index_uses_durable_store_after_restart() -> None:
    store = InMemoryStateStore()
    first_github = InMemoryGithubIssueAdapter()
    first = Saga(durable_state_store=store, github=first_github)
    result = await first.escalate_to_github_issue(
        fingerprint="fp-1",
        emitting_agent="Bragi",
        intent_category="semantic_unavailable",
        failure_reason_code="no_route",
        correlation_id="corr-1",
    )
    second_github = InMemoryGithubIssueAdapter()
    restarted = Saga(durable_state_store=store, github=second_github)
    replay = await restarted.escalate_to_github_issue(
        fingerprint="fp-1",
        emitting_agent="Bragi",
        intent_category="semantic_unavailable",
        failure_reason_code="no_route",
        correlation_id="corr-2",
    )

    assert result["issue_number"] == replay["issue_number"]
    assert second_github.issues == {}


async def test_state_store_audit_chain_adapter_continues_hash_chain_after_restart() -> None:
    store = InMemoryStateStore()
    first = StateStoreAuditChainAdapter(store)
    entry1 = await first.append(
        principal="Saga",
        topic="object.action-run",
        correlation_id="corr-1",
        payload={"correlation_id": "corr-1", "idempotency_key": "audit:corr-1"},
    )

    restarted = StateStoreAuditChainAdapter(store)
    entry2 = await restarted.append(
        principal="Saga",
        topic="object.action-run",
        correlation_id="corr-2",
        payload={"correlation_id": "corr-2", "idempotency_key": "audit:corr-2"},
    )

    assert entry2.seq == 1
    assert entry2.prev_hash == entry1.entry_hash


def test_rate_limiter_retains_budget_after_restart() -> None:
    store = InMemoryStateStore()
    now = 1000.0
    first = RateLimiter(
        per_minute=10, per_hour=2, now=lambda: now, state_store=store, scope="Norns"
    )
    assert first.allow()
    assert first.allow()
    restarted = RateLimiter(
        per_minute=10,
        per_hour=2,
        now=lambda: now + 1,
        state_store=store,
        scope="Norns",
    )
    assert not restarted.allow()
    after_window = RateLimiter(
        per_minute=10,
        per_hour=2,
        now=lambda: now + 3601,
        state_store=store,
        scope="Norns",
    )
    assert after_window.allow()


async def test_ordered_poison_halt_survives_restart_until_explicit_clear() -> None:
    provider = InMemoryEventBus()
    store = InMemoryStateStore()
    registry = load_pantheon()
    payload = {
        "producer_principal": "Thor",
        "correlation_id": "corr-1",
        "idempotency_key": "run:corr-1",
        "resource_id": "resource-1",
        "state": "failed",
    }
    await provider.publish("object.action-run", "resource-1", payload)

    async def failing_handler(_topic: str, _payload: dict[str, object]) -> None:
        raise RuntimeError("poison")

    bridge = EventBusBridge(
        provider=provider,
        registry=registry,
        halt_state_store=store,
        dead_letter_retry_backoff=0.0,
    )
    bridge.subscribe("object.action-run", "Var", failing_handler)
    await bridge.run()
    assert bridge.snapshot()["consumer_states"]["Var:object.action-run"] == "halted"

    await provider.publish(
        "object.action-run",
        "resource-1",
        {**payload, "correlation_id": "corr-2", "idempotency_key": "run:corr-2"},
    )
    seen: list[str] = []

    async def recording_handler(_topic: str, delivered: dict[str, object]) -> None:
        seen.append(str(delivered["correlation_id"]))

    restarted = EventBusBridge(provider=provider, registry=registry, halt_state_store=store)
    restarted.subscribe("object.action-run", "Var", recording_handler)
    await restarted.run()
    assert seen == []
    assert restarted.snapshot()["consumer_states"]["Var:object.action-run"] == "halted"

    assert await restarted.clear_ordered_poison_halt(topic="object.action-run", agent_name="Var")
    cleared = EventBusBridge(provider=provider, registry=registry, halt_state_store=store)
    cleared.subscribe("object.action-run", "Var", recording_handler)
    await cleared.run()
    assert "corr-2" in seen
