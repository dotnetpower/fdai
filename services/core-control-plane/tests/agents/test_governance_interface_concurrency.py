from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest
from fdai.agents._framework.adapters import (
    GitHubIssue,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
)
from fdai.agents._framework.bragi_publication import handoff_event_payload
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from .semantic_judgment_support import semantic_test_boundary


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), handler_timeout=None)


def _hil_payload(correlation_id: str) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:hil",
        "action_idempotency_key": f"{correlation_id}:hil",
        "action_id": f"action-{correlation_id}",
        "action_type": "ops.restart-service",
        "resource_id": f"resource-{correlation_id}",
        "state": "hil_pending",
        "quorum_required": 1,
        "initiator_principal": f"initiator-{correlation_id}@example.com",
        "rollback_contract": "state_forward_only",
        "params": {},
        "verdict": "hil",
    }


class _BlockingBus(InMemoryBus):
    def __init__(self, *, block_topics: set[str]) -> None:
        super().__init__(registry=load_pantheon(), handler_timeout=None)
        self.block_topics = block_topics
        self.entered: dict[str, asyncio.Event] = {}
        self.release: dict[str, asyncio.Event] = {}

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        await super().publish(principal, topic, payload)
        if topic in self.block_topics:
            self.entered.setdefault(topic, asyncio.Event()).set()
            await self.release.setdefault(topic, asyncio.Event()).wait()

    async def wait_for(self, topic: str) -> None:
        await self.entered.setdefault(topic, asyncio.Event()).wait()

    def unblock(self, topic: str) -> None:
        self.release.setdefault(topic, asyncio.Event()).set()


class _CountingIssueTracker(InMemoryGithubIssueAdapter):
    def __init__(self, *, block_first: bool = False) -> None:
        super().__init__()
        self.calls = 0
        self.block_first = block_first
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def create_or_comment_once(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        title: str,
        body: str,
    ) -> tuple[GitHubIssue, bool]:
        self.calls += 1
        if self.block_first and self.calls == 1:
            self.entered.set()
            await self.release.wait()
        return super().create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
        )


async def test_bragi_reserves_turn_indexes_by_arrival_before_slow_responder() -> None:
    first_can_answer = asyncio.Event()

    async def responder(question: str, _context: dict[str, Any]) -> dict[str, Any]:
        if "first" in question:
            await first_can_answer.wait()
        return {"answer": question, "facts": {}}

    bragi = Bragi(semantic_judgment=semantic_test_boundary())
    bragi.register_responder("Thor", responder)

    first = asyncio.create_task(
        bragi.ask(session_id="session-order", user_id="operator", question="Thor first")
    )
    await asyncio.sleep(0)
    second = await bragi.ask(
        session_id="session-order",
        user_id="operator",
        question="Thor second",
    )
    first_can_answer.set()
    first_turn = await first

    assert first_turn.turn_index == 0
    assert second.turn_index == 1


async def test_bragi_conversation_publish_does_not_block_same_session_turn_reservation() -> None:
    bus = _BlockingBus(block_topics={"object.conversation"})
    bragi = Bragi()
    bragi.bind_bus(bus)

    first = asyncio.create_task(
        bragi.ask(session_id="session-conversation", user_id="operator", question="unknown first")
    )
    await bus.wait_for("object.conversation")
    second = await bragi.ask(
        session_id="session-conversation",
        user_id="operator",
        question="unknown second",
    )

    assert second.turn_index == 1
    bus.unblock("object.conversation")
    assert (await first).turn_index == 0


async def test_bragi_handoff_publish_does_not_block_same_session_turn_reservation() -> None:
    bus = _BlockingBus(block_topics={"object.handoff-escalation"})
    bragi = Bragi()
    bragi.bind_bus(bus)

    first = asyncio.create_task(
        bragi.ask(
            session_id="session-handoff",
            user_id="operator",
            question="unknown first",
            materialize_handoff=True,
        )
    )
    await bus.wait_for("object.handoff-escalation")
    second = await bragi.ask(
        session_id="session-handoff",
        user_id="operator",
        question="unknown second",
        materialize_handoff=False,
    )

    assert second.turn_index == 1
    bus.unblock("object.handoff-escalation")
    assert (await first).turn_index == 0


async def test_bragi_turn_publish_marks_outbox_when_cancelled_during_receipt() -> None:
    store = InMemoryStateStore()
    bus = _bus()
    bragi = Bragi(state_store=store)
    bragi.bind_bus(bus)
    mark_started = asyncio.Event()
    release_mark = asyncio.Event()
    original = bragi._mark_turn_published  # noqa: SLF001

    async def slow_mark(payload: Mapping[str, Any]) -> None:
        mark_started.set()
        await release_mark.wait()
        await original(payload)

    bragi._mark_turn_published = slow_mark  # type: ignore[method-assign]  # noqa: SLF001
    task = asyncio.create_task(
        bragi.ask(session_id="session-cancel", user_id="operator", question="unknown")
    )
    await mark_started.wait()
    task.cancel()
    release_mark.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    restarted = Bragi(state_store=store)
    restarted.bind_bus(bus)
    assert await restarted.recover_state() == (0, 0)
    assert len(bus.messages_on("object.turn")) == 1


