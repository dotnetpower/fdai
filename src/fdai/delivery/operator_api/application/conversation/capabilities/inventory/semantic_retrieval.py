"""Non-authoritative semantic retrieval over inventory ontology surfaces."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol, runtime_checkable

from fdai.core.ontology_platform import (
    InterpretationCandidateSource,
    SemanticOperationClass,
    build_semantic_candidate,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.language import (
    InventoryQueryLanguageResolver,
    default_inventory_query_language_resolver,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    QueryValues,
    inventory_query_language_digest,
)
from fdai.shared.contracts.models import OntologyTypeRef
from fdai.shared.providers.knowledge import Embedder, cosine_similarity

_LOG = logging.getLogger(__name__)
_MAX_PROMPT_CHARS = 4096


class InventorySemanticKind(StrEnum):
    STATE = "state"
    OPERATION = "operation"


@dataclass(frozen=True, slots=True)
class InventorySemanticConfig:
    score_threshold: float = 0.50
    max_candidates: int = 3

    def __post_init__(self) -> None:
        if not math.isfinite(self.score_threshold) or not 0 < self.score_threshold <= 1:
            raise ValueError("inventory semantic score_threshold MUST be in (0, 1]")
        if not 1 <= self.max_candidates <= 8:
            raise ValueError("inventory semantic max_candidates MUST be in [1, 8]")


@dataclass(frozen=True, slots=True)
class InventorySemanticMatch:
    kind: InventorySemanticKind
    concept_id: str
    score: float
    catalog_digest: str
    target_ref: OntologyTypeRef
    input_digest: str
    candidate_digest: str
    labels: Mapping[str, str] = field(default_factory=dict)
    authority: Literal["candidate_only"] = "candidate_only"

    def __post_init__(self) -> None:
        if not self.concept_id or not math.isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("inventory semantic match is invalid")
        if not self.catalog_digest.startswith("sha256:") or len(self.catalog_digest) != 71:
            raise ValueError("inventory semantic match catalog_digest is invalid")
        for digest in (self.input_digest, self.candidate_digest):
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError("inventory semantic match proof digest is invalid")
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "concept_id": self.concept_id,
            "score": self.score,
            "catalog_digest": self.catalog_digest,
            "target_ref": self.target_ref.model_dump(mode="json"),
            "input_digest": self.input_digest,
            "candidate_digest": self.candidate_digest,
            "labels": dict(self.labels),
            "authority": self.authority,
        }


@runtime_checkable
class InventorySemanticResolver(Protocol):
    async def resolve(self, prompt: str) -> tuple[InventorySemanticMatch, ...]: ...


@dataclass(frozen=True, slots=True)
class _SemanticVector:
    kind: InventorySemanticKind
    concept_id: str
    vector: tuple[float, ...]
    labels: Mapping[str, str]


class EmbeddingInventorySemanticResolver:
    """Retrieve ontology concepts without granting query or action authority."""

    def __init__(
        self,
        *,
        embedder: Embedder,
        target_ref: OntologyTypeRef,
        language: InventoryQueryLanguageResolver | None = None,
        config: InventorySemanticConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._target_ref = target_ref
        self._language = language or default_inventory_query_language_resolver()
        self._config = config or InventorySemanticConfig()
        self._catalog_digest = inventory_query_language_digest(self._language.registry)
        self._vectors: tuple[_SemanticVector, ...] | None = None
        self._lock = asyncio.Lock()

    async def resolve(self, prompt: str) -> tuple[InventorySemanticMatch, ...]:
        if (
            not prompt.strip()
            or len(prompt) > _MAX_PROMPT_CHARS
            or any(ord(character) < 32 or ord(character) == 127 for character in prompt)
        ):
            return ()
        try:
            vectors = await self._catalog_vectors()
            query = _unit(await self._embedder.embed(prompt))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider failure is a safe abstention
            _LOG.warning(
                "inventory_semantic_retrieval_unavailable",
                extra={"error_type": type(exc).__name__},
            )
            return ()
        if query is None:
            return ()
        ranked = sorted(
            (
                (cosine_similarity(query, item.vector), item)
                for item in vectors
                if len(item.vector) == len(query)
            ),
            key=lambda pair: (-pair[0], pair[1].kind.value, pair[1].concept_id),
        )
        matches: list[InventorySemanticMatch] = []
        for score, item in ranked[: self._config.max_candidates]:
            if score < self._config.score_threshold:
                continue
            candidate = build_semantic_candidate(
                source=InterpretationCandidateSource.EMBEDDING,
                operation_class=SemanticOperationClass.QUERY,
                target_ref=self._target_ref,
                arguments={
                    "semantic_kind": item.kind.value,
                    "concept_id": item.concept_id,
                },
                semantic_catalog_digest=self._catalog_digest,
                input_text=prompt,
                score=score,
                unresolved_terms=(),
            )
            matches.append(
                InventorySemanticMatch(
                    kind=item.kind,
                    concept_id=item.concept_id,
                    score=score,
                    catalog_digest=self._catalog_digest,
                    target_ref=self._target_ref,
                    input_digest=candidate.input_digest,
                    candidate_digest=candidate.candidate_digest,
                    labels=item.labels,
                )
            )
        return tuple(matches)

    async def _catalog_vectors(self) -> tuple[_SemanticVector, ...]:
        if self._vectors is not None:
            return self._vectors
        async with self._lock:
            if self._vectors is not None:
                return self._vectors
            entries = (
                *self._entries(InventorySemanticKind.STATE, self._language.registry.states),
                *self._entries(
                    InventorySemanticKind.OPERATION,
                    self._language.registry.operations,
                ),
            )
            vectors: list[_SemanticVector] = []
            expected_dimension: int | None = None
            for kind, concept_id, entry in entries:
                vector = _unit(await self._embedder.embed(_semantic_text(kind, concept_id, entry)))
                if vector is None:
                    raise ValueError("inventory semantic catalog embedding is invalid")
                if expected_dimension is None:
                    expected_dimension = len(vector)
                elif len(vector) != expected_dimension:
                    raise ValueError("inventory semantic catalog embedding dimensions differ")
                vectors.append(
                    _SemanticVector(
                        kind=kind,
                        concept_id=concept_id,
                        vector=vector,
                        labels=entry.labels,
                    )
                )
            self._vectors = tuple(vectors)
            return self._vectors

    @staticmethod
    def _entries(
        kind: InventorySemanticKind,
        entries: Mapping[str, QueryValues],
    ) -> tuple[tuple[InventorySemanticKind, str, QueryValues], ...]:
        return tuple((kind, concept_id, entries[concept_id]) for concept_id in sorted(entries))


def _semantic_text(
    kind: InventorySemanticKind,
    concept_id: str,
    entry: QueryValues,
) -> str:
    return "\n".join(
        (
            f"{kind.value}:{concept_id}",
            entry.description,
            *entry.examples,
        )
    )


def _unit(values: Sequence[float]) -> tuple[float, ...] | None:
    if not values or any(not math.isfinite(float(value)) for value in values):
        return None
    magnitude = math.sqrt(sum(float(value) * float(value) for value in values))
    if magnitude == 0:
        return None
    return tuple(float(value) / magnitude for value in values)


__all__ = [
    "EmbeddingInventorySemanticResolver",
    "InventorySemanticConfig",
    "InventorySemanticKind",
    "InventorySemanticMatch",
    "InventorySemanticResolver",
]
