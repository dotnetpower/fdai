"""Presentation-only progress of one semantic planning model call.

A record states that a reviewed call stage sent a model request, which deployment served it, how
long it took, and how it ended. It never carries a prompt, a response, quoted question text, or a
model-stated reason, and it grants no evidence or execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract
from fdai_service_contracts.semantic_turn import BoundedId

MAX_MODEL_CALLS_PER_TURN = 32
MAX_MODEL_CALL_UPDATES_PER_TURN = MAX_MODEL_CALLS_PER_TURN * 2

ModelCallStage = Literal[
    "preflight",
    "judgment",
    "form",
    "blind_review",
    "concept_chooser",
    "direction_reader",
    "ambiguity_reader",
    "frame",
    "plan",
]
ModelCallStatus = Literal["running", "completed", "failed"]
_TokenCount = Annotated[int, Field(ge=0, le=10_000_000, strict=True)]


class SemanticModelCallProgress(QueryContract):
    """One start or end of a planning model call, published on the best-effort progress topic."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_kind: Literal["model_call_progress"] = "model_call_progress"
    request_id: BoundedId
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    progress_sequence: Annotated[int, Field(ge=1, le=256)]
    call_index: Annotated[int, Field(ge=1, le=MAX_MODEL_CALLS_PER_TURN)]
    stage: ModelCallStage
    status: ModelCallStatus
    model: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")] | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None
    prompt_tokens: _TokenCount | None = None
    completion_tokens: _TokenCount | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _lifecycle_is_consistent(self) -> SemanticModelCallProgress:
        for value, name in ((self.started_at, "started_at"), (self.completed_at, "completed_at")):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"model call progress {name} MUST be timezone-aware")
        ended = self.status != "running"
        if ended != (self.completed_at is not None) or ended != (self.duration_ms is not None):
            raise ValueError("only an ended model call carries its completion time and duration")
        if not ended and (self.prompt_tokens is not None or self.completion_tokens is not None):
            raise ValueError("a running model call has no measured token counts")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("model call progress MUST NOT end before it starts")
        return self


__all__ = [
    "MAX_MODEL_CALLS_PER_TURN",
    "MAX_MODEL_CALL_UPDATES_PER_TURN",
    "ModelCallStage",
    "ModelCallStatus",
    "SemanticModelCallProgress",
]
