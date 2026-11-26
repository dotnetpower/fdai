"""Cross-campaign question novelty ledger tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.conversation.question_novelty import (
    InMemoryQuestionNoveltyLedger,
    QuestionEmbeddingIdentity,
    QuestionNoveltyRecord,
    summarize_question_novelty,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _record(
    *,
    campaign_character: str = "a",
    case_id: str = "case-1",
    fingerprint_character: str = "b",
    similarity: float = 0.1,
    exact_duplicate: bool = False,
    semantic_duplicate: bool = False,
    accepted: bool = True,
) -> QuestionNoveltyRecord:
    return QuestionNoveltyRecord(
        campaign_id="qs:" + campaign_character * 64,
        case_id=case_id,
        generation_attempt=1,
        perspective="resource",
        locale="en",
        ontology_release_digest=DIGEST,
        question_fingerprint="sha256:" + fingerprint_character * 64,
        embedding=QuestionEmbeddingIdentity(
            space_digest=DIGEST,
            model_version="embedding-v1",
            dimension=384,
            vector_digest="sha256:" + "c" * 64,
        ),
        nearest_question_fingerprint=None,
        max_embedding_similarity=similarity,
        exact_duplicate=exact_duplicate,
        semantic_duplicate=semantic_duplicate,
        accepted=accepted,
        recorded_at=NOW,
    )


async def test_novelty_ledger_rejects_cross_campaign_exact_duplicate() -> None:
    ledger = InMemoryQuestionNoveltyLedger()
    first = _record()
    duplicate = _record(
        campaign_character="d",
        exact_duplicate=True,
        accepted=False,
    )

    assert await ledger.append_novelty(first) is True
    assert await ledger.append_novelty(duplicate) is True
    with pytest.raises(ValueError, match="accepted question fingerprint already exists"):
        await ledger.append_novelty(
            replace(
                duplicate,
                campaign_id="qs:" + "e" * 64,
                exact_duplicate=False,
                accepted=True,
            )
        )


async def test_novelty_ledger_is_append_only() -> None:
    ledger = InMemoryQuestionNoveltyLedger()
    record = _record()

    assert await ledger.append_novelty(record) is True
    assert await ledger.append_novelty(record) is False
    with pytest.raises(ValueError, match="different content"):
        await ledger.append_novelty(replace(record, recorded_at=NOW.replace(second=1)))


def test_semantic_duplicate_threshold_is_exact_and_fail_closed() -> None:
    duplicate = _record(similarity=0.92, semantic_duplicate=True, accepted=False)

    assert duplicate.semantic_duplicate is True
    with pytest.raises(ValueError, match="conflicts with similarity"):
        _record(similarity=0.92, semantic_duplicate=False, accepted=True)


def test_embedding_dimension_is_an_integer_and_threshold_is_replayable() -> None:
    with pytest.raises(ValueError, match="dimension"):
        QuestionEmbeddingIdentity(  # type: ignore[arg-type]
            space_digest=DIGEST,
            model_version="embedding-v1",
            dimension=384.0,
            vector_digest=DIGEST,
        )
    with pytest.raises(ValueError, match="conflicts with similarity"):
        replace(
            _record(),
            max_embedding_similarity=0.91,
            semantic_duplicate_threshold=0.90,
        )


async def test_nearest_fingerprint_must_reference_an_accepted_record() -> None:
    ledger = InMemoryQuestionNoveltyLedger()
    orphan = replace(
        _record(),
        nearest_question_fingerprint="sha256:" + "f" * 64,
    )

    with pytest.raises(ValueError, match="not an accepted ledger record"):
        await ledger.append_novelty(orphan)


def test_novelty_summary_reports_every_required_axis() -> None:
    records = (
        _record(),
        _record(
            campaign_character="d",
            exact_duplicate=True,
            accepted=False,
        ),
    )

    summary = summarize_question_novelty(records)

    assert len(summary) == 1
    assert summary[0].case_id == "case-1"
    assert summary[0].perspective == "resource"
    assert summary[0].locale == "en"
    assert summary[0].ontology_release_digest == DIGEST
    assert summary[0].candidate_count == 2
    assert summary[0].accepted_count == 1
    assert summary[0].exact_duplicate_count == 1
