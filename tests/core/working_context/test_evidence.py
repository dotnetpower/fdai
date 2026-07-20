"""Durable context-selection evidence store tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.working_context import (
    ContextManifest,
    ContextSelectionEvaluation,
    StateStoreContextSelectionEvaluationStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def evaluation() -> ContextSelectionEvaluation:
    manifest = ContextManifest(
        verbatim_ids=("turn",),
        summary_ids=(),
        retrieved_ids=(),
        pinned_ids=(),
        typed_fact_ids=(),
        verbatim_tokens=10,
        summary_tokens=0,
        retrieved_tokens=0,
        pinned_tokens=0,
        typed_fact_tokens=0,
        dropped_ids=(),
    )
    return ContextSelectionEvaluation(
        evaluation_id="eval-1",
        input_fingerprint="a" * 64,
        baseline_policy_ref="deterministic-tiered-v1@1.0.0",
        candidate_policy_ref="candidate-v1@1.0.0",
        baseline_manifest=manifest,
        candidate_manifest=manifest,
        baseline_tokens=10,
        candidate_tokens=10,
        evidence_overlap=1.0,
        omissions=(),
        pinned_preserved=True,
        relevance=None,
        answer_quality_ref="answer-1",
        answer_quality_score=0.9,
        latency_ms=2.5,
        failure_reason=None,
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
    )


async def test_state_store_round_trip_preserves_comparison() -> None:
    store = StateStoreContextSelectionEvaluationStore(InMemoryStateStore())
    expected = evaluation()

    await store.append(expected)

    assert await store.list(limit=10) == (expected,)
    with pytest.raises(ValueError, match="duplicate evaluation id"):
        await store.append(expected)
