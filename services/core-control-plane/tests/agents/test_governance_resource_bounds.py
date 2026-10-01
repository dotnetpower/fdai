from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.adapters import InMemoryAuditChain
from fdai.agents._framework.audit_chain_rehydrate import StateStoreAuditChainAdapter
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.saga_handoff import HandoffIssueCheckpoint, SagaHandoffJournal
from fdai.agents._framework.var_decisions import (
    PendingHilTicket,
    PendingShadowReview,
    VarDecisionJournal,
    approval_for_ticket,
    final_approval_record,
)
from fdai.agents._framework.var_ticket_identity import approval_state_key
from fdai.agents.bragi import Bragi
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers.testing.state_store import InMemoryStateStore

N = 10_000


@dataclass
class _Published:
    principal: str
    topic: str
    payload: dict[str, Any]


class _Bus:
    def __init__(self) -> None:
        self.published: list[_Published] = []

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        assert payload.get("correlation_id")
        assert payload.get("idempotency_key")
        self.published.append(_Published(principal, topic, dict(payload)))


class _CountingStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.find_state_calls = 0
        self.read_state_page_calls = 0

    async def find_state(
        self,
        prefix: str,
        *,
        field: str,
        value: str,
    ) -> Mapping[str, Any] | None:
        self.find_state_calls += 1
        return await super().find_state(prefix, field=field, value=value)

    async def read_state_page(
        self,
        prefix: str,
        *,
        limit: int,
        offset: int = 0,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        self.read_state_page_calls += 1
        return await super().read_state_page(
            prefix,
            limit=limit,
            offset=offset,
            field=field,
            value=value,
        )


class _CountingList(list[Any]):
    def __init__(self, values: list[Any]) -> None:
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):  # type: ignore[no-untyped-def]
        self.iterations += 1
        return super().__iter__()


def _decision() -> RoutingDecision:
    return RoutingDecision(
        primary_agent="Bragi",
        scores={},
        tie_break=None,
        method="deterministic",
        semantic_score=None,
        semantic_margin=None,
        provider_status="not_configured",
    )


def _turn(index: int) -> Turn:
    return Turn(
        turn_index=index,
        question=f"question {index}",
        primary_agent="Bragi",
        answer={"trace_ref": f"corr-turn-{index}", "body": "ok"},
        decision=_decision(),
    )


def _ticket(index: int) -> PendingHilTicket:
    return PendingHilTicket(
        correlation_id=f"corr-var-{index}",
        action_type="ops.restart-service",
        resource_id=f"resource-{index}",
        quorum_required=1,
        action_id=f"action-{index}",
        idempotency_key=f"action-key-{index}",
        approvers=["approver@example.com"],
    )


@pytest.mark.asyncio
async def test_saga_rehydrate_resumes_from_verified_checkpoint() -> None:
    store = InMemoryStateStore()
    chain = StateStoreAuditChainAdapter(store)
    for index in range(1_500):
        await chain.append(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=f"corr-{index % 3}",
            payload={"correlation_id": f"corr-{index % 3}", "idempotency_key": f"audit-{index}"},
        )

    restarted = StateStoreAuditChainAdapter(store)
    await restarted.append(
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="corr-new",
        payload={"correlation_id": "corr-new", "idempotency_key": "audit-new"},
    )

    assert restarted.last_verify_visit_count <= 512


def test_saga_incremental_verify_and_correlation_index_are_bounded() -> None:
    chain = InMemoryAuditChain()
    for index in range(N):
        chain.append(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=f"corr-{index % 10}",
            payload={"correlation_id": f"corr-{index % 10}", "idempotency_key": f"audit-{index}"},
        )
    chain.verify()
    assert chain.last_verify_visit_count == N
    chain.verify()
    assert chain.last_verify_visit_count == 0
    chain.append(
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="corr-1",
        payload={"correlation_id": "corr-1", "idempotency_key": "audit-next"},
    )
    chain.verify()
    assert chain.last_verify_visit_count == 1

    counted_entries = _CountingList(chain.entries)
    chain.entries = counted_entries
    scoped = chain.entries_for_correlation("corr-1")
    assert scoped
    assert counted_entries.iterations == 0


