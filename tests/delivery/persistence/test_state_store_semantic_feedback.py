from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence import StateStoreSemanticFeedbackCandidateStore
from fdai.rule_catalog.schema.rule_semantic_feedback import (
    QueryFailureEvidence,
    RetrievalFailureLayer,
    build_feedback_candidate,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64


def _candidate(*, target: str = "rule:public-access@1"):
    evidence = QueryFailureEvidence(
        attempt_id="attempt:1",
        query_digest=_A,
        principal_scope_digest=_B,
        catalog_digest=_C,
        reason_code="target-not-retrieved",
        layer=RetrievalFailureLayer.RANKING_ERROR,
        reproduced=True,
        evidence_refs=("receipt:retrieval:1",),
        exact_target_rule_ref=target,
    )
    return build_feedback_candidate(evidence)


async def test_candidate_survives_store_adapter_restart() -> None:
    state = InMemoryStateStore()
    first = StateStoreSemanticFeedbackCandidateStore(
        state,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert await first.put(_candidate()) is True

    restarted = StateStoreSemanticFeedbackCandidateStore(state)

    assert await restarted.get(_candidate().candidate_id) == _candidate()
    assert await restarted.list(limit=10) == (_candidate(),)


async def test_duplicate_candidate_is_idempotent_and_audited_once() -> None:
    state = InMemoryStateStore()
    store = StateStoreSemanticFeedbackCandidateStore(
        state,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert await store.put(_candidate()) is True
    assert await store.put(_candidate()) is False

    entries = tuple(state.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["mode"] == "shadow"
    assert entries[0]["entry"]["promotion_applied"] is False


async def test_same_candidate_id_with_different_payload_conflicts() -> None:
    state = InMemoryStateStore()
    store = StateStoreSemanticFeedbackCandidateStore(state)
    candidate = _candidate()
    assert await store.put(candidate) is True
    conflicting = type(candidate)(
        candidate_id=candidate.candidate_id,
        attempt_id=candidate.attempt_id,
        query_digest=candidate.query_digest,
        target_rule_ref="rule:other@1",
        failure_layer=candidate.failure_layer,
        evidence_refs=candidate.evidence_refs,
    )

    with pytest.raises(ValueError, match="idempotency conflict"):
        await store.put(conflicting)


async def test_list_limit_is_bounded() -> None:
    store = StateStoreSemanticFeedbackCandidateStore(InMemoryStateStore())

    with pytest.raises(ValueError, match="limit"):
        await store.list(limit=0)
