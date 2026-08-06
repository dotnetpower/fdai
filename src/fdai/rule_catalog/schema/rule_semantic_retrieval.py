"""Immutable contracts for governed Rule semantic retrieval.

The contracts separate deterministic manifests, proposal-only language surfaces,
validated search generations, and read-only retrieval receipts. None grants policy
evaluation or execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.shared.contracts.models import Redistribution

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$")
_MAX_VALUES = 256
_MAX_TEXT = 4096


class RuleCorpus(StrEnum):
    """Disjoint operational and catalog-curation search corpora."""

    ACTIVE = "active"
    DISCOVERY = "discovery"


class SurfaceOrigin(StrEnum):
    """How one language surface candidate was proposed."""

    AUTHORED = "authored"
    GENERATED = "generated"
    FEEDBACK = "feedback"


class SurfaceState(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PROMOTED = "promoted"
    RETIRED = "retired"
    REJECTED = "rejected"


class ValidationDecision(StrEnum):
    PASS = "pass"  # noqa: S105 - validation outcome, not a credential
    HOLD = "hold"
    REJECT = "reject"


class GenerationState(StrEnum):
    STAGED = "staged"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"


class RetrievalOperation(StrEnum):
    DISCOVER = "discover"
    EXPLAIN = "explain"
    EVALUATE = "evaluate"
    ACTION_DRAFT = "action_draft"


class SemanticAvailability(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class RuleSemanticManifest:
    """Deterministic, evidence-pinned semantics extracted from one Rule."""

    rule_id: str
    rule_version: str
    corpus: RuleCorpus
    policy_ref: str
    policy_digest: str
    source_content_digest: str
    parser_id: str
    parser_version: str
    redistribution: Redistribution
    resource_type: str
    ontology_release_digest: str
    signal_refs: tuple[str, ...]
    property_refs: tuple[str, ...]
    action_type_ref: str
    predicate_refs: tuple[str, ...] = ()
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name, value in (
            ("rule_id", self.rule_id),
            ("rule_version", self.rule_version),
            ("policy_ref", self.policy_ref),
            ("parser_id", self.parser_id),
            ("parser_version", self.parser_version),
            ("resource_type", self.resource_type),
            ("action_type_ref", self.action_type_ref),
            ("schema_version", self.schema_version),
        ):
            _bounded_identifier(name, value)
        for name, value in (
            ("policy_digest", self.policy_digest),
            ("source_content_digest", self.source_content_digest),
            ("ontology_release_digest", self.ontology_release_digest),
        ):
            _require_digest(name, value)
        _ordered_unique("signal_refs", self.signal_refs, allow_empty=False)
        _ordered_unique("property_refs", self.property_refs, allow_empty=False)
        _ordered_unique("predicate_refs", self.predicate_refs, allow_empty=True)

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "rule_id": self.rule_id,
                "rule_version": self.rule_version,
                "corpus": self.corpus.value,
                "policy_ref": self.policy_ref,
                "policy_digest": self.policy_digest,
                "source_content_digest": self.source_content_digest,
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "redistribution": self.redistribution.value,
                "resource_type": self.resource_type,
                "ontology_release_digest": self.ontology_release_digest,
                "signal_refs": self.signal_refs,
                "property_refs": self.property_refs,
                "action_type_ref": self.action_type_ref,
                "predicate_refs": self.predicate_refs,
            }
        )


@dataclass(frozen=True, slots=True)
class RuleSemanticSurface:
    """Proposal-only natural-language surface for one deterministic manifest."""

    surface_id: str
    manifest_digest: str
    locale: str
    origin: SurfaceOrigin
    intent_ids: tuple[str, ...]
    concept_refs: tuple[str, ...]
    aliases: tuple[str, ...]
    training_queries: tuple[str, ...]
    hard_negative_queries: tuple[str, ...]
    producer_ref: str
    evidence_refs: tuple[str, ...]
    state: SurfaceState = SurfaceState.CANDIDATE
    prompt_digest: str | None = None
    validation_receipt_digest: str | None = None
    execution_authority: bool = False
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        _bounded_identifier("surface_id", self.surface_id)
        _bounded_identifier("locale", self.locale)
        _bounded_identifier("producer_ref", self.producer_ref)
        _bounded_identifier("schema_version", self.schema_version)
        _require_digest("manifest_digest", self.manifest_digest)
        if self.prompt_digest is not None:
            _require_digest("prompt_digest", self.prompt_digest)
        if self.validation_receipt_digest is not None:
            _require_digest("validation_receipt_digest", self.validation_receipt_digest)
        for name, values, allow_empty in (
            ("intent_ids", self.intent_ids, False),
            ("concept_refs", self.concept_refs, False),
            ("aliases", self.aliases, True),
            ("training_queries", self.training_queries, False),
            ("hard_negative_queries", self.hard_negative_queries, False),
            ("evidence_refs", self.evidence_refs, False),
        ):
            _ordered_unique(name, values, allow_empty=allow_empty, identifiers=False)
        if self.origin is SurfaceOrigin.GENERATED and self.prompt_digest is None:
            raise ValueError("generated semantic surface MUST carry a prompt_digest")
        if self.state is not SurfaceState.CANDIDATE and self.validation_receipt_digest is None:
            raise ValueError("non-candidate semantic surface MUST carry validation evidence")
        if self.execution_authority:
            raise ValueError("semantic surface MUST NOT carry execution authority")
        overlap = {_normalize_query(item) for item in self.training_queries}.intersection(
            _normalize_query(item) for item in self.hard_negative_queries
        )
        if overlap:
            raise ValueError("semantic surface training and hard-negative queries MUST be disjoint")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "surface_id": self.surface_id,
                "manifest_digest": self.manifest_digest,
                "locale": self.locale,
                "origin": self.origin.value,
                "intent_ids": self.intent_ids,
                "concept_refs": self.concept_refs,
                "aliases": self.aliases,
                "training_queries": self.training_queries,
                "hard_negative_queries": self.hard_negative_queries,
                "producer_ref": self.producer_ref,
                "evidence_refs": self.evidence_refs,
                "state": self.state.value,
                "prompt_digest": self.prompt_digest,
                "validation_receipt_digest": self.validation_receipt_digest,
                "execution_authority": self.execution_authority,
            }
        )


@dataclass(frozen=True, slots=True)
class CohortMetric:
    cohort: str
    metric: str
    value: float
    sample_count: int

    def __post_init__(self) -> None:
        _bounded_identifier("cohort", self.cohort)
        _bounded_identifier("metric", self.metric)
        if not math.isfinite(self.value):
            raise ValueError("cohort metric value MUST be finite")
        if self.sample_count < 1:
            raise ValueError("cohort metric sample_count MUST be positive")


@dataclass(frozen=True, slots=True)
class SurfaceValidationReceipt:
    """Held-out retrieval evidence that cannot promote a surface by itself."""

    surface_digest: str
    dataset_digest: str
    evaluator_ref: str
    training_query_digests: tuple[str, ...]
    evaluation_query_digests: tuple[str, ...]
    cohort_metrics: tuple[CohortMetric, ...]
    failure_codes: tuple[str, ...]
    decision: ValidationDecision
    validation_authority: str = "validation_only"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name, value in (
            ("surface_digest", self.surface_digest),
            ("dataset_digest", self.dataset_digest),
        ):
            _require_digest(name, value)
        _bounded_identifier("evaluator_ref", self.evaluator_ref)
        _bounded_identifier("schema_version", self.schema_version)
        _ordered_digests("training_query_digests", self.training_query_digests)
        _ordered_digests("evaluation_query_digests", self.evaluation_query_digests)
        if set(self.training_query_digests).intersection(self.evaluation_query_digests):
            raise ValueError("training and held-out evaluation queries MUST be disjoint")
        if not self.cohort_metrics:
            raise ValueError("surface validation MUST carry cohort metrics")
        metric_keys = tuple((item.cohort, item.metric) for item in self.cohort_metrics)
        if metric_keys != tuple(sorted(set(metric_keys))):
            raise ValueError("surface validation cohort metrics MUST be unique and ordered")
        _ordered_unique("failure_codes", self.failure_codes, allow_empty=True)
        if self.decision is ValidationDecision.PASS and self.failure_codes:
            raise ValueError("passing surface validation MUST NOT carry failures")
        if self.validation_authority != "validation_only":
            raise ValueError("surface validation MUST remain validation_only")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "surface_digest": self.surface_digest,
                "dataset_digest": self.dataset_digest,
                "evaluator_ref": self.evaluator_ref,
                "training_query_digests": self.training_query_digests,
                "evaluation_query_digests": self.evaluation_query_digests,
                "cohort_metrics": [
                    (item.cohort, item.metric, item.value, item.sample_count)
                    for item in self.cohort_metrics
                ],
                "failure_codes": self.failure_codes,
                "decision": self.decision.value,
                "validation_authority": self.validation_authority,
            }
        )


@dataclass(frozen=True, slots=True)
class CatalogSearchGeneration:
    """One complete and atomically activatable semantic-index generation."""

    generation_id: str
    corpus: RuleCorpus
    catalog_digest: str
    semantic_schema_digest: str
    ontology_release_digest: str
    embedding_space_id: str
    embedding_model_version: str
    embedding_dimension: int
    document_digests: tuple[str, ...]
    state: GenerationState = GenerationState.STAGED
    validation_receipt_digest: str | None = None
    activated_at: datetime | None = None
    projection_authority: str = "projection_only"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name, value in (
            ("generation_id", self.generation_id),
            ("embedding_space_id", self.embedding_space_id),
            ("embedding_model_version", self.embedding_model_version),
            ("schema_version", self.schema_version),
        ):
            _bounded_identifier(name, value)
        for name, value in (
            ("catalog_digest", self.catalog_digest),
            ("semantic_schema_digest", self.semantic_schema_digest),
            ("ontology_release_digest", self.ontology_release_digest),
        ):
            _require_digest(name, value)
        _ordered_digests("document_digests", self.document_digests)
        if not 1 <= self.embedding_dimension <= 4096:
            raise ValueError("embedding_dimension MUST be in [1, 4096]")
        if self.validation_receipt_digest is not None:
            _require_digest("validation_receipt_digest", self.validation_receipt_digest)
        if self.activated_at is not None and self.activated_at.tzinfo is None:
            raise ValueError("generation activated_at MUST be timezone-aware")
        if self.state is GenerationState.ACTIVE and (
            self.validation_receipt_digest is None or self.activated_at is None
        ):
            raise ValueError("active generation MUST carry validation and activation evidence")
        if self.state is GenerationState.STAGED and self.activated_at is not None:
            raise ValueError("staged generation MUST NOT carry activated_at")
        if self.projection_authority != "projection_only":
            raise ValueError("search generation MUST remain projection_only")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "generation_id": self.generation_id,
                "corpus": self.corpus.value,
                "catalog_digest": self.catalog_digest,
                "semantic_schema_digest": self.semantic_schema_digest,
                "ontology_release_digest": self.ontology_release_digest,
                "embedding_space_id": self.embedding_space_id,
                "embedding_model_version": self.embedding_model_version,
                "embedding_dimension": self.embedding_dimension,
                "document_digests": self.document_digests,
                "state": self.state.value,
                "validation_receipt_digest": self.validation_receipt_digest,
                "activated_at": _timestamp(self.activated_at),
                "projection_authority": self.projection_authority,
            }
        )


@dataclass(frozen=True, slots=True)
class RetrievalRank:
    rule_ref: str
    rank: int
    components: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        _bounded_identifier("rule_ref", self.rule_ref)
        if self.rank < 1:
            raise ValueError("retrieval rank MUST be positive")
        names = tuple(name for name, _ in self.components)
        if names != tuple(sorted(set(names))):
            raise ValueError("retrieval components MUST be unique and ordered")
        for name, value in self.components:
            _bounded_identifier("retrieval component", name)
            if not math.isfinite(value):
                raise ValueError("retrieval component value MUST be finite")


@dataclass(frozen=True, slots=True)
class CatalogRetrievalReceipt:
    """Read-only proof of one bounded search over an exact catalog generation."""

    query_digest: str
    operation: RetrievalOperation
    corpus: RuleCorpus
    catalog_digest: str
    semantic_state: SemanticAvailability
    results: tuple[RetrievalRank, ...]
    generation_digest: str | None = None
    degraded_reason: str | None = None
    truncated: bool = False
    execution_authority: bool = False
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        _require_digest("query_digest", self.query_digest)
        _require_digest("catalog_digest", self.catalog_digest)
        _bounded_identifier("schema_version", self.schema_version)
        if self.generation_digest is not None:
            _require_digest("generation_digest", self.generation_digest)
        if self.semantic_state is SemanticAvailability.AVAILABLE and self.generation_digest is None:
            raise ValueError("available semantic retrieval MUST name a generation")
        if self.semantic_state in {SemanticAvailability.UNAVAILABLE, SemanticAvailability.DISABLED}:
            if self.generation_digest is not None:
                raise ValueError("unavailable semantic retrieval MUST NOT name a generation")
        if self.semantic_state is not SemanticAvailability.AVAILABLE:
            if self.degraded_reason is None:
                raise ValueError("degraded semantic retrieval MUST include a reason")
            _bounded_identifier("degraded_reason", self.degraded_reason)
        if self.operation in {RetrievalOperation.EVALUATE, RetrievalOperation.ACTION_DRAFT}:
            if self.corpus is not RuleCorpus.ACTIVE:
                raise ValueError("evaluation and action drafts MUST use the active corpus")
        ranks = tuple(item.rank for item in self.results)
        refs = tuple(item.rule_ref for item in self.results)
        if ranks != tuple(range(1, len(self.results) + 1)):
            raise ValueError("retrieval results MUST use contiguous rank order")
        if len(refs) != len(set(refs)):
            raise ValueError("retrieval result Rule refs MUST be unique")
        if self.execution_authority:
            raise ValueError("catalog retrieval receipt MUST NOT carry execution authority")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "query_digest": self.query_digest,
                "operation": self.operation.value,
                "corpus": self.corpus.value,
                "catalog_digest": self.catalog_digest,
                "semantic_state": self.semantic_state.value,
                "generation_digest": self.generation_digest,
                "results": [(item.rule_ref, item.rank, item.components) for item in self.results],
                "degraded_reason": self.degraded_reason,
                "truncated": self.truncated,
                "execution_authority": self.execution_authority,
            }
        )


def query_digest(query: str) -> str:
    """Return a content digest without retaining raw operator text."""

    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("semantic retrieval query MUST be non-empty")
    return "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bounded_identifier(name: str, value: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a bounded ASCII identifier")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a sha256 digest")


def _ordered_digests(name: str, values: tuple[str, ...]) -> None:
    if not values or len(values) > _MAX_VALUES:
        raise ValueError(f"{name} MUST contain 1..{_MAX_VALUES} digests")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be unique and ordered")
    for value in values:
        _require_digest(name, value)


def _ordered_unique(
    name: str,
    values: tuple[str, ...],
    *,
    allow_empty: bool,
    identifiers: bool = True,
) -> None:
    if (not values and not allow_empty) or len(values) > _MAX_VALUES:
        raise ValueError(f"{name} MUST be bounded and non-empty")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be unique and ordered")
    for value in values:
        if identifiers:
            _bounded_identifier(name, value)
        elif not value.strip() or len(value) > _MAX_TEXT or any(ord(char) < 32 for char in value):
            raise ValueError(f"{name} MUST contain bounded text without control characters")


def _normalize_query(value: str) -> str:
    return " ".join(value.casefold().split())


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


__all__ = [
    "CatalogRetrievalReceipt",
    "CatalogSearchGeneration",
    "CohortMetric",
    "GenerationState",
    "RetrievalOperation",
    "RetrievalRank",
    "RuleCorpus",
    "RuleSemanticManifest",
    "RuleSemanticSurface",
    "SemanticAvailability",
    "SurfaceOrigin",
    "SurfaceState",
    "SurfaceValidationReceipt",
    "ValidationDecision",
    "query_digest",
]
