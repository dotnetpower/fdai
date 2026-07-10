"""Wave 3 pipeline behavior tests."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents.bus import InMemoryBus
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.registry import load_pantheon
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar

# ---------------------------------------------------------------------------
# Huginn
# ---------------------------------------------------------------------------


def test_huginn_normalizes_and_dedups() -> None:
    huginn = Huginn()
    raw = {
        "id": "evt-1",
        "correlation_id": "corr-1",
        "resource_id": "vm-1",
        "resource_type": "compute",
        "event_type": "restart_needed",
        "attributes": {"reason": "healthcheck"},
    }
    first = asyncio.run(huginn.ingest(raw))
    second = asyncio.run(huginn.ingest(raw))
    assert first is not None
    assert first["event_type"] == "restart_needed"
    assert second is None  # dedup


def test_huginn_publishes_on_bound_bus() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "evt-x",
                "correlation_id": "c",
                "resource_id": "r",
                "event_type": "public_network_enabled",
            }
        )
    )
    events = bus.messages_on("object.event")
    assert len(events) == 1
    assert events[0].principal == "Huginn"


def test_huginn_requires_stable_key() -> None:
    huginn = Huginn()
    with pytest.raises(ValueError, match="missing idempotency_key"):
        asyncio.run(huginn.ingest({"resource_id": "r"}))


# ---------------------------------------------------------------------------
# Heimdall
# ---------------------------------------------------------------------------


def test_heimdall_emits_anomaly_on_threshold_burst() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    for _ in range(3):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {"resource_id": "vm-1", "event_type": "cpu_spike", "correlation_id": "c"},
            )
        )
    anomalies = bus.messages_on("object.anomaly")
    assert len(anomalies) == 1
    assert anomalies[0].payload["count_in_window"] == 3


def test_heimdall_no_anomaly_on_mixed_event_types() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    for et in ("a", "b", "c"):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {"resource_id": "vm-1", "event_type": et, "correlation_id": "c"},
            )
        )
    assert bus.messages_on("object.anomaly") == []


def test_heimdall_security_severity_high_on_irreversible() -> None:
    heimdall = Heimdall()
    asyncio.run(
        heimdall.on_typed_message(
            "object.security-event",
            {
                "initiator_principal": "guest@example.com",
                "attempted_action": "remediate.delete-storage",
                "severity_hint": "medium",
            },
        )
    )
    # on_typed_message returns None, so use direct call
    sev = asyncio.run(
        heimdall._maybe_classify_severity(
            {
                "initiator_principal": "guest@example.com",
                "attempted_action": "remediate.delete-storage",
                "severity_hint": "medium",
            }
        )
    )
    assert sev == "high"


def test_heimdall_security_severity_critical_on_pattern() -> None:
    heimdall = Heimdall()
    # Same user attempting 3 distinct actions => critical
    for action in ("a.b", "c.d", "e.f"):
        asyncio.run(
            heimdall._maybe_classify_severity(
                {
                    "initiator_principal": "attacker@example.com",
                    "attempted_action": action,
                    "severity_hint": "low",
                }
            )
        )
    # A follow-up attempt on any action should classify critical.
    final = asyncio.run(
        heimdall._maybe_classify_severity(
            {
                "initiator_principal": "attacker@example.com",
                "attempted_action": "a.b",
                "severity_hint": "low",
            }
        )
    )
    assert final == "critical"


# ---------------------------------------------------------------------------
# Forseti
# ---------------------------------------------------------------------------


def test_forseti_emits_verdict_auto_on_rule_match() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "c",
            },
        )
    )
    verdicts = bus.messages_on("object.verdict")
    assert len(verdicts) == 1
    assert verdicts[0].payload["risk_verdict"] == "auto"
    assert verdicts[0].payload["action_type"] == "remediate.disable-public-access"


def test_forseti_rbac_deny_emits_security_event() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    # guest@example.com is not allowed to run remediate.disable-public-access
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "c",
                "initiator_principal": "guest@example.com",
            },
        )
    )
    verdicts = bus.messages_on("object.verdict")
    security = bus.messages_on("object.security-event")
    assert verdicts[0].payload["risk_verdict"] == "deny"
    assert verdicts[0].payload["reason"] == "rbac_insufficient"
    assert len(security) == 1
    assert security[0].payload["event_type"] == "privilege_escalation_attempt"


def test_forseti_abstains_on_no_rule_match() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    result = asyncio.run(
        f.on_typed_message(
            "object.event",
            {"event_type": "unknown_thing", "correlation_id": "c"},
        )
    )
    assert result is None
    assert bus.messages_on("object.verdict") == []


# ---------------------------------------------------------------------------
# Thor / Var / Vidar
# ---------------------------------------------------------------------------


def test_thor_auto_verdict_executes_and_publishes_action_runs() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )
    )
    assert run.state == ActionRunState.SUCCEEDED
    action_runs = bus.messages_on("object.action-run")
    states_seen = [m.payload["state"] for m in action_runs]
    assert "verdicted" in states_seen
    assert "executing" in states_seen
    assert "succeeded" in states_seen


def test_thor_hil_verdict_waits_for_approval_then_executes() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)

    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-hil",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "disk-1",
            }
        )
    )
    assert thor.action_runs["c-hil"].state == ActionRunState.HIL_PENDING
    # Operator approves
    asyncio.run(var.decide("c-hil", approver="operator@example.com", decision="approve"))
    assert thor.action_runs["c-hil"].state == ActionRunState.SUCCEEDED


def test_thor_rejects_deny_verdict_without_execution() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-deny",
                "action_type": "remediate.delete-storage",
                "risk_verdict": "deny",
                "resource_id": "sa-x",
            }
        )
    )
    assert run.state == ActionRunState.DENY_DROPPED
    # No executing transition
    states = [m.payload["state"] for m in bus.messages_on("object.action-run")]
    assert "executing" not in states


def test_thor_degrades_to_shadow_when_saga_absent() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus, saga_available=False)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-2",
            }
        )
    )
    assert run.shadow_mode is True
    assert run.state == ActionRunState.SUCCEEDED
    assert run.outcome == "shadow_success"


def test_thor_triggers_vidar_rollback_on_failure() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    async def failing(_ctx):
        return False

    thor = Thor(bus=bus, executor=failing)
    vidar = Vidar(bus=bus)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)

    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-fail",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-3",
            }
        )
    )
    assert thor.action_runs["c-fail"].state == ActionRunState.ROLLED_BACK
    rollbacks = bus.messages_on("object.rollback")
    assert len(rollbacks) == 1


def test_thor_per_resource_mutex_prevents_concurrent_runs() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    # First dispatch: HIL, so it stays pending
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c1",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "vm-lock",
            }
        )
    )
    # Second dispatch on same resource returns the existing (pending) run
    run2 = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c2",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-lock",
            }
        )
    )
    # It should be the same object (existing pending), not a new one
    assert run2.correlation_id == "c1"


def test_var_quorum_two_approvers_required() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    # Simulate Thor emitting a hil_pending action_run with quorum_required=2
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c",
                "action_type": "remediate.delete-storage",
                "resource_id": "sa-1",
                "state": "hil_pending",
                "quorum_required": 2,
            },
        )
    )
    # First approver: no approval yet
    result1 = asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))
    assert result1 is None
    # Second approver reaches quorum
    result2 = asyncio.run(var.decide("c", approver="b@example.com", decision="approve"))
    assert result2 is not None
    assert result2["state"] == "approved"


def test_var_rejects_self_approval_twice() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c",
                "action_type": "x",
                "state": "hil_pending",
                "quorum_required": 2,
            },
        )
    )
    asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))
    with pytest.raises(ValueError, match="self-approve"):
        asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))


def _var_with_pending(
    correlation: str = "c-hil",
    *,
    quorum: int = 1,
    initiator: str | None = None,
) -> Var:
    reg = load_pantheon()
    var = Var(bus=InMemoryBus(registry=reg))
    payload: dict[str, object] = {
        "correlation_id": correlation,
        "action_type": "remediate.delete-storage",
        "state": "hil_pending",
        "quorum_required": quorum,
    }
    if initiator is not None:
        payload["initiator_principal"] = initiator
    asyncio.run(var.on_typed_message("object.action-run", payload))
    return var


def test_var_rejects_initiator_self_approval() -> None:
    # The principal that initiated the action can never approve it -
    # approval and initiation are distinct principals (pantheon invariant).
    var = _var_with_pending(quorum=2, initiator="op@example.com")
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(var.decide("c-hil", approver="op@example.com", decision="approve"))
    # A padded variant must not slip past the trimmed comparison.
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(var.decide("c-hil", approver="  op@example.com  ", decision="approve"))


def test_var_rejects_blank_approver() -> None:
    var = _var_with_pending()
    with pytest.raises(ValueError, match="non-empty principal"):
        asyncio.run(var.decide("c-hil", approver="   ", decision="approve"))


def test_var_unknown_decision_raises() -> None:
    var = _var_with_pending()
    with pytest.raises(ValueError, match="unknown decision"):
        asyncio.run(var.decide("c-hil", approver="a@example.com", decision="maybe"))


def test_var_reject_flow_emits_rejected_approval() -> None:
    var = _var_with_pending(quorum=2)
    result = asyncio.run(var.decide("c-hil", approver="a@example.com", decision="reject"))
    assert result is not None
    assert result["state"] == "rejected"
    # The ticket is consumed, so a second decide finds nothing.
    assert asyncio.run(var.decide("c-hil", approver="b@example.com", decision="approve")) is None


def test_var_decide_unknown_correlation_returns_none() -> None:
    var = _var_with_pending()
    assert (
        asyncio.run(var.decide("does-not-exist", approver="a@example.com", decision="approve"))
        is None
    )


def test_var_ingest_ignores_non_hil_and_duplicate_runs() -> None:
    var = _var_with_pending("c-dup")
    # Wrong topic is ignored.
    asyncio.run(
        var.on_typed_message("object.verdict", {"correlation_id": "z", "state": "hil_pending"})
    )
    # Right topic but not hil_pending is ignored.
    asyncio.run(
        var.on_typed_message(
            "object.action-run", {"correlation_id": "z", "state": "auto"}
        )
    )
    # Empty correlation is ignored.
    asyncio.run(
        var.on_typed_message(
            "object.action-run", {"correlation_id": "", "state": "hil_pending"}
        )
    )
    # A duplicate of an already-pending correlation does not overwrite it.
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {"correlation_id": "c-dup", "action_type": "other", "state": "hil_pending"},
        )
    )
    tickets = {t.correlation_id for t in var.pending_tickets()}
    assert tickets == {"c-dup"}
    assert var.pending_tickets()[0].action_type == "remediate.delete-storage"


def test_var_quorum_met_without_bus_still_consumes_ticket() -> None:
    # bus=None: the approval is not published but the ticket still
    # resolves and is removed from the pending queue.
    var = _var_with_pending("c-nobus", quorum=1)
    var.bus = None
    result = asyncio.run(var.decide("c-nobus", approver="a@example.com", decision="approve"))
    assert result is not None
    assert result["state"] == "approved"
    assert var.pending_tickets() == ()


def test_var_bind_bus_late_binds_the_publisher() -> None:
    # A composition root may construct Var before the bus exists and bind
    # it afterwards; the setter must take effect.
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=None)
    assert var.bus is None
    var.bind_bus(bus)
    assert var.bus is bus


def test_var_introspect_scoped_general_and_empty() -> None:
    var = _var_with_pending("c-one", quorum=2)
    # Naming a pending correlation scopes the answer to that ticket.
    scoped = asyncio.run(var.introspect("what is the status of c-one?", {}))
    assert scoped.facts["correlation_id"] == "c-one"
    assert scoped.facts["quorum_required"] == 2
    assert "c-one" in scoped.answer
    # No correlation named -> a general pending summary.
    general = asyncio.run(var.introspect("what is pending?", {}))
    assert general.facts["pending_hil"] == 1
    assert "pending" in general.answer
    # A fresh approver with no queue -> the empty-queue answer.
    empty = Var(bus=None)
    empty_result = asyncio.run(empty.introspect("anything to approve?", {}))
    assert empty_result.facts["pending_hil"] == 0
    assert "No HIL approvals pending" in empty_result.answer


def test_var_admin_card_dedup_updates_counter_in_place() -> None:
    var = Var(bus=None)
    payload = {
        "initiator_principal": "svc@example.com",
        "attempted_action": "delete-role-assignment",
        "severity": "high",
        "counter": 1,
    }
    first = asyncio.run(var.deliver_admin_card(payload))
    assert first.counter == 1
    assert len(var.admin_channel.cards) == 1
    # A repeat for the same (initiator, action) updates the counter in
    # place rather than posting a second card.
    second = asyncio.run(var.deliver_admin_card({**payload, "counter": 4}))
    assert second.counter == 4
    assert len(var.admin_channel.cards) == 1
    assert var.admin_channel.cards[-1].counter == 4



# ---------------------------------------------------------------------------
# End-to-end pipeline: Huginn -> Heimdall -> Forseti -> Thor -> Vidar -> Saga
# ---------------------------------------------------------------------------


def test_end_to_end_shadow_verdict_loop() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    huginn = Huginn(bus=bus)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    forseti = Forseti(bus=bus)
    thor = Thor(bus=bus)
    vidar = Vidar(bus=bus)
    saga = Saga()

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    for terminal in (
        "object.verdict",
        "object.action-run",
        "object.rollback",
        "object.approval",
        "object.security-event",
    ):
        bus.subscribe(terminal, "Saga", saga.on_typed_message)

    # Fire 10 restart_needed events - each matches Forseti's auto rule
    for i in range(10):
        asyncio.run(
            huginn.ingest(
                {
                    "id": f"evt-{i}",
                    "correlation_id": f"corr-{i}",
                    "resource_id": f"vm-{i}",
                    "event_type": "restart_needed",
                }
            )
        )

    verdicts = bus.messages_on("object.verdict")
    action_runs = bus.messages_on("object.action-run")

    # Every event that has a rule match must yield exactly one verdict.
    assert len(verdicts) == 10
    # Every verdict must produce (at least) verdicted/executing/succeeded states.
    assert len(action_runs) >= 30
    # Zero policy escapes: no state == 'failed' or 'deny_dropped'
    escaped = [a for a in action_runs if a.payload["state"] in ("failed", "deny_dropped")]
    assert escaped == []
    # Saga captured every terminal state
    saga.audit_chain.verify()
    assert len(saga.audit_chain.entries) >= len(verdicts) + len(action_runs)
