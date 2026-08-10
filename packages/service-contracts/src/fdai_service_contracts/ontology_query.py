"""Versioned, no-authority contracts for ontology-grounded operator queries."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ID_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"
_MAX_JSON_BYTES = 65_536
_MAX_PLAN_NODES = 32
_MAX_GOALS = 16


class QueryContract(BaseModel):
    """Strict immutable base used by ontology-query wire records."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class SemanticOperation(StrEnum):
    SELECT = "select"
    COMPARE = "compare"
    EXPLAIN_CHANGE = "explain_change"
    VALIDATE = "validate"
    ACTION_DRAFT = "action_draft"


class QueryNodeKind(StrEnum):
    OBJECT_SET = "object_set"
    UNION = "union"
    INTERSECTION = "intersection"
    SUBTRACTION = "subtraction"
    ORDER = "order"
    AGGREGATE = "aggregate"
    FUNCTION = "function"
    TOPOLOGY_AT = "topology_at"
    TOPOLOGY_DIFF = "topology_diff"
    METRIC_SERIES = "metric_series"
    EVIDENCE_JOIN = "evidence_join"


class GoalEvidenceMode(StrEnum):
    SCREEN = "screen"
    CATALOG = "catalog"
    OPERATIONAL = "operational"
    WEB = "web"
    MODEL_KNOWLEDGE = "model_knowledge"
    MIXED = "mixed"


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


def canonical_json(value: Any) -> str:
    """Serialize bounded JSON deterministically for replay and digest checks."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError(f"canonical JSON exceeds {_MAX_JSON_BYTES} bytes")
    return encoded


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def parse_json_object(value: str, *, field_name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} MUST contain canonical JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} MUST contain a JSON object")
    if canonical_json(parsed) != value:
        raise ValueError(f"{field_name} MUST be canonical JSON")
    return parsed


class SemanticProblemFrame(QueryContract):
    """Candidate-only semantic decomposition before object or provider lookup."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: SemanticOperation
    subject_constraints: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    measure_concepts: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    temporal_scope_json: Annotated[str, Field(min_length=2, max_length=_MAX_JSON_BYTES)] = "{}"
    output_shape: Annotated[str, Field(pattern=_ID_PATTERN)]
    evidence_requirements: tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...] = ()
    unresolved_terms: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False
    frame_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _canonical(self) -> SemanticProblemFrame:
        temporal = parse_json_object(self.temporal_scope_json, field_name="temporal_scope_json")
        for name, values in (
            ("subject_constraints", self.subject_constraints),
            ("measure_concepts", self.measure_concepts),
            ("evidence_requirements", self.evidence_requirements),
            ("unresolved_terms", self.unresolved_terms),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} MUST be unique")
        expected = content_digest(
            {
                "schema_version": self.schema_version,
                "operation": self.operation.value,
                "subject_constraints": self.subject_constraints,
                "measure_concepts": self.measure_concepts,
                "temporal_scope": temporal,
                "output_shape": self.output_shape,
                "evidence_requirements": self.evidence_requirements,
                "unresolved_terms": self.unresolved_terms,
                "input_digest": self.input_digest,
                "authority": self.authority,
                "execution_authority": False,
            }
        )
        if self.frame_digest != expected:
            raise ValueError("semantic problem frame digest does not match its content")
        return self

    @property
    def temporal_scope(self) -> dict[str, Any]:
        return parse_json_object(self.temporal_scope_json, field_name="temporal_scope_json")


