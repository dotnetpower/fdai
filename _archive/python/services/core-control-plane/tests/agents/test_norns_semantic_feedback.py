from __future__ import annotations

from typing import Any

import pytest
from fdai.agents import Norns, instantiate_pantheon
from fdai.delivery.persistence import StateStoreSemanticFeedbackCandidateStore
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidate
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_QUERY = "sha256:" + "a" * 64
_SCOPE = "sha256:" + "b" * 64
_CATALOG = "sha256:" + "c" * 64


class _CandidateSink:
    def __init__(self) -> None:
        self.candidates: list[SemanticFeedbackCandidate] = []

    async def put(self, candidate: SemanticFeedbackCandidate) -> bool:
        created = candidate not in self.candidates
        if created:
            self.candidates.append(candidate)
        return created


def _payload(**overrides: object) -> dict[str, Any]:
    failure: dict[str, object] = {
        "attempt_id": "attempt:semantic:1",
        "query_digest": _QUERY,
        "principal_scope_digest": _SCOPE,
        "catalog_digest": _CATALOG,
        "reason_code": "target-not-retrieved",
        "layer": "ranking_error",
        "reproduced": True,
        "evidence_refs": ["receipt:retrieval:1", "receipt:validation:1"],
        "exact_target_rule_ref": "rule:object-storage.public-access.deny@1.0.0",
    }
    failure.update(overrides)
    return {
        "producer_principal": "Muninn",
        "kind": "semantic_retrieval_failure",
        "failure": failure,
    }


async def test_reproduced_feedback_persists_before_rule_candidate() -> None:
    sink = _CandidateSink()
    norns = Norns(semantic_feedback_store=sink)

    await norns.on_typed_message("object.context-index", _payload())

    assert len(sink.candidates) == 1
    assert len(norns.pending_candidates) == 1
    proposal = norns.pending_candidates[0]
    assert proposal["source_signal"] == "semantic_retrieval_failure"
    assert proposal["proposal_kind"] == "revision"
    assert proposal["target_rule_id"] == "object-storage.public-access.deny"
    assert proposal["evidence"]["promotion_authority"] is False


async def test_replayed_feedback_is_persisted_and_proposed_once() -> None:
    sink = _CandidateSink()
    norns = Norns(semantic_feedback_store=sink)
    payload = _payload()

    await norns.on_typed_message("object.context-index", payload)
    await norns.on_typed_message("object.context-index", payload)

    assert len(sink.candidates) == 1
    assert len(norns.pending_candidates) == 1
    assert norns.behavior_snapshot()["semantic_feedback_candidate_duplicate"] == 1


async def test_feedback_without_durable_sink_backpressures() -> None:
    norns = Norns()

    with pytest.raises(RuntimeError, match="sink is unavailable"):
        await norns.on_typed_message("object.context-index", _payload())

    assert norns.pending_candidates == []


async def test_unreproduced_feedback_cannot_reach_candidate_store() -> None:
    sink = _CandidateSink()
    norns = Norns(semantic_feedback_store=sink)

    with pytest.raises(ValueError, match="MUST be reproduced"):
        await norns.on_typed_message(
            "object.context-index",
            _payload(reproduced=False),
        )

    assert sink.candidates == []
    assert norns.pending_candidates == []


async def test_reproduced_feedback_reaches_existing_mimir_guard_in_shadow() -> None:
    state = InMemoryStateStore()
    norns = Norns(semantic_feedback_store=StateStoreSemanticFeedbackCandidateStore(state))
    mimir = instantiate_pantheon()["Mimir"]

    await norns.on_typed_message("object.context-index", _payload())
    proposal = norns.pending_candidates[0]
    await mimir.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Norns",
            "correlation_id": "norns:semantic-feedback",
            "idempotency_key": "rule-candidate:semantic-feedback",
            **proposal,
            "norns_consensus": {
                "decision": "propose",
                "unanimous": True,
                "perspective_count": 3,
            },
        },
    )

    assert len(state.audit_entries) == 1
    assert state.audit_entries[0]["entry"]["promotion_applied"] is False
    assert mimir.pending_candidates()[0]["source_signal"] == "semantic_retrieval_failure"
