"""Structured behavior knowledge retrieval contracts.

Behavior knowledge describes how FDAI behaves without carrying raw source
code. Source evidence is citation metadata used only to verify freshness and
authority. Retrieval never grants approval or execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from fdai.shared.providers.knowledge import Embedder

BehaviorStatus = Literal["implemented", "configured", "designed", "not_applicable"]
BehaviorSourceKind = Literal["code", "test", "doc", "schema"]
BehaviorAuthorityRole = Literal["implementation", "verification", "design", "configuration"]
BehaviorMatchKind = Literal["exact_alias", "exact_identifier", "hybrid"]

EMBEDDING_DIM = 384


@dataclass(frozen=True, slots=True)
class BehaviorSource:
    """One source citation used to validate a behavior contract."""

    source_kind: BehaviorSourceKind
    path: str
    symbol: str
    line_start: int
    line_end: int
    blob_sha: str
    authority_role: BehaviorAuthorityRole

    def __post_init__(self) -> None:
        if not self.path or self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("behavior source path MUST be repository-relative")
        if not self.symbol:
            raise ValueError("behavior source symbol MUST be non-empty")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError("behavior source line range MUST be positive and ordered")
        if not self.blob_sha:
            raise ValueError("behavior source blob_sha MUST be non-empty")

    def citation(self) -> dict[str, str | int]:
        """Return display-safe provenance without source body text."""
        return {
            "path": self.path,
            "symbol": self.symbol,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "blob_sha": self.blob_sha,
        }

    def manifest_record(self) -> dict[str, str | int]:
        """Return complete metadata for internal hashing and persistence."""
        return {
            **self.citation(),
            "source_kind": self.source_kind,
            "authority_role": self.authority_role,
        }


@dataclass(frozen=True, slots=True)
class BehaviorContent:
    """Localized structured prose for one behavior contract."""

    trigger: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    outcomes: tuple[str, ...]
    exclusions: tuple[str, ...]
    safety: tuple[str, ...]

    def search_text(self) -> str:
        return "\n".join(
            (
                *self.trigger,
                *self.preconditions,
                *self.steps,
                *self.outcomes,
                *self.exclusions,
                *self.safety,
            )
        )


@dataclass(frozen=True, slots=True)
class BehaviorSpec:
    """One answerable behavior contract."""

    behavior_id: str
    subject_kind: str
    subject_id: str
    status: BehaviorStatus
    owner: str
    question_aliases: tuple[str, ...]
    trigger: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    outcomes: tuple[str, ...]
    exclusions: tuple[str, ...]
    safety: tuple[str, ...]
    sources: tuple[BehaviorSource, ...]
    indexed_commit: str
    extractor_version: str
    source_manifest_hash: str
    localized: Mapping[str, BehaviorContent] = field(default_factory=dict)
    embedding: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        required = {
            "behavior_id": self.behavior_id,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "owner": self.owner,
            "indexed_commit": self.indexed_commit,
            "extractor_version": self.extractor_version,
            "source_manifest_hash": self.source_manifest_hash,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"behavior fields MUST be non-empty: {', '.join(missing)}")
        if not self.question_aliases:
            raise ValueError("behavior question_aliases MUST be non-empty")
        if not self.sources:
            raise ValueError("behavior sources MUST be non-empty")
        if self.embedding and len(self.embedding) != EMBEDDING_DIM:
            raise ValueError(f"behavior embedding MUST have dimension {EMBEDDING_DIM}")

    @property
    def test_backed(self) -> bool:
        return any(source.source_kind == "test" for source in self.sources)

    def search_text(self) -> str:
        """Return structured behavior prose suitable for embedding."""
        fields = (
            self.subject_kind,
            self.subject_id,
            *self.question_aliases,
            *self.trigger,
            *self.preconditions,
            *self.steps,
            *self.outcomes,
            *self.exclusions,
            *self.safety,
        )
        localized = tuple(content.search_text() for _, content in sorted(self.localized.items()))
        return "\n".join((*fields, *localized))


@dataclass(frozen=True, slots=True)
class BehaviorFreshness:
    """Freshness result for one source citation."""

    fresh: bool
    tracked: bool
    current_blob_sha: str | None = None


@runtime_checkable
class BehaviorSourceValidator(Protocol):
    """Validate source hashes against a tracked repository allowlist."""

    async def validate(self, source: BehaviorSource) -> BehaviorFreshness: ...


@dataclass(frozen=True, slots=True)
class BehaviorSearchResult:
    """One ranked behavior contract and its freshness state."""

    spec: BehaviorSpec
    score: float
    match_kind: BehaviorMatchKind
    stale: bool
    stale_sources: tuple[BehaviorSource, ...] = ()


@runtime_checkable
class BehaviorKnowledgeIndex(Protocol):
    """Idempotently index and retrieve structured behavior contracts."""

    async def upsert(self, spec: BehaviorSpec) -> bool:
        """Store ``spec`` and return whether the stored value changed."""
        ...

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResult]: ...


__all__ = [
    "BehaviorAuthorityRole",
    "BehaviorContent",
    "BehaviorFreshness",
    "BehaviorKnowledgeIndex",
    "BehaviorMatchKind",
    "BehaviorSearchResult",
    "BehaviorSource",
    "BehaviorSourceKind",
    "BehaviorSourceValidator",
    "BehaviorSpec",
    "BehaviorStatus",
    "EMBEDDING_DIM",
    "Embedder",
]