async def test_var_unrelated_decision_not_blocked_by_slow_authorizer() -> None:
    first_authorizer_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def authorizer(principal: str, _action_type: str) -> bool:
        if principal == "approver-a@example.com":
            first_authorizer_entered.set()
            await release_first.wait()
        return True

    bus = _bus()
    var = Var(bus=bus, approver_authorizer=authorizer)
    await var.on_typed_message("object.action-run", _hil_payload("ticket-a"))
    await var.on_typed_message("object.action-run", _hil_payload("ticket-b"))

    first = asyncio.create_task(
        var.decide("ticket-a", approver="approver-a@example.com", decision="approve")
    )
    await first_authorizer_entered.wait()
    second = await var.decide(
        "ticket-b",
        approver="approver-b@example.com",
        decision="approve",
    )
    release_first.set()

    assert second is not None and second["correlation_id"] == "ticket-b"
    assert (await first) is not None


async def test_var_final_publish_marks_outbox_when_cancelled_during_receipt() -> None:
    store = InMemoryStateStore()
    bus = _bus()
    var = Var(bus=bus, state_store=store)
    await var.on_typed_message("object.action-run", _hil_payload("ticket-cancel"))
    mark_started = asyncio.Event()
    release_mark = asyncio.Event()
    original = var._mark_approval_published  # noqa: SLF001

    async def slow_mark(approval: Mapping[str, Any]) -> None:
        mark_started.set()
        await release_mark.wait()
        await original(approval)

    var._mark_approval_published = slow_mark  # type: ignore[method-assign]  # noqa: SLF001
    task = asyncio.create_task(
        var.decide("ticket-cancel", approver="approver@example.com", decision="approve")
    )
    await mark_started.wait()
    task.cancel()
    release_mark.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    restarted = Var(bus=bus, state_store=store)
    assert await restarted.recover_approvals() == (0, 0)
    assert len(bus.messages_on("object.approval")) == 1


async def test_var_shadow_review_concurrent_reviewers_publish_once() -> None:
    bus = _BlockingBus(block_topics={"object.approval"})
    var = Var(bus=bus)
    await var.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "audited_topic": "object.action-run",
            "shadow_mode": True,
            "operator_reviewed": False,
            "shadow_observation_id": "shadow-concurrent",
            "correlation_id": "shadow-concurrent",
            "idempotency_key": "shadow-concurrent:audit",
            "action_type": "ops.restart-service",
            "observed_at": "2030-01-02T00:00:00+00:00",
            "policy_escape": False,
        },
    )

    first = asyncio.create_task(
        var.decide_shadow_review("shadow-concurrent", reviewer="a@example.com", agreed=True)
    )
    await bus.wait_for("object.approval")
    second = await var.decide_shadow_review(
        "shadow-concurrent",
        reviewer="b@example.com",
        agreed=False,
    )
    bus.unblock("object.approval")
    assert await first is not None
    assert second == {"state": "rejected", "reason": "missing_ticket"}
    assert len(bus.messages_on("object.approval")) == 1


async def test_var_recovery_does_not_duplicate_live_final_publication() -> None:
    store = InMemoryStateStore()
    bus = _BlockingBus(block_topics={"object.approval"})
    var = Var(bus=bus, state_store=store)
    await var.on_typed_message("object.action-run", _hil_payload("ticket-recovery"))

    live = asyncio.create_task(
        var.decide("ticket-recovery", approver="approver@example.com", decision="approve")
    )
    await bus.wait_for("object.approval")
    restarted = Var(bus=bus, state_store=store)
    assert await restarted.recover_approvals() == (0, 0)
    bus.unblock("object.approval")
    assert await live is not None
    assert len(bus.messages_on("object.approval")) == 1


async def test_saga_unrelated_handoff_not_blocked_by_slow_issue_tracker() -> None:
    tracker = _CountingIssueTracker(block_first=True)
    bus = _bus()
    saga = Saga(github=tracker)
    saga.bind_bus(bus)
    first = handoff_event_payload(
        session_id="session-1",
        question="unknown first",
        turn_index=0,
        reason="semantic_unavailable",
    )
    second = handoff_event_payload(
        session_id="session-2",
        question="unknown second",
        turn_index=0,
        reason="semantic_unavailable",
    )

    first_task = asyncio.create_task(saga.on_typed_message("object.handoff-escalation", first))
    await tracker.entered.wait()
    await saga.on_typed_message("object.handoff-escalation", second)
    tracker.release.set()
    await first_task

    assert len(bus.messages_on("object.issue")) == 2


