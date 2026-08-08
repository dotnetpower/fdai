"""End-to-end: a chat command re-enters the typed pipeline (agent-pantheon.md 7.7).

Proves the conversational-port contract the operator asked for: a request that
Thor could act on is NOT sent to Thor directly - Bragi turns it into an
ActionProposal (initiator = operator), Forseti judges it, Var approves a
high-risk one, and only then does Thor execute (shadow-first). RBAC rejects a
request the operator's principal is not allowed to make, and the initiator can
never approve their own action.

The bus dispatches synchronously, so the whole chain resolves inside
``bragi.ask`` / ``var.decide``.
"""

from __future__ import annotations

import asyncio

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var

_OPERATOR = "operator@example.com"  # allowed everything except delete-storage
_GUEST = "guest@example.com"  # allowed only ops.restart-service
_APPROVER = "approver@example.com"


class _Harness:
    def __init__(self) -> None:
        reg = load_pantheon()
        self.bus = InMemoryBus(registry=reg)
        self.huginn = Huginn(bus=self.bus)
        self.forseti = Forseti(bus=self.bus)
        # Shadow-first: mirror the runtime default so an 'auto' verdict is
        # judged-and-logged, never a live mutation, until an explicit promotion.
        self.thor = Thor(bus=self.bus, shadow_by_default=True)
        self.var = Var(bus=self.bus)
        self.bragi = Bragi()
        # Wire the conversational-port entry: Bragi submits proposals through
        # Huginn (sole writer of object.event). Bragi never publishes / executes.
        self.bragi.register_proposal_sink(self.huginn.ingest)
        self.bus.subscribe("object.event", "Forseti", self.forseti.on_typed_message)
        self.bus.subscribe("object.verdict", "Thor", self.thor.on_typed_message)
        self.bus.subscribe("object.verdict", "Bragi", self.bragi.on_typed_message)
        self.bus.subscribe("object.action-run", "Var", self.var.on_typed_message)
        self.bus.subscribe("object.action-run", "Bragi", self.bragi.on_typed_message)
        self.bus.subscribe("object.approval", "Thor", self.thor.on_typed_message)

    def ask(self, question: str, *, user: str = _OPERATOR, role: str | None = None):
        return asyncio.run(
            self.bragi.ask(session_id="s1", user_id=user, question=question, initiator_role=role)
        )

    def bragi_published(self) -> list:
        return [m for m in self.bus.published if m.principal == "Bragi"]


def test_auto_action_submitted_judged_and_shadow_executed() -> None:
    h = _Harness()
    turn = h.ask("restart svc-1 now")
    answer = turn.answer
    # Bragi submitted the proposal (did NOT answer or execute it).
    assert answer["answer"] is None
    assert answer["submitted"] is True
    assert answer["action_type"] == "ops.restart-service"
    corr = answer["correlation_id"]

    # Forseti judged auto; Thor executed in shadow (judged-and-logged only).
    run = h.thor.action_runs[corr]
    assert run.verdict == "auto"
    assert run.shadow_mode is True
    assert run.state == ActionRunState.SUCCEEDED
    assert run.outcome == "shadow_success"

    # Bragi NEVER published or executed - it only rendered progress (7.7).
    assert h.bragi_published() == []
    assert len(h.bragi.progress_for(corr)) >= 2


def test_hil_action_waits_for_a_different_approver_then_executes() -> None:
    h = _Harness()
    turn = h.ask("encrypt disk-1")
    corr = turn.answer["correlation_id"]
    assert h.thor.action_runs[corr].state == ActionRunState.HIL_PENDING

    # A DIFFERENT principal approves -> Thor executes (shadow).
    asyncio.run(h.var.decide(corr, approver=_APPROVER, decision="approve"))
    assert h.thor.action_runs[corr].state == ActionRunState.SUCCEEDED
    assert h.bragi_published() == []


