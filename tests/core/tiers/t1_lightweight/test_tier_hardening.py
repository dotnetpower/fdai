from __future__ import annotations

from typing import Any

import pytest

from fdai.core.tiers.t1_lightweight import (
    LearnedAction,
    SimilarityMatch,
    T1Outcome,
    T1Tier,
)
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.shared.contracts.models import Event


def _action(**overrides: Any) -> LearnedAction:
    values: dict[str, Any] = {
        "signature": "sig-1",
        "rule_id": "object-storage.public-access.deny",
        "action_type": "remediate.disable-public-access",
        "params": {"reason": "test"},
        "incident_id": "incident-1",
        "success_rate": 0.95,
        "reuse_count": 0,
    }
    values.update(overrides)
    return LearnedAction(**values)


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "change_detected",
            "detected_at": "2026-07-22T00:00:00Z",
            "ingested_at": "2026-07-22T00:00:01Z",
            "mode": "shadow",
            "payload": {},
        }
    )


class _Library:
    def __init__(self, match: SimilarityMatch) -> None:
        self._match = match

    async def search(self, query_vector: Any, *, k: int = 5):  # type: ignore[no-untyped-def]
        return (self._match,)


@pytest.mark.parametrize("score", [-1.01, 1.01])
async def test_out_of_range_similarity_abstains(score: float) -> None:
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_Library(SimilarityMatch(action=_action(), score=score)),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "similarity_score_out_of_range"
    assert decision.best_match is None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"success_rate": -0.01}, "success_rate_out_of_range"),
        ({"success_rate": 1.01}, "success_rate_out_of_range"),
        ({"reuse_count": -1}, "negative_reuse_count"),
        ({"signature": "   "}, "invalid_learned_action_signature"),
        ({"rule_id": ""}, "invalid_learned_action_rule_id"),
        ({"action_type": "\t"}, "invalid_learned_action_action_type"),
        ({"incident_id": " "}, "invalid_learned_action_incident_id"),
        ({"params": []}, "invalid_learned_action_params"),
    ],
)
async def test_invalid_learned_action_evidence_abstains(
    changes: dict[str, Any],
    reason: str,
) -> None:
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_Library(SimilarityMatch(action=_action(**changes), score=1.0)),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert reason in decision.reasons


class _RaisingEmbedding:
    async def embed(self, text: str) -> tuple[float, ...]:
        raise RuntimeError("embedding backend down")


class _RaisingLibrary:
    async def search(self, query_vector: Any, *, k: int = 5):  # type: ignore[no-untyped-def]
        raise RuntimeError("pattern library down")


async def test_embedding_provider_failure_abstains() -> None:
    tier = T1Tier(
        embedding_model=_RaisingEmbedding(),
        pattern_library=_Library(SimilarityMatch(action=_action(), score=0.99)),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "t1_provider_error:RuntimeError"
    assert decision.best_match is None


async def test_pattern_library_failure_abstains() -> None:
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_RaisingLibrary(),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "t1_provider_error:RuntimeError"
    assert decision.best_match is None
