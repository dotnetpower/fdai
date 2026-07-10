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

from fdai.agents.bragi import Bragi
from fdai.agents.bus import InMemoryBus
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.registry import load_pantheon
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
            self.bragi.ask(
                session_id="s1", user_id=user, question=question, initiator_role=role
            )
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


def test_contributor_role_may_submit_an_action() -> None:
    h = _Harness()
    turn = h.ask("restart svc-1 now", role="Contributor")
    assert turn.answer["submitted"] is True
    corr = turn.answer["correlation_id"]
    assert h.thor.action_runs[corr].state == ActionRunState.SUCCEEDED

