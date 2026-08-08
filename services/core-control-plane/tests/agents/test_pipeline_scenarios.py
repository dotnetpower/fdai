"""Full-pipeline scenario measurement.

Wires the verdict -> dispatch -> approval path (Forseti -> Thor -> Var + Saga)
over an InMemoryBus and drives diverse events through it, then measures each
agent's ``behavior_snapshot()`` and asserts the cross-agent pipeline
invariants. Because InMemoryBus dispatches synchronously, one published
event drives the whole reaction chain, so a single scenario measures every
agent at once - the fastest way to surface an invariant break.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var


def _wire_pipeline(*, shadow: bool) -> tuple[InMemoryBus, Forseti, Thor, Var, Saga]:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti()
    forseti.bind_bus(bus)
    thor = Thor(shadow_by_default=shadow)
    thor.bind_bus(bus)
    var = Var()
    var.bind_bus(bus)
    saga = Saga()
    saga.bind_bus(bus)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)
    return bus, forseti, thor, var, saga


def _emit(bus: InMemoryBus, event: dict[str, Any]) -> None:
    asyncio.run(bus.publish("Huginn", "object.event", event))


def test_auto_scenario_shadow_never_mutates() -> None:
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(
        bus, {"event_type": "public_network_enabled", "correlation_id": "a1", "resource_id": "r1"}
    )
    fb, tb, vb = forseti.behavior_snapshot(), thor.behavior_snapshot(), var.behavior_snapshot()
    assert fb.get("verdict:auto") == 1
    assert tb.get("dispatch:auto") == 1
    # Shadow invariant: judged-and-logged, never a real execution.
    assert tb.get("executed:shadow") == 1
    assert tb.get("executed:success") is None
    assert tb.get("executed:failed") is None
    # Auto path never parks a HIL ticket.
    assert vb.get("ticket_pending") is None


def test_hil_scenario_parks_exactly_one_ticket() -> None:
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(bus, {"event_type": "unencrypted_disk", "correlation_id": "h1", "resource_id": "d1"})
    fb, tb, vb = forseti.behavior_snapshot(), thor.behavior_snapshot(), var.behavior_snapshot()
    assert fb.get("verdict:hil") == 1
    assert tb.get("dispatch:hil") == 1
    assert vb.get("ticket_pending") == 1
    # A HIL action is not executed until approved.
    assert tb.get("executed:shadow") is None


def test_deny_scenario_never_reaches_var() -> None:
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(
        bus,
        {"action_type": "remediate.delete-storage", "correlation_id": "d1", "resource_id": "s1"},
    )
    fb, tb, vb = forseti.behavior_snapshot(), thor.behavior_snapshot(), var.behavior_snapshot()
    assert fb.get("verdict:deny") == 1
    assert tb.get("dispatch:deny") == 1
    # Deny invariant: a denied action never dispatches, executes, or parks HIL.
    assert tb.get("dispatch:auto") is None
    assert tb.get("executed:shadow") is None
    assert vb.get("ticket_pending") is None


def test_mixed_scenario_stream_measures_whole_pipeline() -> None:
    """A stream of mixed events: the aggregate behaviour across agents is
    internally consistent (Forseti verdicts == Thor dispatches, HIL count ==
    Var tickets, deny never executes)."""
    bus, forseti, thor, var, saga = _wire_pipeline(shadow=True)
    events = [
        {"event_type": "public_network_enabled", "correlation_id": "m1", "resource_id": "ra"},
        {"event_type": "unencrypted_disk", "correlation_id": "m2", "resource_id": "rb"},
        {"event_type": "restart_needed", "correlation_id": "m3", "resource_id": "rc"},
        {"action_type": "remediate.delete-storage", "correlation_id": "m4", "resource_id": "rd"},
        {"event_type": "unencrypted_disk", "correlation_id": "m5", "resource_id": "re"},
    ]
    for e in events:
        _emit(bus, e)

    fb, tb, vb = forseti.behavior_snapshot(), thor.behavior_snapshot(), var.behavior_snapshot()
    verdicts = fb.get("verdict:auto", 0) + fb.get("verdict:hil", 0) + fb.get("verdict:deny", 0)
    dispatches = tb.get("dispatch:auto", 0) + tb.get("dispatch:hil", 0) + tb.get("dispatch:deny", 0)
    # Every verdict produced exactly one dispatch (no dropped or duplicated).
    assert verdicts == dispatches == 5
    # HIL verdicts (2x unencrypted_disk) parked exactly that many tickets.
    assert fb.get("verdict:hil") == 2
    assert vb.get("ticket_pending") == 2
    # Deny (1x delete-storage) never executed or parked.
    assert fb.get("verdict:deny") == 1
    assert tb.get("executed:shadow") == 2  # only the 2 auto actions (public, restart)
    # Saga audited every terminal outcome it saw (republished as audit-entry).
    assert len(bus.messages_on("object.audit-entry")) >= 2  # the 2 shadow successes


# ---------------------------------------------------------------------------
# Adversarial scenarios - measure robustness, not just the happy path
# ---------------------------------------------------------------------------


def test_adversarial_duplicate_verdict_dispatched_once() -> None:
    """The same event delivered twice: Thor dedups on correlation, so exactly
    one action runs and the second is measured as a duplicate."""
    bus, forseti, thor, _, _ = _wire_pipeline(shadow=True)
    event = {"event_type": "public_network_enabled", "correlation_id": "dup", "resource_id": "r1"}
    _emit(bus, dict(event))
    _emit(bus, dict(event))  # re-delivery
    tb = thor.behavior_snapshot()
    assert tb.get("dispatch:auto") == 1  # dispatched once
    assert tb.get("dispatch:duplicate") == 1  # second was a no-op
    assert tb.get("executed:shadow") == 1  # executed once, not twice


def test_adversarial_empty_payload_does_not_act() -> None:
    """A junk / empty event must abstain (measurably) and never dispatch."""
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(bus, {})
    _emit(bus, {"event_type": "nonsense", "correlation_id": "j1"})
    fb, tb, vb = forseti.behavior_snapshot(), thor.behavior_snapshot(), var.behavior_snapshot()
    assert fb.get("no_rule_match") == 2
    # Nothing downstream acted.
    assert tb == {}
    assert vb == {}


def test_adversarial_self_approval_blocked_and_measured() -> None:
    """An operator-initiated HIL action the operator then tries to self-approve
    is blocked, and the block is a measurable security signal."""
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(
        bus,
        {
            "action_type": "remediate.enable-encryption",
            "initiator_principal": "operator@example.com",
            "operator_initiated": True,
            "correlation_id": "sa1",
            "resource_id": "d1",
        },
    )
    assert var.behavior_snapshot().get("ticket_pending") == 1
    # The initiator cannot approve their own action.
    try:
        asyncio.run(var.decide("sa1", approver="operator@example.com", decision="approve"))
        raise AssertionError("self-approval should have raised")
    except ValueError:
        pass
    assert var.behavior_snapshot().get("self_approval_blocked") == 1
    # A distinct approver is still accepted (quorum 1 for a reversible action).
    approval = asyncio.run(var.decide("sa1", approver="approver@example.com", decision="approve"))
    assert approval is not None
    assert var.behavior_snapshot().get("approved") == 1


def test_adversarial_self_approval_retry_not_double_counted() -> None:
    """Retrying the same self-approval (treating the raised error as transient)
    must not inflate the security metric - it counts once per (id, approver)."""
    bus, forseti, thor, var, _ = _wire_pipeline(shadow=True)
    _emit(
        bus,
        {
            "action_type": "remediate.enable-encryption",
            "initiator_principal": "operator@example.com",
            "operator_initiated": True,
            "correlation_id": "retry1",
            "resource_id": "d1",
        },
    )
    for _ in range(3):  # same self-approval retried 3x
        try:
            asyncio.run(var.decide("retry1", approver="operator@example.com", decision="approve"))
        except ValueError:
            pass
    assert var.behavior_snapshot().get("self_approval_blocked") == 1  # counted once, not 3x


def test_pipeline_wiring_matches_agent_specs() -> None:
    """Scenario fidelity: every manual subscription in the harness is a topic
    the agent actually declares, so a green scenario cannot rest on a wiring
    the real PantheonRuntime would not create."""
    _, forseti, thor, var, saga = _wire_pipeline(shadow=True)
    assert "object.event" in forseti.spec.subscribes
    assert "object.verdict" in thor.spec.subscribes
    assert "object.approval" in thor.spec.subscribes
    assert "object.action-run" in var.spec.subscribes
    assert "object.action-run" in saga.spec.subscribes
    # And each agent publishes only what it owns (single-writer).
    assert "object.verdict" in forseti.spec.publishes
    assert "object.action-run" in thor.spec.publishes
    assert "object.approval" in var.spec.publishes
    assert "object.audit-entry" in saga.spec.publishes
