"""Cross-campaign novelty evidence without persisted question text or vectors."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

_CAMPAIGN_ID_PATTERN = re.compile(r"qs:[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}")
_LOCALES = frozenset({"en", "ko"})
_SEMANTIC_DUPLICATE_LIMIT = 0.92
_MAX_RECORDS = 10_000


class QuestionNoveltyDuplicateError(ValueError):
    """The normalized question fingerprint already belongs to accepted content."""


@dataclass(frozen=True, slots=True)
class QuestionEmbeddingIdentity:
    """Bounded identity of one embedding without retaining its vector."""

    space_digest: str
    model_version: str
    dimension: int
    vector_digest: str

    def __post_init__(self) -> None:
        _require_digest("question embedding space", self.space_digest)
        _require_digest("question embedding vector", self.vector_digest)
        if not self.model_version or len(self.model_version) > 128:
            raise ValueError("question embedding model version MUST be bounded")
        if (
            isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
            or not 1 <= self.dimension <= 65_536
        ):
            raise ValueError("question embedding dimension MUST be in [1, 65536]")


@dataclass(frozen=True, slots=True)
class QuestionNoveltyRecord:
    """Append-only exact and semantic duplicate decision for one candidate."""

    campaign_id: str
    case_id: str
    generation_attempt: int
    perspective: str
    locale: str
    ontology_release_digest: str
    question_fingerprint: str
    embedding: QuestionEmbeddingIdentity | None
    nearest_question_fingerprint: str | None
    max_embedding_similarity: float | None
    exact_duplicate: bool
    semantic_duplicate: bool
    accepted: bool
    recorded_at: datetime
    semantic_duplicate_threshold: float = _SEMANTIC_DUPLICATE_LIMIT

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question novelty campaign id is invalid")
        for name, value in (("case", self.case_id), ("perspective", self.perspective)):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"question novelty {name} is invalid")
        if self.locale not in _LOCALES:
            raise ValueError("question novelty locale MUST be en or ko")
        if not 1 <= self.generation_attempt <= 10:
            raise ValueError("question novelty generation attempt MUST be in [1, 10]")
        _require_digest("question novelty release", self.ontology_release_digest)
        _require_digest("question novelty fingerprint", self.question_fingerprint)
        if self.recorded_at.tzinfo is None:
            raise ValueError("question novelty time MUST be timezone-aware")
        if not 0.0 <= self.semantic_duplicate_threshold <= 1.0:
            raise ValueError("question novelty duplicate threshold MUST be in [0, 1]")
        if self.embedding is None:
            if (
                self.nearest_question_fingerprint is not None
                or self.max_embedding_similarity is not None
            ):
                raise ValueError(
                    "question novelty semantic evidence requires an embedding identity"
                )
            if self.semantic_duplicate:
                raise ValueError("semantic duplicate requires embedding evidence")
        else:
            if (
                self.max_embedding_similarity is None
                or not 0.0 <= self.max_embedding_similarity <= 1.0
            ):
                raise ValueError("question novelty similarity MUST be in [0, 1]")
            if self.semantic_duplicate != (
                self.max_embedding_similarity >= self.semantic_duplicate_threshold
            ):
                raise ValueError("semantic duplicate decision conflicts with similarity")
            if self.nearest_question_fingerprint is not None:
                _require_digest("nearest question fingerprint", self.nearest_question_fingerprint)
        if self.accepted == (self.exact_duplicate or self.semantic_duplicate):
            raise ValueError("question novelty acceptance conflicts with duplicate evidence")


@dataclass(frozen=True, slots=True)
class QuestionNoveltyBucket:
    """Novelty counts for one case, perspective, locale, and release."""

    case_id: str
    perspective: str
    locale: str
    ontology_release_digest: str
    candidate_count: int
    accepted_count: int
    exact_duplicate_count: int
    semantic_duplicate_count: int


class QuestionNoveltyLedger(Protocol):
    """Append-only cross-campaign novelty persistence contract."""

    async def append_novelty(self, record: QuestionNoveltyRecord) -> bool: ...

    async def list_novelty(self, *, limit: int = 10_000) -> tuple[QuestionNoveltyRecord, ...]: ...


class InMemoryQuestionNoveltyLedger:
    """Reference ledger that enforces exact duplicate decisions across campaigns."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, int], QuestionNoveltyRecord] = {}

    async def append_novelty(self, record: QuestionNoveltyRecord) -> bool:
        key = (record.campaign_id, record.case_id, record.generation_attempt)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("question novelty identity already belongs to different content")
            return False
        prior_exact = any(
            item.accepted and item.question_fingerprint == record.question_fingerprint
            for item in self._records.values()
        )
        if record.accepted and prior_exact:
            raise QuestionNoveltyDuplicateError("accepted question fingerprint already exists")
        if record.exact_duplicate != prior_exact:
            raise ValueError("question novelty exact duplicate decision conflicts with ledger")
        if record.nearest_question_fingerprint is not None and not any(
            item.accepted and item.question_fingerprint == record.nearest_question_fingerprint
            for item in self._records.values()
        ):
            raise ValueError("nearest question fingerprint is not an accepted ledger record")
        self._records[key] = record
        return True

    async def list_novelty(self, *, limit: int = _MAX_RECORDS) -> tuple[QuestionNoveltyRecord, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= _MAX_RECORDS:
            raise ValueError(f"question novelty limit MUST be in [1, {_MAX_RECORDS}]")
        return tuple(
            sorted(
                self._records.values(),
                key=lambda item: (
                    item.recorded_at,
                    item.campaign_id,
                    item.case_id,
                    item.generation_attempt,
                ),
            )[:limit]
        )


def summarize_question_novelty(
    records: Sequence[QuestionNoveltyRecord],
) -> tuple[QuestionNoveltyBucket, ...]:
    """Report novelty by case, perspective, locale, and exact release."""

    if len(records) > _MAX_RECORDS:
        raise ValueError("question novelty summary exceeds its record bound")
    grouped: dict[tuple[str, str, str, str], list[QuestionNoveltyRecord]] = {}
    for record in records:
        key = (
            record.case_id,
            record.perspective,
            record.locale,
            record.ontology_release_digest,
        )
        grouped.setdefault(key, []).append(record)
    return tuple(
        QuestionNoveltyBucket(
            case_id=key[0],
            perspective=key[1],
            locale=key[2],
            ontology_release_digest=key[3],
            candidate_count=len(items),
            accepted_count=sum(item.accepted for item in items),
            exact_duplicate_count=sum(item.exact_duplicate for item in items),
            semantic_duplicate_count=sum(item.semantic_duplicate for item in items),
        )
        for key, items in sorted(grouped.items())
    )


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


__all__ = [
    "InMemoryQuestionNoveltyLedger",
    "QuestionEmbeddingIdentity",
    "QuestionNoveltyBucket",
    "QuestionNoveltyDuplicateError",
    "QuestionNoveltyLedger",
    "QuestionNoveltyRecord",
    "summarize_question_novelty",
]
