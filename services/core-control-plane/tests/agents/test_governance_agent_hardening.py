"""Governance and interface agent hardening regressions (Saga, Mimir, Muninn, Norns)."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.runtime.discovery_activation import DiscoveryActivationState


def test_mimir_indexes_saga_issue_fingerprints_for_pending_candidates() -> None:
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "candidate-corr",
                "idempotency_key": "candidate-1",
                "proposed_by": "Norns",
                "proposal_kind": "new",
                "source_signal": "handoff_fingerprint",
                "evidence": {"fingerprint": "fp-1", "occurrence_count": 3},
            },
        )
    )

    asyncio.run(
        mimir.on_typed_message(
            "object.issue",
            {
                "producer_principal": "Saga",
                "correlation_id": "issue-corr",
                "idempotency_key": "issue-fp-1",
                "fingerprint": "fp-1",
                "issue_number": 7,
                "created": True,
            },
        )
    )

    result = asyncio.run(mimir.introspect("rules?", {}))
    assert result.facts["open_issue_fingerprints"] == 1
    assert mimir.behavior_snapshot()["issue_fingerprint:accepted"] == 1


def test_mimir_rejects_issue_fingerprint_from_non_saga_owner() -> None:
    mimir = Mimir()

    with pytest.raises(ValueError, match="published by Saga"):
        asyncio.run(
            mimir.on_typed_message(
                "object.issue",
                {
                    "producer_principal": "Bragi",
                    "correlation_id": "issue-corr",
                    "fingerprint": "fp-1",
                    "issue_number": 7,
                },
            )
        )

    assert mimir.behavior_snapshot()["issue_fingerprint:rejected"] == 1


def test_muninn_retains_bragi_turn_digest_only_and_blocks_cross_user_read() -> None:
    muninn = Muninn()

    asyncio.run(
        muninn.on_typed_message(
            "object.turn",
            {
                "producer_principal": "Bragi",
                "turn_id": "turn-1",
                "correlation_id": "corr-turn-1",
                "idempotency_key": "turn:1",
                "principal_scope": "sha256:" + hashlib.sha256(b"user-a").hexdigest(),
                "question": "raw question must not be retained",
                "answer": "raw answer must not be retained",
                "question_ref": "question-ref",
                "question_sha256": "a" * 64,
                "answer_ref": "answer-ref",
                "answer_sha256": "b" * 64,
            },
        )
    )

    same_user = muninn.get_context(
        "conversation_turns",
        "turn-1",
        requester_user_id="user-a",
    )
    assert same_user is not None
    assert same_user["question_sha256"] == "a" * 64
    assert "question" not in same_user
    assert "answer" not in same_user

    assert muninn.get_context("conversation_turns", "turn-1", requester_user_id="user-b") is None
    assert muninn.behavior_snapshot()["conversation_context:cross_user_refused"] == 1


def test_muninn_indexes_bragi_conversation_and_user_preference_projections() -> None:
    muninn = Muninn()
    asyncio.run(
        muninn.on_typed_message(
            "object.conversation",
            {
                "producer_principal": "Bragi",
                "conversation_id": "conversation-1",
                "correlation_id": "session-1",
                "idempotency_key": "conversation:1",
                "principal_scope": "sha256:" + hashlib.sha256(b"user-a").hexdigest(),
                "status": "active",
            },
        )
    )
    asyncio.run(
        muninn.on_typed_message(
            "object.user-preference",
            {
                "producer_principal": "Bragi",
                "id": "preference-1",
                "correlation_id": "preference-corr",
                "idempotency_key": "preference:1",
                "principal_scope": "sha256:" + hashlib.sha256(b"user-a").hexdigest(),
                "preference_digest": "sha256:" + "c" * 64,
                "locale": "ko",
            },
        )
    )

    conversation = muninn.get_context("conversations", "conversation-1", requester_user_id="user-a")
    preference = muninn.get_context("user_preferences", "preference-1", requester_user_id="user-a")
    assert conversation is not None
    assert preference is not None
    assert conversation["payload_digest"]
    assert preference["preference_digest"] == "sha256:" + "c" * 64
    assert "locale" not in preference


def test_saga_publishes_non_learnable_terminal_audit_and_norns_skips_it() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    saga = Saga()
    norns = Norns(min_outcome_samples=1, rollback_alarm_rate=0.0)
    saga.bind_bus(bus)
    bus.subscribe("object.audit-entry", "Norns", norns.on_typed_message)

    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "action_type": "remediate.z",
                "state": "rejected",
                "correlation_id": "reject-corr",
            },
        )
    )

    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["non_learnable"] is True
    assert "result" not in entries[0].payload
    assert entries[0].payload["idempotency_key"].startswith("audit-entry:action-run:")
    assert norns.pending_candidates == []
    assert norns.behavior_snapshot()["audit_outcome:non_learnable"] == 1


def test_saga_marks_shadow_success_distinct_from_real_success() -> None:
    saga = Saga()
    bus = InMemoryBus(registry=load_pantheon())
    saga.bind_bus(bus)

    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "action_type": "remediate.z",
                "state": "succeeded",
                "shadow_mode": True,
                "correlation_id": "shadow-corr",
            },
        )
    )

    entry = bus.messages_on("object.audit-entry")[0].payload
    assert entry["result"] == "shadow_success"
    assert entry["shadow_mode"] is True


def test_runtime_discovery_activation_gate_defaults_closed_for_norns() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    norns = Norns(promotion_threshold=1)
    activation = DiscoveryActivationState()
    norns.bind_candidate_publication_gate(activation.is_enabled)
    norns.bind_bus(bus)

    assert activation.is_enabled() is False
    asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": "fp-runtime-closed"}))

    assert bus.messages_on("object.rule-candidate") == []
    assert len(norns.pending_candidates) == 1
    assert norns.behavior_snapshot()["rule_candidate_publication_disabled"] == 1