@pytest.mark.asyncio
async def test_saga_audit_outbox_published_rows_compact_to_bounded_tombstones() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    saga.bind_bus(_Bus())  # type: ignore[arg-type]
    for index in range(N):
        payload = {
            "producer_principal": "Saga",
            "correlation_id": f"corr-outbox-{index}",
            "idempotency_key": f"audit-outbox-{index}",
            "audited_topic": "object.action-run",
        }
        await saga._publish_audit_entry_with_outbox(payload)

    rows, total = await store.read_state_page("pantheon/saga/audit-outbox/", limit=N + 1)
    assert total <= 6_024
    assert all("payload" not in row for row in rows if row.get("status") == "published")

    await saga._checkpoint_audit_outbox(
        {
            "producer_principal": "Saga",
            "correlation_id": "corr-outbox-9999",
            "idempotency_key": "audit-outbox-9999",
            "audited_topic": "object.action-run",
        }
    )


@pytest.mark.asyncio
async def test_saga_handoff_locks_and_journal_are_reclaimed() -> None:
    saga = Saga()
    for index in range(N):
        await saga._materialize_handoff({"escalation_id": f"esc-{index}"}, f"corr-{index}")
    assert saga._handoff_locks == {}

    journal = SagaHandoffJournal(local_store=saga.state_store, durable_store=None)
    for index in range(N):
        escalation_id = f"esc-complete-{index}"
        await journal.claim(
            escalation_id=escalation_id,
            fingerprint=f"fp-{index}",
            correlation_id=f"corr-{index}",
            operation_id=f"op-{index}",
        )
        await journal.write_checkpoint(
            escalation_id,
            HandoffIssueCheckpoint(
                fingerprint=f"fp-{index}",
                correlation_id=f"corr-{index}",
                issue_number=index + 1,
                created=True,
                occurrence_count=1,
            ),
        )
        await journal.complete(
            escalation_id,
            HandoffIssueCheckpoint(
                fingerprint=f"fp-{index}",
                correlation_id=f"corr-{index}",
                issue_number=index + 1,
                created=True,
                occurrence_count=1,
            ),
        )
    assert saga.state_store.scan("handoff_escalation_claims") == {}
    assert saga.state_store.scan("handoff_escalation_mutations") == {}
    assert len(saga.state_store.scan("handoff_escalation_receipts")) == N


@pytest.mark.asyncio
async def test_var_decision_and_shadow_review_locks_are_reclaimed() -> None:
    var = Var()
    for index in range(N):
        assert await var.decide(f"corr-missing-{index}", approver="approver", decision="approve")
    assert var._decision_locks == {}

    bus = _Bus()
    var.bind_bus(bus)  # type: ignore[arg-type]
    for index in range(N):
        correlation_id = f"corr-shadow-{index}"
        var._pending_shadow_reviews[correlation_id] = PendingShadowReview(
            correlation_id=correlation_id,
            action_type="ops.restart-service",
            observed_at="2028-01-01T00:00:00+00:00",
            policy_escape=False,
            initiator_principal="initiator@example.com",
        )
        await var.decide_shadow_review(correlation_id, reviewer="reviewer@example.com", agreed=True)
    assert var._shadow_review_locks == {}
    assert var._pending_shadow_reviews == {}


