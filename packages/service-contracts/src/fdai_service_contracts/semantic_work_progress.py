"""Presentation-only work progress contracts for one semantic turn.

These records describe how much read work a turn planned and how much of its enforcing budget it
used. They never carry evidence, instructions, or execution authority: a density pin selects
presentation, budget telemetry reports measured consumption, and a context receipt names an
operator preference that shaped the turn without becoming evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from fdai_service_contracts.ontology_query import QueryContract, canonical_json
from fdai_service_contracts.semantic_turn import BoundedId, SemanticConversationModelTier

MAX_WORK_PROGRESS_WAVES = 8
MAX_WORK_PROGRESS_PLANNED_READS = 64
MAX_TURN_BUDGET_MEASURE = 10_000_000
MAX_CONTEXT_RECEIPTS = 4
CONVERSATION_MODEL_TIER_RECEIPT_ID = "operator-preference:conversation-model-tier"

WorkProgressDensity = Literal["compact", "procedural"]
TurnBudgetExhaustion = Literal["deadline", "model_calls", "tokens", "rate_limited", "cancelled"]
ContextReceiptFreshness = Literal["fresh", "stale", "superseded"]
_Count = Annotated[int, Field(ge=0, le=MAX_TURN_BUDGET_MEASURE, strict=True)]


def _integer_schema_version(value: object) -> object:
    if type(value) is not int:
        raise ValueError("work progress schema_version MUST be the integer 1")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} MUST be timezone-aware")
    return value


class WorkProgressShape(QueryContract):
    """Server-pinned presentation density for one compiled read plan."""

    schema_version: Literal[1] = 1
    density: WorkProgressDensity
    waves: Annotated[int, Field(ge=1, le=MAX_WORK_PROGRESS_WAVES, strict=True)]
    planned_reads: Annotated[int, Field(ge=0, le=MAX_WORK_PROGRESS_PLANNED_READS, strict=True)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _integer_version(cls, value: object) -> object:
        return _integer_schema_version(value)

    @model_validator(mode="after")
    def _compact_is_one_read(self) -> WorkProgressShape:
        if self.density == "compact" and (self.waves != 1 or self.planned_reads > 1):
            raise ValueError("a compact work progress shape describes at most one read in one wave")
        return self


class TurnBudgetMeasure(QueryContract):
    """One measure of the enforcing turn budget."""

    used: _Count
    reserved: _Count
    maximum: Annotated[int, Field(ge=1, le=MAX_TURN_BUDGET_MEASURE, strict=True)]

    @property
    def exceeded(self) -> bool:
        return self.used + self.reserved > self.maximum


class TurnBudgetTelemetry(QueryContract):
    """Measured consumption of the enforcing turn budget at settle.

    A measure may end above its maximum only when it is the exhaustion reason: observed tokens
    replace their reservation before the check, and a deadline is noticed after it passes. Model
    calls are reserved before each call, so they never exceed their maximum.
    """

    schema_version: Literal[1] = 1
    model_calls: TurnBudgetMeasure
    tokens: TurnBudgetMeasure
    elapsed_ms: TurnBudgetMeasure
    as_of: datetime
    complete: Annotated[bool, Field(strict=True)]
    exhaustion_reason: TurnBudgetExhaustion | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def _integer_version(cls, value: object) -> object:
        return _integer_schema_version(value)

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @model_validator(mode="after")
    def _measures_are_consistent(self) -> TurnBudgetTelemetry:
        _aware(self.as_of, "turn budget as_of")
        if self.model_calls.exceeded:
            raise ValueError("model calls MUST NOT exceed their maximum")
        if self.tokens.exceeded and self.exhaustion_reason != "tokens":
            raise ValueError("tokens may exceed their maximum only when tokens ended the turn")
        if self.elapsed_ms.reserved != 0:
            raise ValueError("elapsed time cannot be reserved")
        if self.elapsed_ms.exceeded and self.exhaustion_reason != "deadline":
            raise ValueError("elapsed time may exceed its maximum only when the deadline passed")
        return self


def context_receipt_digest(preference: str, value: str) -> str:
    """Return the bare SHA-256 hex digest that identifies one applied preference value."""

    encoded = canonical_json({"preference": preference, "value": value}).encode()
    return hashlib.sha256(encoded).hexdigest()


class SemanticContextReceipt(QueryContract):
    """One operator preference that shaped a turn. It is context, never evidence or instructions."""

    receipt_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9:._-]{0,127}$")]
    kind: Literal["operator_preference"] = "operator_preference"
    preference: Literal["conversation_model_tier"]
    value: SemanticConversationModelTier
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    observed_at: datetime
    freshness: ContextReceiptFreshness

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @model_validator(mode="after")
    def _digest_binds_value(self) -> SemanticContextReceipt:
        _aware(self.observed_at, "context receipt observed_at")
        if self.digest != context_receipt_digest(self.preference, self.value.value):
            raise ValueError("context receipt digest does not match its preference value")
        return self


def conversation_model_tier_receipt(
    tier: SemanticConversationModelTier,
    *,
    observed_at: datetime,
) -> SemanticContextReceipt:
    """Describe the per-conversation model tier carried by the request that Core applied."""

    return SemanticContextReceipt(
        receipt_id=CONVERSATION_MODEL_TIER_RECEIPT_ID,
        preference="conversation_model_tier",
        value=tier,
        digest=context_receipt_digest("conversation_model_tier", tier.value),
        observed_at=observed_at,
        freshness="fresh",
    )


def parse_context_receipts(raw: object) -> tuple[SemanticContextReceipt, ...]:
    """Validate one bounded receipt list with unique identities or raise ``ValueError``."""

    if not isinstance(raw, list | tuple) or len(raw) > MAX_CONTEXT_RECEIPTS:
        raise ValueError(f"context receipts MUST be a list of at most {MAX_CONTEXT_RECEIPTS}")
    try:
        receipts = tuple(SemanticContextReceipt.model_validate(item) for item in raw)
    except ValidationError as exc:
        raise ValueError("context receipt is malformed") from exc
    if len({receipt.receipt_id for receipt in receipts}) != len(receipts):
        raise ValueError("context receipt identities MUST be unique")
    return receipts


class SemanticWorkProgress(QueryContract):
    """One plan-time pin published before the pinned plan's first node progress."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_kind: Literal["work_progress_shape"] = "work_progress_shape"
    request_id: BoundedId
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    progress_sequence: Annotated[int, Field(ge=1, le=256)]
    work_progress_shape: WorkProgressShape
    execution_authority: Literal[False] = False


