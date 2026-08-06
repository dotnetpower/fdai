"""Privacy-safe attribution and challenger intake for failed Rule queries."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$")
_RETRIEVAL_OWNED = frozenset(
    {
        "missing_concept",
        "mapping_gap",
        "ranking_error",
        "ambiguity",
    }
)


class RetrievalFailureLayer(StrEnum):
    STALE_GENERATION = "stale_generation"
    MISSING_CONCEPT = "missing_concept"
    MAPPING_GAP = "mapping_gap"
    RANKING_ERROR = "ranking_error"
    AMBIGUITY = "ambiguity"
    INACTIVE_RULE = "inactive_rule"
    PROVIDER_EVIDENCE = "provider_evidence"
    PRESENTATION = "presentation"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class QueryFailureEvidence:
    """Redacted deployment-local evidence for one terminal retrieval failure."""

    attempt_id: str
    query_digest: str
    principal_scope_digest: str
    catalog_digest: str
    reason_code: str
    layer: RetrievalFailureLayer
    reproduced: bool
    evidence_refs: tuple[str, ...]
    exact_target_rule_ref: str | None = None
    user_correction_ref: str | None = None
    raw_text_retained: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("attempt_id", self.attempt_id),
            ("reason_code", self.reason_code),
        ):
            _identifier(name, value)
        for name, value in (
            ("query_digest", self.query_digest),
            ("principal_scope_digest", self.principal_scope_digest),
            ("catalog_digest", self.catalog_digest),
        ):
            _digest(name, value)
        if not self.evidence_refs or self.evidence_refs != tuple(sorted(set(self.evidence_refs))):
            raise ValueError("query failure evidence refs MUST be non-empty, unique, and ordered")
        for value in self.evidence_refs:
            _identifier("evidence_ref", value)
        if self.exact_target_rule_ref is not None:
            _identifier("exact_target_rule_ref", self.exact_target_rule_ref)
        if self.user_correction_ref is not None:
            _identifier("user_correction_ref", self.user_correction_ref)
        if self.raw_text_retained:
            raise ValueError("semantic feedback MUST NOT retain raw operator text")


@dataclass(frozen=True, slots=True)
class SemanticFeedbackCandidate:
    """Inert challenger candidate with no ranking or promotion authority."""

    candidate_id: str
    attempt_id: str
    query_digest: str
    target_rule_ref: str
    failure_layer: RetrievalFailureLayer
    evidence_refs: tuple[str, ...]
    mode: str = "challenger_only"
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("attempt_id", self.attempt_id),
            ("target_rule_ref", self.target_rule_ref),
        ):
            _identifier(name, value)
        _digest("query_digest", self.query_digest)
        if self.mode != "challenger_only" or self.promotion_authority:
            raise ValueError("semantic feedback candidate MUST remain challenger_only")


class SemanticFeedbackCandidateSink(Protocol):
    """Durable sink used by Norns after deterministic feedback attribution."""

    async def put(self, candidate: SemanticFeedbackCandidate) -> bool: ...


def query_failure_evidence_from_mapping(raw: Mapping[str, Any]) -> QueryFailureEvidence:
    """Decode one exact privacy-safe failure record from a typed context event."""

    required = {
        "attempt_id",
        "query_digest",
        "principal_scope_digest",
        "catalog_digest",
        "reason_code",
        "layer",
        "reproduced",
        "evidence_refs",
    }
    optional = {"exact_target_rule_ref", "user_correction_ref", "raw_text_retained"}
    fields = set(raw)
    if fields - required - optional:
        raise ValueError("query failure evidence contains unknown fields")
    if required - fields:
        raise ValueError("query failure evidence is missing required fields")
    reproduced = raw["reproduced"]
    if not isinstance(reproduced, bool):
        raise ValueError("query failure evidence reproduced MUST be a boolean")
    evidence_refs = raw["evidence_refs"]
    if not isinstance(evidence_refs, list) or any(
        not isinstance(item, str) for item in evidence_refs
    ):
        raise ValueError("query failure evidence refs MUST be an array of strings")
    raw_text_retained = raw.get("raw_text_retained", False)
    if not isinstance(raw_text_retained, bool):
        raise ValueError("query failure raw_text_retained MUST be a boolean")
    return QueryFailureEvidence(
        attempt_id=_text(raw, "attempt_id"),
        query_digest=_text(raw, "query_digest"),
        principal_scope_digest=_text(raw, "principal_scope_digest"),
        catalog_digest=_text(raw, "catalog_digest"),
        reason_code=_text(raw, "reason_code"),
        layer=RetrievalFailureLayer(_text(raw, "layer")),
        reproduced=reproduced,
        evidence_refs=tuple(evidence_refs),
        exact_target_rule_ref=_optional_text(raw, "exact_target_rule_ref"),
        user_correction_ref=_optional_text(raw, "user_correction_ref"),
        raw_text_retained=raw_text_retained,
    )


def build_feedback_candidate(evidence: QueryFailureEvidence) -> SemanticFeedbackCandidate:
    """Create a challenger only for reproduced, exact, retrieval-owned failures."""

    if evidence.layer.value not in _RETRIEVAL_OWNED:
        raise ValueError("failure is not owned by semantic retrieval")
    if not evidence.reproduced:
        raise ValueError("semantic retrieval failure MUST be reproduced")
    if evidence.exact_target_rule_ref is None:
        raise ValueError("semantic feedback requires an exact target Rule")
    payload = {
        "attempt_id": evidence.attempt_id,
        "query_digest": evidence.query_digest,
        "target_rule_ref": evidence.exact_target_rule_ref,
        "failure_layer": evidence.layer.value,
        "evidence_refs": evidence.evidence_refs,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    candidate_id = "semantic-feedback:" + hashlib.sha256(encoded).hexdigest()
    return SemanticFeedbackCandidate(
        candidate_id=candidate_id,
        attempt_id=evidence.attempt_id,
        query_digest=evidence.query_digest,
        target_rule_ref=evidence.exact_target_rule_ref,
        failure_layer=evidence.layer,
        evidence_refs=evidence.evidence_refs,
    )


def _identifier(name: str, value: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a bounded ASCII identifier")


def _digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a sha256 digest")


def _text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"query failure evidence {name} MUST be a non-empty string")
    return value


def _optional_text(raw: Mapping[str, Any], name: str) -> str | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"query failure evidence {name} MUST be null or non-empty string")
    return value


__all__ = [
    "QueryFailureEvidence",
    "RetrievalFailureLayer",
    "SemanticFeedbackCandidate",
    "SemanticFeedbackCandidateSink",
    "build_feedback_candidate",
    "query_failure_evidence_from_mapping",
]
