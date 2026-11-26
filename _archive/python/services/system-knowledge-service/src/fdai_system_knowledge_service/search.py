"""Deterministic bilingual retrieval over one immutable knowledge catalog."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from fdai_service_contracts.system_knowledge import (
    SystemKnowledgeCatalog,
    SystemKnowledgeMatch,
    SystemKnowledgeQueryRequest,
    SystemKnowledgeQueryResponse,
    SystemKnowledgeRecord,
    system_knowledge_digest,
)

_LATIN = re.compile(r"[a-z0-9]+")
_HANGUL = re.compile(r"[가-힣]+")
_STATUS_RANK = {
    "validated": 0,
    "implemented": 1,
    "in_progress": 2,
    "not_started": 3,
    "deferred": 4,
    "not_applicable": 5,
}
_LEXICAL_FLOOR = 0.08
MatchKind = Literal["exact_alias", "exact_identifier", "lexical"]


class SystemKnowledgeIndex:
    """Search one validated catalog without model or source-file access."""

    def __init__(
        self,
        catalog: SystemKnowledgeCatalog,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tokens = {
            record.knowledge_id: set(_tokens(_search_text(record))) for record in catalog.records
        }

    @property
    def catalog(self) -> SystemKnowledgeCatalog:
        """Return the immutable catalog identity used by this index."""

        return self._catalog

    def search(self, request: SystemKnowledgeQueryRequest) -> SystemKnowledgeQueryResponse:
        """Return ordered matches or one complete empty result."""

        query = unicodedata.normalize("NFKC", request.query).strip()
        query_tokens = set(_tokens(query))
        ranked: list[tuple[float, int, str, SystemKnowledgeMatch]] = []
        for record in self._catalog.records:
            match_kind, score = self._score(record, query, query_tokens)
            if score < _LEXICAL_FLOOR:
                continue
            match = SystemKnowledgeMatch(
                record=record,
                score=round(min(score, 10.0), 6),
                match_kind=match_kind,
            )
            ranked.append(
                (
                    -match.score,
                    _STATUS_RANK[record.status.value],
                    record.knowledge_id,
                    match,
                )
            )
        ranked.sort(key=lambda item: item[:3])
        matches = tuple(item[3] for item in ranked[: request.limit])
        body = {
            "schema_version": "1.0.0",
            "outcome": "answered" if matches else "empty",
            "matches": matches,
            "observed_at": self._clock(),
            "source_revision": self._catalog.source_revision,
            "catalog_digest": self._catalog.catalog_digest,
            "complete": True,
            "limitation": None,
            "execution_authority": False,
        }
        return SystemKnowledgeQueryResponse.model_validate(
            {
                **body,
                "response_digest": system_knowledge_digest(body),
            }
        )

    def _score(
        self,
        record: SystemKnowledgeRecord,
        query: str,
        query_tokens: set[str],
    ) -> tuple[MatchKind, float]:
        normalized_query = " ".join(_tokens(query))
        if any(" ".join(_tokens(alias)) == normalized_query for alias in record.question_aliases):
            return "exact_alias", 10.0
        identifiers = set(_tokens(f"{record.knowledge_id} {record.subject_id}"))
        if query_tokens & identifiers:
            return "exact_identifier", 8.0
        if not query_tokens:
            return "lexical", 0.0
        matched = query_tokens & self._tokens[record.knowledge_id]
        if len(matched) < 2:
            return "lexical", 0.0
        overlap = len(matched) / len(query_tokens)
        return "lexical", overlap


def _search_text(record: SystemKnowledgeRecord) -> str:
    return "\n".join(
        (
            record.knowledge_id,
            record.subject_id,
            record.title,
            *record.question_aliases,
            *record.designed_behavior,
            *record.implemented_behavior,
            *record.limitations,
        )
    )


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    for word in _LATIN.findall(normalized.replace("_", " ").replace("-", " ")):
        tokens.append(_singular(word))
    for run in _HANGUL.findall(normalized):
        tokens.append(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tuple(tokens)


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


__all__ = ["SystemKnowledgeIndex"]