def derive_work_progress_shape(
    nodes: Iterable[tuple[str, Sequence[str]]],
) -> WorkProgressShape | None:
    """Derive the pin for one compiled read plan whose nodes follow their dependencies.

    Waves are the longest dependency depth, matching an executor that finishes every ready node
    before it starts the next wave. ``None`` means the plan cannot be pinned within the contract
    bounds, so each channel derives density from its observations instead.
    """

    depth: dict[str, int] = {}
    for node_id, depends_on in nodes:
        if node_id in depth or any(dependency not in depth for dependency in depends_on):
            return None
        depth[node_id] = 1 + max((depth[dependency] for dependency in depends_on), default=0)
    if not depth or len(depth) > MAX_WORK_PROGRESS_PLANNED_READS:
        return None
    waves = max(depth.values())
    if waves > MAX_WORK_PROGRESS_WAVES:
        return None
    return WorkProgressShape(
        density="compact" if len(depth) == 1 else "procedural",
        waves=waves,
        planned_reads=len(depth),
    )


__all__ = [
    "CONVERSATION_MODEL_TIER_RECEIPT_ID",
    "MAX_CONTEXT_RECEIPTS",
    "ContextReceiptFreshness",
    "SemanticContextReceipt",
    "SemanticWorkProgress",
    "TurnBudgetExhaustion",
    "TurnBudgetMeasure",
    "TurnBudgetTelemetry",
    "WorkProgressDensity",
    "WorkProgressShape",
    "context_receipt_digest",
    "conversation_model_tier_receipt",
    "derive_work_progress_shape",
    "parse_context_receipts",
]
