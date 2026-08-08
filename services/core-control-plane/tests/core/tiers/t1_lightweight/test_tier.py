"""T1 tier - similarity reuse invariants."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.tiers.t1_lightweight import (
    LearnedAction,
    SimilarityMatch,
    T1Config,
    T1Outcome,
    T1Tier,
    cosine_similarity,
)
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.shared.contracts.models import Event


def _event(
    *, event_id: str = "00000000-0000-0000-0000-000000000001", payload: dict[str, Any] | None = None
) -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": event_id,
            "idempotency_key": event_id,
            "source": "src",
            "event_type": "change_detected",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
            "payload": payload or {},
        }
    )


def _action(**overrides: Any) -> LearnedAction:
    defaults: dict[str, Any] = {
        "signature": "sig-1",
        "rule_id": "object-storage.public-access.deny",
        "action_type": "remediate.disable-public-access",
        "params": {"reason": "test"},
        "incident_id": "incident-1",
        "success_rate": 0.95,
    }
    defaults.update(overrides)
    return LearnedAction(**defaults)


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_similarity_threshold_out_of_range_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        T1Tier(
            embedding_model=DeterministicEmbeddingModel(),
            pattern_library=InMemoryPatternLibrary(),
            config=T1Config(similarity_threshold=value),
        )


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_min_success_rate_out_of_range_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="min_success_rate"):
        T1Tier(
            embedding_model=DeterministicEmbeddingModel(),
            pattern_library=InMemoryPatternLibrary(),
            config=T1Config(min_success_rate=value),
        )


# ---------------------------------------------------------------------------
# Abstain paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_library_abstains_with_reason() -> None:
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=InMemoryPatternLibrary(),
    )
    decision = await tier.evaluate(event=_event())
    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "no_neighbour_found"
    assert decision.best_match is None


@pytest.mark.asyncio
async def test_similarity_below_threshold_abstains() -> None:
    embed = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    # Populate with a vector that has no relationship to the query text.
    unrelated_vector = await embed.embed("completely-different-event")
    library.add(vector=unrelated_vector, action=_action())

    tier = T1Tier(
        embedding_model=embed,
        pattern_library=library,
        config=T1Config(similarity_threshold=0.999),
    )
    decision = await tier.evaluate(
        event=_event(payload={"resource": {"type": "object-storage", "props": {}}})
    )
    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason is not None
    assert decision.reason.startswith("similarity=")
    assert decision.best_match is not None


@pytest.mark.asyncio
async def test_low_success_rate_abstains_even_when_similarity_high() -> None:
    embed = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    payload = {"resource": {"type": "object-storage", "props": {"x": 1}}}
    event = _event(payload=payload)

    # Seed the library with the exact vector of the query so score ≈ 1.0.
    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    query_vector = await embed.embed(_event_text(event))
    library.add(vector=query_vector, action=_action(success_rate=0.5))

    tier = T1Tier(
        embedding_model=embed,
        pattern_library=library,
        config=T1Config(similarity_threshold=0.8, min_success_rate=0.9),
    )
    decision = await tier.evaluate(event=event)
    assert decision.outcome is T1Outcome.ABSTAIN
    assert any("success_rate=" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_non_finite_similarity_score_abstains() -> None:
    class _NonFiniteLibrary:
        async def search(self, query_vector: Any, *, k: int = 5):
            return (SimilarityMatch(action=_action(), score=float("nan")),)

    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_NonFiniteLibrary(),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "non_finite_similarity_score"
    assert decision.best_match is None


@pytest.mark.asyncio
async def test_non_finite_success_rate_abstains() -> None:
    class _NonFiniteLibrary:
        async def search(self, query_vector: Any, *, k: int = 5):
            return (
                SimilarityMatch(
                    action=_action(success_rate=float("nan")),
                    score=1.0,
                ),
            )

    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_NonFiniteLibrary(),
    )

    decision = await tier.evaluate(event=_event())

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "non_finite_success_rate"


# ---------------------------------------------------------------------------
# Reuse path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_match_reuses_learned_action() -> None:
    embed = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    payload = {"resource": {"type": "object-storage", "props": {"public_access": True}}}
    event = _event(payload=payload)

    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    matching_vector = await embed.embed(_event_text(event))
    library.add(vector=matching_vector, action=_action(success_rate=0.99))

    tier = T1Tier(embedding_model=embed, pattern_library=library)
    decision = await tier.evaluate(event=event)
    assert decision.outcome is T1Outcome.REUSED
    assert decision.best_match is not None
    assert decision.best_match.action.rule_id == "object-storage.public-access.deny"
    # phase-2 § T1: "reuse is not auto-trust - must go through verifier
    # and risk gate before it can execute". The tier signals this back
    # via `requires_reverification=True` so a caller can never bypass.
    assert decision.requires_reverification is True


@pytest.mark.asyncio
async def test_best_match_is_the_highest_score_neighbour() -> None:
    embed = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    payload = {"resource": {"type": "object-storage", "props": {"public_access": True}}}
    event = _event(payload=payload)

    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    query_vector = await embed.embed(_event_text(event))
    unrelated_vector = await embed.embed("garbage-text-nowhere-near")
    library.add(vector=unrelated_vector, action=_action(signature="far", success_rate=0.99))
    library.add(vector=query_vector, action=_action(signature="close", success_rate=0.99))

    tier = T1Tier(embedding_model=embed, pattern_library=library)
    decision = await tier.evaluate(event=event)
    assert decision.outcome is T1Outcome.REUSED
    assert decision.best_match is not None
    assert decision.best_match.action.signature == "close"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_cosine_similarity_handles_empty_and_mismatched_vectors() -> None:
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, float("nan")], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, float("inf")], [1.0, 1.0]) == 0.0
    # Identical vectors → cosine 1.0.
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)
    assert cosine_similarity([0.1] * 384, [0.1] * 384) == 1.0


def test_deterministic_embedding_is_stable_across_calls() -> None:
    import asyncio

    model = DeterministicEmbeddingModel(dim=8)
    a = asyncio.run(model.embed("hello"))
    b = asyncio.run(model.embed("hello"))
    assert tuple(a) == tuple(b)
    assert len(a) == 8


def test_pattern_library_len_reports_count() -> None:
    library = InMemoryPatternLibrary()
    assert len(library) == 0
    library.add(vector=[0.1] * 8, action=_action())
    library.add(vector=[0.2] * 8, action=_action(signature="s2"))
    assert len(library) == 2


async def test_contextless_upsert_cannot_erase_operational_context() -> None:
    from datetime import UTC, datetime

    from fdai.core.tiers.t1_lightweight import OperationalCaseContext

    library = InMemoryPatternLibrary()
    context = OperationalCaseContext(
        case_ref=f"case-history:case-a:1:{'a' * 64}",
        failure_fingerprint="f" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        required_topology_role="serves",
        graph_digest="b" * 64,
        owner_digest="c" * 64,
        evidence_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
    )
    contextual = _action(signature="same", operational_case=context)
    await library.upsert_pattern(vector=[0.1] * 8, action=contextual)
    await library.upsert_pattern(vector=[0.2] * 8, action=_action(signature="same"))

    matches = await library.search([0.2] * 8, k=1)
    assert matches[0].action.operational_case == context