class OntologyQueryNode(QueryContract):
    """One bounded node in a verified ontology query DAG."""

    node_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    kind: QueryNodeKind
    depends_on: tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...] = ()
    arguments_json: Annotated[str, Field(min_length=2, max_length=_MAX_JSON_BYTES)] = "{}"
    output_kind: Annotated[str, Field(pattern=_ID_PATTERN)]

    @model_validator(mode="after")
    def _node_is_canonical(self) -> OntologyQueryNode:
        parse_json_object(self.arguments_json, field_name=f"node {self.node_id} arguments_json")
        if self.node_id in self.depends_on:
            raise ValueError("query node MUST NOT depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("query node dependencies MUST be unique")
        return self

    @property
    def arguments(self) -> dict[str, Any]:
        return parse_json_object(self.arguments_json, field_name="arguments_json")


class OntologyQueryPlan(QueryContract):
    """Exact-release read plan that cannot carry mutation authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    semantic_catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    problem_frame_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    purpose: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    caller_role: Annotated[str, Field(min_length=1, max_length=32)]
    nodes: Annotated[tuple[OntologyQueryNode, ...], Field(min_length=1, max_length=_MAX_PLAN_NODES)]
    output_node_ids: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(min_length=1, max_length=8)
    ]
    execution_authority: Literal[False] = False
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _plan_is_canonical(self) -> OntologyQueryPlan:
        by_id: dict[str, OntologyQueryNode] = {}
        for node in self.nodes:
            if node.node_id in by_id:
                raise ValueError("query node ids MUST be unique")
            missing = set(node.depends_on) - set(by_id)
            if missing:
                raise ValueError(
                    f"query node dependencies MUST precede the node: {sorted(missing)!r}"
                )
            by_id[node.node_id] = node
        if len(self.output_node_ids) != len(set(self.output_node_ids)):
            raise ValueError("output node ids MUST be unique")
        if missing_outputs := set(self.output_node_ids) - set(by_id):
            raise ValueError(f"unknown output node ids: {sorted(missing_outputs)!r}")
        expected = content_digest(
            {
                "schema_version": self.schema_version,
                "ontology_release_digest": self.ontology_release_digest,
                "semantic_catalog_digest": self.semantic_catalog_digest,
                "problem_frame_digest": self.problem_frame_digest,
                "purpose": self.purpose,
                "caller_role": self.caller_role,
                "nodes": [node.model_dump(mode="json") for node in self.nodes],
                "output_node_ids": self.output_node_ids,
                "execution_authority": False,
            }
        )
        if self.plan_digest != expected:
            raise ValueError("ontology query plan digest does not match its content")
        return self


class IntentGoal(QueryContract):
    goal_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    intent: Annotated[str, Field(pattern=_ID_PATTERN)]
    capability: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None
    arguments_json: Annotated[str, Field(min_length=2, max_length=_MAX_JSON_BYTES)] = "{}"
    depends_on: tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...] = ()
    evidence_mode: GoalEvidenceMode
    freshness_required: bool
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()

    @model_validator(mode="after")
    def _goal_is_bounded(self) -> IntentGoal:
        parse_json_object(self.arguments_json, field_name=f"goal {self.goal_id} arguments_json")
        if not math.isfinite(self.confidence):
            raise ValueError("goal confidence MUST be finite")
        if self.goal_id in self.depends_on:
            raise ValueError("intent goal MUST NOT depend on itself")
        return self


class IntentGraph(QueryContract):
    schema_version: Literal["2.0.0"] = "2.0.0"
    problem_frame_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    goals: Annotated[tuple[IntentGoal, ...], Field(min_length=1, max_length=_MAX_GOALS)]
    clarification: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    action_posture: Literal["advise_only", "draft_only"]

    @model_validator(mode="after")
    def _graph_is_valid(self) -> IntentGraph:
        if not math.isfinite(self.confidence):
            raise ValueError("intent graph confidence MUST be finite")
        seen: set[str] = set()
        for goal in self.goals:
            if goal.goal_id in seen:
                raise ValueError("intent goal ids MUST be unique")
            if missing := set(goal.depends_on) - seen:
                raise ValueError(f"intent goal dependencies MUST precede goal: {sorted(missing)!r}")
            seen.add(goal.goal_id)
        return self


class GoalTaskReceipt(QueryContract):
    task_id: Annotated[str, Field(min_length=1, max_length=256)]
    goal_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    intent: Annotated[str, Field(pattern=_ID_PATTERN)]
    capability: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None
    evidence_mode: GoalEvidenceMode
    status: TaskStatus
    duration_ms: int = Field(ge=0, le=86_400_000)
    depends_on: tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...] = ()
    reason: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    blocked_by: tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...] = ()
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def _times_are_valid(self) -> GoalTaskReceipt:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("task receipt times MUST be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("task completion MUST NOT precede start")
        if self.status is TaskStatus.SKIPPED and not self.blocked_by:
            raise ValueError("skipped task MUST name blocked_by goals")
        return self


class StructuralCoverageReceipt(QueryContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    principal_scope_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    readable_declaration_count: int = Field(ge=0)
    descriptor_count: int = Field(ge=0)
    unavailable_declaration_ids: tuple[
        Annotated[str, Field(min_length=1, max_length=160)], ...
    ] = ()
    manifest_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    complete: bool
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _coverage_is_consistent(self) -> StructuralCoverageReceipt:
        unavailable = len(self.unavailable_declaration_ids)
        complete = self.descriptor_count + unavailable == self.readable_declaration_count
        if self.complete != complete:
            raise ValueError("structural coverage complete flag does not match counts")
        if len(self.unavailable_declaration_ids) != len(set(self.unavailable_declaration_ids)):
            raise ValueError("unavailable declaration ids MUST be unique")
        expected = content_digest(
            {
                "schema_version": self.schema_version,
                "ontology_release_digest": self.ontology_release_digest,
                "principal_scope_digest": self.principal_scope_digest,
                "readable_declaration_count": self.readable_declaration_count,
                "descriptor_count": self.descriptor_count,
                "unavailable_declaration_ids": self.unavailable_declaration_ids,
                "manifest_digest": self.manifest_digest,
                "complete": self.complete,
            }
        )
        if self.receipt_digest != expected:
            raise ValueError("structural coverage receipt digest does not match its content")
        return self


__all__ = [
    "GoalEvidenceMode",
    "GoalTaskReceipt",
    "IntentGoal",
    "IntentGraph",
    "OntologyQueryNode",
    "OntologyQueryPlan",
    "QueryNodeKind",
    "SemanticOperation",
    "SemanticProblemFrame",
    "StructuralCoverageReceipt",
    "TaskStatus",
    "canonical_json",
    "content_digest",
]
