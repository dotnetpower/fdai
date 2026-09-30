from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.learning import RuleCandidateHint
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 30, tzinfo=UTC)


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), isolate_handlers=False)


def _investigation_candidate() -> dict[str, object]:
    return {
        "producer_principal": "Norns",
        "correlation_id": "investigation-corr",
        "idempotency_key": "rule-candidate:investigation:1",
        "source_signal": "investigation_strategy_comparison_cohort",
        "evidence": {
            "candidate_digest": "sha256:" + "1" * 64,
            "sample_size": 2,
        },
        "proposed_by": "Norns",
        "proposal_kind": "revision",
        "target_rule_id": "investigation.selector.restart",
    }


async def test_mimir_rule_status_survives_restart_without_resurrecting_retired_rule() -> None:
    store = InMemoryStateStore()
    first = Mimir(governance_state_store=store)

    first.promote(
        "rules.restart",
        source="manual",
        reviewed_change_ref="catalog-pr:https://git.example.com/fdai/control-plane/pull/1@sha256:"
        + "a" * 64,
        updated_at=_NOW.isoformat(),
    )
    first.revoke("rules.restart", updated_at=_NOW.isoformat())
    await first.drain_governance_writes()

    restarted = Mimir(governance_state_store=store)
    assert await restarted.recover_governance_state() == 1

    status = restarted.status("rules.restart")
    assert status is not None
    assert status.state == "retired"


async def test_mimir_issue_investigation_and_quarantine_fences_survive_restart() -> None:
    store = InMemoryStateStore()
    first = Mimir(governance_state_store=store)
    first.bind_bus(_bus())

    await first.on_typed_message(
        "object.issue",
        {
            "producer_principal": "Saga",
            "correlation_id": "issue-corr",
            "idempotency_key": "issue:fp-1",
            "fingerprint": "fp-1",
            "issue_number": 42,
            "created": True,
            "open": True,
        },
    )
    await first.on_typed_message("object.rule-candidate", _investigation_candidate())
    await first.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Norns",
            "correlation_id": "bad-candidate",
            "idempotency_key": "bad-candidate:1",
            "proposed_by": "Norns",
            "proposal_kind": "unknown",
            "evidence": {"sample_size": 1},
        },
    )

    restarted = Mimir(governance_state_store=store)
    restarted.bind_bus(_bus())
    assert await restarted.recover_governance_state() == 3

    await restarted.on_typed_message("object.rule-candidate", _investigation_candidate())
    assert restarted.pending_candidates() == ()
    assert restarted.behavior_snapshot()["investigation_strategy_candidate_duplicate"] == 1
    assert len(restarted.quarantined_candidates()) == 1
    result = await restarted.introspect("rules?", {})
    assert result.facts["open_issue_fingerprints"] == 1


async def test_muninn_digest_conversation_projection_rehydrates_from_durable_store() -> None:
    store = InMemoryStateStore()
    first = Muninn(durable_state_store=store)

    await first.on_typed_message(
        "object.turn",
        {
            "producer_principal": "Bragi",
            "turn_id": "turn-1",
            "conversation_id": "conversation-1",
            "correlation_id": "turn-corr",
            "idempotency_key": "turn:1",
            "principal_scope": "sha256:" + hashlib.sha256(b"user-a").hexdigest(),
            "question": "raw text must not persist",
            "answer": "raw answer must not persist",
            "question_sha256": "a" * 64,
            "answer_sha256": "b" * 64,
        },
    )

    restarted = Muninn(durable_state_store=store)
    assert await restarted.recover_conversation_projections() == 1

    record = restarted.get_context("conversation_turns", "turn-1", requester_user_id="user-a")
    assert record is not None
    assert record["question_sha256"] == "a" * 64
    assert "question" not in record
    assert "answer" not in record