def test_initiator_cannot_self_approve() -> None:
    h = _Harness()
    turn = h.ask("encrypt disk-1")
    corr = turn.answer["correlation_id"]
    assert h.thor.action_runs[corr].state == ActionRunState.HIL_PENDING
    # The operator who initiated the action may not approve it.
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(h.var.decide(corr, approver=_OPERATOR, decision="approve"))
    # Still pending - not executed.
    assert h.thor.action_runs[corr].state == ActionRunState.HIL_PENDING


def test_rbac_denies_request_and_raises_security_event() -> None:
    h = _Harness()
    # guest is not allowed to run remediate.enable-encryption.
    turn = h.ask("encrypt disk-1", user=_GUEST)
    corr = turn.answer["correlation_id"]
    verdicts = h.bus.messages_on("object.verdict")
    security = h.bus.messages_on("object.security-event")
    assert verdicts[0].payload["risk_verdict"] == "deny"
    assert verdicts[0].payload["reason"] == "rbac_insufficient"
    assert len(security) == 1
    assert security[0].payload["event_type"] == "privilege_escalation_attempt"
    # Denied -> dropped, never executed.
    assert h.thor.action_runs[corr].state == ActionRunState.DENY_DROPPED
    states = [m.payload["state"] for m in h.bus.messages_on("object.action-run")]
    assert "executing" not in states
    assert h.bragi_published() == []


def test_unmapped_command_abstains_without_submitting() -> None:
    h = _Harness()
    # 'provision' is a command verb but maps to no ActionType -> abstain.
    turn = h.ask("provision a new cluster")
    assert turn.answer["submitted"] is False
    assert turn.answer["abstain_reason"] == "unmapped_action_intent"
    # Nothing entered the pipeline.
    assert h.bus.messages_on("object.event") == []
    assert h.bus.messages_on("object.verdict") == []


def test_question_is_not_treated_as_an_action() -> None:
    h = _Harness()
    # An interrogative routes to introspection, never the action pipeline.
    turn = h.ask("what is the action status")
    assert turn.answer.get("submitted") is None
    assert h.bus.messages_on("object.event") == []


def test_reader_role_is_refused_at_entry_before_the_pipeline() -> None:
    h = _Harness()
    # A Reader cannot submit any action - refused before it enters the pipeline.
    turn = h.ask("restart svc-1 now", role="Reader")
    assert turn.answer["submitted"] is False
    assert turn.answer["abstain_reason"] == "rbac_role_floor"
    assert turn.answer["required_role"] == "Contributor"
    # Nothing entered the pipeline; nothing executed.
    assert h.bus.messages_on("object.event") == []
    assert h.bus.messages_on("object.verdict") == []


def test_break_glass_cannot_submit_a_normal_action() -> None:
    # BreakGlass is hard-isolated (NOT a superset of Owner) and does NOT carry
    # author-draft-pr, so the HTTP console-action gate refuses it. The
    # conversational entry gate MUST agree - a linear role rank that treats
    # BreakGlass as "above Owner" wrongly let it through (critique #8).
    h = _Harness()
    turn = h.ask("restart svc-1 now", role="BreakGlass")
    assert turn.answer["submitted"] is False
    assert turn.answer["abstain_reason"] == "rbac_role_floor"
    assert h.bus.messages_on("object.event") == []


@pytest.mark.parametrize(
    ("role", "expect_submit"),
    [
        ("Reader", False),
        ("Contributor", True),
        ("Approver", True),
        ("Owner", True),
        ("BreakGlass", False),
        ("not-a-role", False),
    ],
)
def test_entry_gate_agrees_with_capability_matrix(role: str, expect_submit: bool) -> None:
    # Drift guard: the conversational entry gate MUST admit exactly the roles
    # the canonical capability matrix grants author-draft-pr, so it can never
    # diverge from the HTTP console-action gate (critique #8).
    h = _Harness()
    turn = h.ask("restart svc-1 now", role=role)
    assert turn.answer["submitted"] is expect_submit
    if not expect_submit:
        assert turn.answer["abstain_reason"] == "rbac_role_floor"


