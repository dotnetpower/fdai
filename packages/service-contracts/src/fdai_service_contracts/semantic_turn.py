"""Typed no-authority records for Operator-to-Core semantic turns."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest
from fdai_service_contracts.operator import OperatorRole

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
BoundedId = Annotated[str, Field(min_length=1, max_length=256)]
SEMANTIC_REQUEST_TOPIC = "operator.semantic-turn.requests"
SEMANTIC_PROJECTION_TOPIC = "core.semantic-turn.projections"
SEMANTIC_PHYSICAL_TOPIC = "aw.pantheon.objects"
LOGICAL_TOPIC_FIELD = "_fdai_logical_topic"
_RULE_COMPONENT_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"
_MAX_RULE_CANDIDATES = 50


def multiplexed_consumer_group(group_id: str, logical_topic: str) -> str:
    """Derive one stable physical consumer group for a logical topic."""
    topic_hash = hashlib.sha256(logical_topic.encode("utf-8")).hexdigest()[:12]
    return f"{group_id}.{topic_hash}"


class SemanticTurnDisposition(StrEnum):
    """Terminal outcomes accepted by the semantic conversation boundary."""

    ANSWERED = "answered"
    HELD = "held"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"
    ACTION_DRAFT = "action_draft"
    CANCELLED = "cancelled"


class SemanticTurnPrincipal(QueryContract):
    """Authenticated Operator identity and server-derived roles."""

    subject_id: BoundedId
    roles: Annotated[tuple[OperatorRole, ...], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def _roles_are_unique(self) -> SemanticTurnPrincipal:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("semantic turn principal roles MUST be unique")
        return self


class SemanticPriorTurn(QueryContract):
    """One bounded untrusted history item supplied for context resolution."""

    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=8_000)]


class SemanticTurnRequest(QueryContract):
    """One bounded ordinary-language request with no execution authority."""

    utterance: Annotated[str, Field(min_length=1, max_length=32_000)]
    principal: SemanticTurnPrincipal
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    locale: Annotated[str, Field(min_length=2, max_length=35)]
    purpose: Annotated[str, Field(min_length=1, max_length=128)]
    deadline_at: datetime
    view_context_digest: Digest | None = None
    prior_turns: Annotated[tuple[SemanticPriorTurn, ...], Field(max_length=12)] = ()
    cancelled: bool = False
    execution_authority: Literal[False] = False


class SemanticTurnResult(QueryContract):
    """One evidence-bound terminal semantic result with no action authority."""

    disposition: SemanticTurnDisposition
    reason_code: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")]
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    ontology_release_digest: Digest | None = None
    principal_manifest_digest: Digest | None = None
    plan_digest: Digest | None = None
    execution_receipt_digest: Digest | None = None
    intent_graph: dict[str, Any] | None = None
    intent_graph_evidence: dict[str, Any] | None = None
    evidence_refs: Annotated[tuple[BoundedId, ...], Field(max_length=12)] = ()
    checks_completed: Annotated[int, Field(ge=0, le=64)] = 0
    checks_total: Annotated[int, Field(ge=0, le=64)] = 0
    answer: Annotated[str, Field(min_length=1, max_length=64_000)] | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _evidence_is_consistent(self) -> SemanticTurnResult:
        if self.checks_completed > self.checks_total:
            raise ValueError("semantic checks_completed MUST NOT exceed checks_total")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("semantic evidence_refs MUST be unique")
        exact = (
            self.ontology_release_digest,
            self.principal_manifest_digest,
            self.plan_digest,
            self.execution_receipt_digest,
        )
        if self.disposition is SemanticTurnDisposition.ANSWERED and (
            any(item is None for item in exact)
            or not self.evidence_refs
            or self.checks_total == 0
            or self.checks_completed != self.checks_total
            or self.answer is None
        ):
            raise ValueError("answered semantic results MUST carry complete verified evidence")
        return self


class RuleSearchRank(QueryContract):
    """One bounded rank in a no-authority Rule retrieval receipt."""

    rule_ref: BoundedId
    rank: Annotated[int, Field(ge=1, le=_MAX_RULE_CANDIDATES)]
    components: dict[Annotated[str, Field(pattern=_RULE_COMPONENT_PATTERN)], float] = {}

    @model_validator(mode="after")
    def _components_are_stable(self) -> RuleSearchRank:
        if len(self.components) > 8:
            raise ValueError("Rule search rank MUST have at most 8 components")
        if any(not math.isfinite(value) for value in self.components.values()):
            raise ValueError("Rule search rank components MUST be finite")
        return self


class RuleSearchCandidate(QueryContract):
    """One candidate-only Rule projection with no evaluation or action authority."""

    rule_ref: BoundedId
    rank: Annotated[int, Field(ge=1, le=_MAX_RULE_CANDIDATES)]
    components: dict[Annotated[str, Field(pattern=_RULE_COMPONENT_PATTERN)], float] = {}
    authority: Literal["candidate_only"]

    @model_validator(mode="after")
    def _candidate_components_are_bounded(self) -> RuleSearchCandidate:
        if len(self.components) > 8 or any(
            not math.isfinite(value) for value in self.components.values()
        ):
            raise ValueError("Rule search candidate components MUST be bounded and finite")
        return self


class RuleSearchRequest(QueryContract):
    """Exact bounded query accepted by the Rule search projection read path."""

    query: Annotated[str, Field(min_length=1, max_length=4_096)]
    operation: Literal["discover", "explain", "evaluate", "action_draft"]
    corpus: Literal["active", "discovery"]
    limit: Annotated[int, Field(ge=1, le=20)]

    @model_validator(mode="after")
    def _query_contains_content(self) -> RuleSearchRequest:
        if not self.query.strip():
            raise ValueError("Rule search query MUST contain non-whitespace content")
        return self


class RuleSearchReceipt(QueryContract):
    """Replayable proof of one exact-generation bounded Rule retrieval."""

    schema_version: Literal["1.0.0"]
    query_digest: Digest
    operation: Literal["discover", "explain", "evaluate", "action_draft"]
    corpus: Literal["active", "discovery"]
    catalog_digest: Digest
    semantic_state: Literal["available", "stale", "disabled", "unavailable"]
    generation_digest: Digest | None = None
    results: Annotated[tuple[RuleSearchRank, ...], Field(max_length=_MAX_RULE_CANDIDATES)] = ()
    degraded_reason: Annotated[
        str | None,
        Field(min_length=1, max_length=80, pattern=_RULE_COMPONENT_PATTERN),
    ] = None
    unresolved_terms: Annotated[
        tuple[Annotated[str, Field(pattern=_RULE_COMPONENT_PATTERN)], ...],
        Field(max_length=16),
    ] = ()
    clarification_required: bool = False
    truncated: bool = False
    execution_authority: Literal[False]

    @model_validator(mode="after")
    def _receipt_is_consistent(self) -> RuleSearchReceipt:
        ranks = tuple(item.rank for item in self.results)
        refs = tuple(item.rule_ref for item in self.results)
        if ranks != tuple(range(1, len(self.results) + 1)):
            raise ValueError("Rule search receipt ranks MUST be contiguous")
        if len(refs) != len(set(refs)):
            raise ValueError("Rule search receipt Rule refs MUST be unique")
        if self.semantic_state == "available" and self.generation_digest is None:
            raise ValueError("available Rule search MUST name a generation")
        if self.semantic_state != "available" and self.degraded_reason is None:
            raise ValueError("degraded Rule search MUST include a reason")
        if self.unresolved_terms != tuple(sorted(set(self.unresolved_terms))):
            raise ValueError("Rule search unresolved terms MUST be unique and ordered")
        if self.unresolved_terms and not self.clarification_required:
            raise ValueError("unresolved Rule search terms MUST require clarification")
        if self.clarification_required and self.results:
            raise ValueError("clarification Rule search MUST NOT claim ranked results")
        return self

    @property
    def digest(self) -> str:
        return content_digest(_rule_search_receipt_digest_payload(self))


class RuleSearchProjection(QueryContract):
    """Exact Rule retrieval output projected from Core without action authority."""

    query_digest: Digest
    retrieval_receipt_digest: Digest
    candidates: Annotated[
        tuple[RuleSearchCandidate, ...],
        Field(max_length=_MAX_RULE_CANDIDATES),
    ] = ()
    retrieval_receipt: RuleSearchReceipt
    authority: Literal["candidate_only"]
    execution_authority: Literal[False]

    @model_validator(mode="after")
    def _projection_is_consistent(self) -> RuleSearchProjection:
        if self.query_digest != self.retrieval_receipt.query_digest:
            raise ValueError("Rule search query digest MUST match its receipt")
        if self.retrieval_receipt_digest != self.retrieval_receipt.digest:
            raise ValueError("Rule search receipt digest MUST match canonical receipt content")
        candidate_identity = tuple(
            (item.rule_ref, item.rank, item.components) for item in self.candidates
        )
        receipt_identity = tuple(
            (item.rule_ref, item.rank, item.components) for item in self.retrieval_receipt.results
        )
        if candidate_identity != receipt_identity:
            raise ValueError("Rule search candidates MUST exactly match receipt ranking")
        return self


def rule_search_query_digest(value: Any) -> str:
    """Return the stable digest used to address one exact Rule search projection."""

    request = RuleSearchRequest.model_validate(value)
    return content_digest(request.model_dump(mode="json"))


def _rule_search_receipt_digest_payload(receipt: RuleSearchReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "query_digest": receipt.query_digest,
        "operation": receipt.operation,
        "corpus": receipt.corpus,
        "catalog_digest": receipt.catalog_digest,
        "semantic_state": receipt.semantic_state,
        "generation_digest": receipt.generation_digest,
        "results": [
            [item.rule_ref, item.rank, sorted(item.components.items())] for item in receipt.results
        ],
        "degraded_reason": receipt.degraded_reason,
        "unresolved_terms": list(receipt.unresolved_terms),
        "clarification_required": receipt.clarification_required,
        "truncated": receipt.truncated,
        "execution_authority": receipt.execution_authority,
    }


__all__ = [
    "RuleSearchCandidate",
    "RuleSearchProjection",
    "RuleSearchRank",
    "RuleSearchRequest",
    "RuleSearchReceipt",
    "SemanticPriorTurn",
    "SemanticTurnDisposition",
    "SemanticTurnPrincipal",
    "SemanticTurnRequest",
    "SemanticTurnResult",
    "rule_search_query_digest",
]