async def test_saga_durable_fingerprint_claim_prevents_cross_replica_double_create() -> None:
    store = InMemoryStateStore()
    tracker = _CountingIssueTracker(block_first=True)
    first = Saga(durable_state_store=store, github=tracker)
    second = Saga(durable_state_store=store, github=tracker)
    fingerprint = "fingerprint-cross-replica"

    first_task = asyncio.create_task(
        first.escalate_to_github_issue(
            fingerprint=fingerprint,
            emitting_agent="Bragi",
            intent_category="semantic_unavailable",
            failure_reason_code="no_route",
            correlation_id="corr-a",
        )
    )
    await tracker.entered.wait()
    loser = await asyncio.gather(
        second.escalate_to_github_issue(
            fingerprint=fingerprint,
            emitting_agent="Bragi",
            intent_category="semantic_unavailable",
            failure_reason_code="no_route",
            correlation_id="corr-b",
        ),
        return_exceptions=True,
    )
    tracker.release.set()
    assert await first_task
    assert isinstance(loser[0], RuntimeError)
    assert tracker.calls == 1


async def test_saga_occurrence_count_cas_merges_concurrent_updates() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    fingerprint = "fingerprint-occurrence"
    await saga._put_durable_fingerprint(  # noqa: SLF001
        fingerprint,
        {
            "issue_number": 1,
            "occurrence_count": 1,
            "last_correlation_id": "corr-0",
            "open": True,
        },
    )

    await asyncio.gather(
        saga._mutate_github_issue(  # noqa: SLF001
            operation_id="handoff:one",
            fingerprint=fingerprint,
            emitting_agent="Bragi",
            intent_category="semantic_unavailable",
            failure_reason_code="no_route",
            correlation_id="corr-1",
        ),
        saga._mutate_github_issue(  # noqa: SLF001
            operation_id="handoff:two",
            fingerprint=fingerprint,
            emitting_agent="Bragi",
            intent_category="semantic_unavailable",
            failure_reason_code="no_route",
            correlation_id="corr-2",
        ),
    )

    stored = await saga._load_durable_fingerprint(fingerprint)  # noqa: SLF001
    assert stored is not None
    assert stored["occurrence_count"] == 3


async def test_saga_cancellation_after_issue_update_does_not_repeat_external_mutation() -> None:
    store = InMemoryStateStore()
    tracker = _CountingIssueTracker()
    saga = Saga(durable_state_store=store, github=tracker)
    write_started = asyncio.Event()
    release_write = asyncio.Event()
    original = saga._put_durable_fingerprint  # noqa: SLF001

    async def slow_write(fingerprint: str, value: dict[str, Any]) -> None:
        write_started.set()
        await release_write.wait()
        await original(fingerprint, value)

    saga._put_durable_fingerprint = slow_write  # type: ignore[method-assign]  # noqa: SLF001
    task = asyncio.create_task(
        saga.escalate_to_github_issue(
            fingerprint="fingerprint-cancel",
            emitting_agent="Bragi",
            intent_category="semantic_unavailable",
            failure_reason_code="no_route",
            correlation_id="corr-cancel",
        )
    )
    await write_started.wait()
    task.cancel()
    release_write.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    replay = await saga.escalate_to_github_issue(
        fingerprint="fingerprint-cancel",
        emitting_agent="Bragi",
        intent_category="semantic_unavailable",
        failure_reason_code="no_route",
        correlation_id="corr-cancel",
    )
    assert replay["issue_number"] == 1
    assert tracker.operation_results.keys() == {"handoff:fingerprint-cancel:corr-cancel"}


async def test_saga_audit_outbox_recovery_does_not_duplicate_live_publish() -> None:
    store = InMemoryStateStore()
    bus = _BlockingBus(block_topics={"object.audit-entry"})
    saga = Saga(audit_chain=InMemoryAuditChain(), durable_state_store=store)
    saga.bind_bus(bus)
    payload = {
        "producer_principal": "Saga",
        "correlation_id": "audit-race",
        "idempotency_key": "audit-race:key",
        "audited_topic": "object.action-run",
        "action_type": "ops.restart-service",
        "result": "success",
    }

    live = asyncio.create_task(saga._publish_audit_entry_with_outbox(deepcopy(payload)))  # noqa: SLF001
    await bus.wait_for("object.audit-entry")
    restarted = Saga(audit_chain=InMemoryAuditChain(), durable_state_store=store)
    restarted.bind_bus(bus)
    assert await restarted.recover_audit_outbox() == 0
    bus.unblock("object.audit-entry")
    await live
    assert len(bus.messages_on("object.audit-entry")) == 1