def test_contributor_role_may_submit_an_action() -> None:
    h = _Harness()
    turn = h.ask("restart svc-1 now", role="Contributor")
    assert turn.answer["submitted"] is True
    corr = turn.answer["correlation_id"]
    assert h.thor.action_runs[corr].state == ActionRunState.SUCCEEDED


# ---------------------------------------------------------------------------
# Hardening: forged-signal / spoofing defenses
# ---------------------------------------------------------------------------


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def test_forged_external_signal_cannot_carry_operator_fields() -> None:
    # An external / rule-fired signal on the ingress topic that includes
    # operator-proposal keys must NOT have them honored: only an explicit
    # event_type == "operator_request" is trusted (agent-pantheon.md 7.7).
    bus = _bus()
    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "evt-forged",
                "correlation_id": "c-forged",
                "event_type": "anomaly",  # not an operator request
                "initiator_principal": "attacker@evil",
                "action_type": "remediate.delete-storage",
                "operator_initiated": True,
            }
        )
    )
    published = bus.messages_on("object.event")[0].payload
    assert "action_type" not in published
    assert "initiator_principal" not in published
    assert "operator_initiated" not in published


def test_operator_request_honors_operator_fields_with_strict_bool() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "evt-op",
                "correlation_id": "c-op",
                "event_type": "operator_request",
                "initiator_principal": "operator@example.com",
                "action_type": "ops.restart-service",
                # A forged truthy string must be coerced to a strict bool.
                "operator_initiated": "false",
                "workflow_action": {
                    "process_id": "process-1",
                    "step_id": "restart",
                    "proposal_ref": "proposal-1",
                },
            }
        )
    )
    published = bus.messages_on("object.event")[0].payload
    assert published["action_type"] == "ops.restart-service"
    assert published["operator_initiated"] is False
    assert published["workflow_action"]["process_id"] == "process-1"


def test_forseti_operator_fail_closed_requires_strict_true() -> None:
    # A non-True operator_initiated must not trip the operator fail-closed deny
    # path; the action is judged by risk only (defense in depth with H1).
    bus = _bus()
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.judge(
            {
                "event_type": "operator_request",
                "action_type": "ops.restart-service",
                "operator_initiated": "true",  # string, not the bool True
                "initiator_principal": "ghost@nowhere",
                "correlation_id": "c-strict",
            }
        )
    )
    verdicts = bus.messages_on("object.verdict")
    assert verdicts[0].payload["risk_verdict"] == "auto"
    assert bus.messages_on("object.security-event") == []


def test_forseti_preserves_workflow_lineage_on_verdict() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)
    workflow_action = {
        "process_id": "process-1",
        "step_id": "restart",
        "proposal_ref": "proposal-1",
    }

    verdict = asyncio.run(
        forseti.judge(
            {
                "event_type": "operator_request",
                "action_type": "ops.restart-service",
                "operator_initiated": False,
                "correlation_id": "c-workflow",
                "workflow_action": workflow_action,
            }
        )
    )

    assert verdict["workflow_action"] == workflow_action


def test_var_rejects_blank_approver_and_trims_self_approval() -> None:
    bus = _bus()
    var = Var(bus=bus)
    # Seed a pending HIL ticket carrying the operator initiator.
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c-hil",
                "action_type": "ops.failover-primary",
                "state": "hil_pending",
                "initiator_principal": "operator@example.com",
            },
        )
    )
    # A blank approver is refused.
    with pytest.raises(ValueError, match="non-empty principal"):
        asyncio.run(var.decide("c-hil", approver="   ", decision="approve"))
    # A whitespace-padded self-approval is still caught (trimmed compare).
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(var.decide("c-hil", approver="  operator@example.com  ", decision="approve"))


# ---------------------------------------------------------------------------
# Hardening pass 2: idempotency, quorum floor, ingress bounds, leak caps
# ---------------------------------------------------------------------------


