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
    decision_path: str | None = None
    normalized_semantic_digest: str | None = None
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
        allow_unknown = self.corpus is RuleCorpus.DISCOVERY
        _ordered_unique("signal_refs", self.signal_refs, allow_empty=allow_unknown)
        _ordered_unique("property_refs", self.property_refs, allow_empty=allow_unknown)
        _ordered_unique("predicate_refs", self.predicate_refs, allow_empty=True)
        if self.decision_path is not None:
            _bounded_identifier("decision_path", self.decision_path)
        if self.normalized_semantic_digest is not None:
            _require_digest("normalized_semantic_digest", self.normalized_semantic_digest)

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
                "decision_path": self.decision_path,
                "normalized_semantic_digest": self.normalized_semantic_digest,
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


__all__ = [
    "CohortMetric",
    "RuleCorpus",
    "RuleSemanticManifest",
    "RuleSemanticSurface",
    "SurfaceOrigin",
    "SurfaceState",
    "SurfaceValidationReceipt",
    "ValidationDecision",
    "query_digest",
]