@pytest.mark.asyncio
async def test_var_recovery_uses_bounded_pages_not_find_state_scans() -> None:
    store = _CountingStore()
    journal = VarDecisionJournal(
        store,
        state_prefix="pantheon/var/approval",
        clock=lambda: datetime(2028, 1, 1, tzinfo=UTC),
    )
    for index in range(25):
        ticket = _ticket(index)
        await journal.record(
            state_key=approval_state_key(
                ticket.correlation_id,
                "decisions",
                ticket.action_run_identity,
            ),
            correlation_id=ticket.correlation_id,
            action_type=ticket.action_type,
            quorum_required=ticket.quorum_required,
            ticket_identity={
                "correlation_id": ticket.correlation_id,
                "action_type": ticket.action_type,
                "resource_id": ticket.resource_id,
                "quorum_required": ticket.quorum_required,
                "original_quorum_required": ticket.original_quorum_required,
                "effective_quorum_required": ticket.effective_quorum_required,
                "action_run_identity": ticket.action_run_identity,
                "action_id": ticket.action_id,
                "idempotency_key": ticket.idempotency_key,
                "rollback_contract": ticket.rollback_contract,
                "kind": ticket.kind,
                "params": {},
                "development_authority": None,
                "decision_case": None,
            },
            principal="approver@example.com",
            decision="approved",
        )
    var = Var(state_store=store, bus=_Bus())  # type: ignore[arg-type]
    finalized, published = await var.recover_approvals()
    assert (finalized, published) == (25, 25)
    assert store.find_state_calls == 0
    assert store.read_state_page_calls <= 5


@pytest.mark.asyncio
async def test_var_pending_final_publication_uses_page_reads() -> None:
    store = _CountingStore()
    for index in range(25):
        ticket = _ticket(index)
        approval = approval_for_ticket(ticket, state="approved")
        await store.write_state(
            approval_state_key(
                ticket.correlation_id,
                "final",
                ticket.action_run_identity,
            ),
            final_approval_record(approval, publication_status="pending", revision=1),
        )
    var = Var(state_store=store, bus=_Bus())  # type: ignore[arg-type]
    finalized, published = await var.recover_approvals()
    assert (finalized, published) == (0, 25)
    assert store.find_state_calls == 0
    assert store.read_state_page_calls <= 5


@pytest.mark.asyncio
async def test_bragi_turn_outbox_compacts_to_digest_tombstones_and_suppresses_duplicates() -> None:
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store)
    bragi.bind_bus(_Bus())  # type: ignore[arg-type]
    session = ConversationSession(session_id="session", user_id="operator")
    for index in range(N):
        payload = await bragi._checkpoint_turn_payload(session=session, turn=_turn(index))
        await bragi._publish_turn(payload)

    rows, total = await store.read_state_page("pantheon/bragi/turn-outbox/", limit=N + 1)
    assert total <= 6_024
    assert all("payload" not in row for row in rows if row.get("status") == "published")
    await bragi._checkpoint_turn_payload(session=session, turn=_turn(N - 1))


@pytest.mark.asyncio
async def test_bragi_progress_recovery_is_bounded_by_compaction() -> None:
    store = InMemoryStateStore()
    bragi = Bragi(state_store=store)
    for index in range(N):
        await bragi.on_typed_message(
            "object.verdict",
            {
                "correlation_id": f"corr-progress-{index}",
                "idempotency_key": f"verdict-{index}",
                "risk_verdict": "hil",
            },
        )
    _rows, total = await store.read_state_page("pantheon/bragi/progress/", limit=N + 1)
    assert total == 5_000

    restarted = Bragi(state_store=store)
    progress, published = await restarted.recover_state()
    assert progress == 5_000
    assert published == 0


@pytest.mark.asyncio
async def test_bragi_canonicalizes_turn_answer_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from fdai.agents._framework import bragi_publication

    calls = 0
    original = bragi_publication.canonical_json

    def counted(value: object) -> str:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(bragi_publication, "canonical_json", counted)
    bragi = Bragi(state_store=InMemoryStateStore())
    bragi.bind_bus(_Bus())  # type: ignore[arg-type]
    session = ConversationSession(session_id="session", user_id="operator")

    payload = await bragi._checkpoint_turn_payload(session=session, turn=_turn(0))
    await bragi._publish_turn(payload)

    assert calls == 1