def test_thor_dispatch_verdict_is_idempotent_per_correlation() -> None:
    # At-least-once delivery: a re-delivered verdict for a correlation already
    # dispatched must be a no-op, never a second execution.
    bus = _bus()
    calls: list[dict] = []

    async def exec_fn(ctx: dict) -> bool:
        calls.append(ctx)
        return True

    thor = Thor(bus=bus, executor=exec_fn)  # enforce (not shadow) -> real exec
    verdict = {
        "correlation_id": "c-idem",
        "action_type": "ops.restart-service",
        "risk_verdict": "auto",
        "resource_id": "vm-1",
    }
    run1 = asyncio.run(thor.dispatch_verdict(verdict))
    run2 = asyncio.run(thor.dispatch_verdict(verdict))
    assert run1 is run2
    assert len(calls) == 1  # executed once despite the duplicate verdict


def test_var_clamps_quorum_to_a_floor_of_one() -> None:
    bus = _bus()
    var = Var(bus=bus)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c-q",
                "action_type": "ops.restart-service",
                "state": "hil_pending",
                "quorum_required": 0,  # forged / malformed downgrade
                "initiator_principal": "op@example.com",
            },
        )
    )
    assert var._pending["c-q"].quorum_required == 1
    result = asyncio.run(var.decide("c-q", approver="approver@example.com", decision="approve"))
    assert result is not None
    assert result["state"] == "approved"


def test_huginn_bounds_oversized_ingress_fields() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "e-big",
                "event_type": "operator_request",
                "action_type": "x" * 5_000,
                "initiator_principal": "op@example.com",
                "operator_initiated": True,
                "resource_id": "r" * 5_000,
            }
        )
    )
    payload = bus.messages_on("object.event")[0].payload
    assert len(payload["action_type"]) <= 512
    assert len(payload["resource_id"]) <= 512


def test_var_pending_map_is_bounded() -> None:
    bus = _bus()
    var = Var(bus=bus)
    var._MAX_PENDING = 2  # instance override of the class cap
    for i in range(5):
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                {
                    "correlation_id": f"c-{i}",
                    "action_type": "ops.restart-service",
                    "state": "hil_pending",
                    "initiator_principal": "op@example.com",
                },
            )
        )
    assert len(var._pending) == 2


def test_bragi_progress_map_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from fdai.agents import bragi as bragi_mod

    monkeypatch.setattr(bragi_mod, "_MAX_PROGRESS_KEYS", 2)
    b = Bragi()
    for i in range(5):
        asyncio.run(
            b.on_typed_message(
                "object.verdict", {"correlation_id": f"c-{i}", "risk_verdict": "auto"}
            )
        )
    assert len(b._progress) == 2


def test_bragi_progress_dedups_redelivered_step() -> None:
    # At-least-once delivery can redeliver the same lifecycle record; the
    # operator must not see a duplicated step.
    b = Bragi()
    record = {"correlation_id": "c-dup", "state": "executing", "action_type": "ops.x"}
    asyncio.run(b.on_typed_message("object.action-run", dict(record)))
    asyncio.run(b.on_typed_message("object.action-run", dict(record)))
    assert len(b.progress_for("c-dup")) == 1


def test_bragi_progress_list_length_is_bounded() -> None:
    # A redelivery / retry burst of DISTINCT states must not grow one
    # conversation's progress log without limit.
    from fdai.agents.bragi import _MAX_PROGRESS_STEPS

    b = Bragi()
    for i in range(_MAX_PROGRESS_STEPS + 50):
        asyncio.run(
            b.on_typed_message(
                "object.action-run",
                {"correlation_id": "c-long", "state": f"s{i}", "action_type": "ops.x"},
            )
        )
    assert len(b.progress_for("c-long")) == _MAX_PROGRESS_STEPS


def test_bragi_session_map_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from fdai.agents import bragi as bragi_mod

    monkeypatch.setattr(bragi_mod, "_MAX_SESSIONS", 2)
    b = Bragi()
    for i in range(5):
        asyncio.run(b.ask(session_id=f"s-{i}", user_id="u", question="what is the action status"))
    assert len(b._sessions) <= 2