async def test_muninn_publication_outbox_suppresses_redelivery_after_restart() -> None:
    store = InMemoryStateStore()
    payload = {
        "producer_principal": "Muninn",
        "kind": "operating_pattern_retained",
        "correlation_id": "cohort-key",
        "idempotency_key": "operating-pattern-retained:abc",
    }

    first = Muninn(durable_state_store=store)
    assert await first._claim_publication("outbox:test", payload) is True

    restarted = Muninn(durable_state_store=store)
    assert await restarted._claim_publication("outbox:test", payload) is True
    await restarted._mark_publication_published("outbox:test", payload)

    completed = Muninn(durable_state_store=store)
    assert await completed._claim_publication("outbox:test", payload) is False


async def test_norns_outcome_approval_forecast_and_hint_state_rehydrates() -> None:
    store = InMemoryStateStore()
    first = Norns(
        min_outcome_samples=2,
        rollback_alarm_rate=0.0,
        rejection_revise_threshold=2,
        forecast_error_threshold=2,
        operational_state_store=store,
    )
    first.bind_candidate_publication_gate(lambda: False)

    await first.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "correlation_id": "audit-1",
            "idempotency_key": "audit:1",
            "action_type": "ops.restart",
            "result": "rollback",
        },
    )
    await first.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Var",
            "correlation_id": "approval-1",
            "idempotency_key": "approval:1",
            "action_type": "ops.scale",
            "state": "rejected",
        },
    )
    forecast_payload = {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "forecast-1",
        "idempotency_key": "forecast:1",
        "case_id": "case-1",
        "revision": "1",
        "manifest_digest": "c" * 64,
        "detector_id": "detector-1",
        "metric": "latency",
        "outcome_label": "false_positive",
        "case_ref": f"case-history:case-1:1:{'c' * 64}",
    }
    await first.on_typed_message("object.context-index", forecast_payload)
    hint = RuleCandidateHint(
        proposal_kind="revision",
        target_ref="rule-hint",
        pattern="Repeated correction indicates a narrower condition.",
        evidence_refs=("turn:1",),
        confidence=0.8,
    )
    proposal_ref = await first.submit_rule_hint(hint, proposed_by="Norns", at=_NOW)

    restarted = Norns(
        min_outcome_samples=2,
        rollback_alarm_rate=0.0,
        rejection_revise_threshold=2,
        forecast_error_threshold=2,
        operational_state_store=store,
    )
    restarted.bind_candidate_publication_gate(lambda: False)
    assert await restarted.recover_learning_state() == 1

    await restarted.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "correlation_id": "audit-1",
            "idempotency_key": "audit:1-redelivery",
            "action_type": "ops.restart",
            "result": "rollback",
        },
    )
    await restarted.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "correlation_id": "audit-2",
            "idempotency_key": "audit:2",
            "action_type": "ops.restart",
            "result": "rollback",
        },
    )
    await restarted.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Var",
            "correlation_id": "approval-1",
            "idempotency_key": "approval:1-redelivery",
            "action_type": "ops.scale",
            "state": "rejected",
        },
    )
    await restarted.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Var",
            "correlation_id": "approval-2",
            "idempotency_key": "approval:2",
            "action_type": "ops.scale",
            "state": "rejected",
        },
    )
    await restarted.on_typed_message("object.context-index", forecast_payload)
    await restarted.on_typed_message(
        "object.context-index",
        {**forecast_payload, "case_id": "case-2", "idempotency_key": "forecast:2"},
    )
    assert await restarted.submit_rule_hint(hint, proposed_by="Norns", at=_NOW) == proposal_ref

    candidates = restarted.pending_candidates
    assert [candidate["source_signal"] for candidate in candidates] == [
        "audit_outcome",
        "recurring_hil_rejection",
        "forecast_case_history",
    ]
    assert candidates[0]["evidence"]["sample_size"] == 2
    assert candidates[1]["evidence"]["rejection_count"] == 2
    assert candidates[2]["evidence"]["occurrence_count"] == 2
