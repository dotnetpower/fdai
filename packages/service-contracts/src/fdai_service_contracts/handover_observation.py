"""Content-free read projections of Operator-owned goals, never knowledge authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_Ref = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:/-]+$")]


class HandoverEvidenceObservation(BaseModel):
    """A reference remains subject to independent admission, ACL, and availability checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_ref: _Ref
    digest: _Ref
    kind: _Ref


class HandoverGoalObservation(BaseModel):
    """Observe a goal revision without copying its subject, text, or acceptance authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    goal_id: _Ref
    assignment_case_id: _Ref | None = None
    agent_name: _Ref
    scope_ref: _Ref
    prompt_ref: _Ref
    priority: Annotated[int, Field(strict=True, ge=1, le=100)]
    state: Literal[
        "not_started", "in_progress", "blocked", "ready_for_review", "accepted", "stale", "declined"
    ]
    revision: Annotated[int, Field(strict=True, ge=1)]
    evidence: Annotated[tuple[HandoverEvidenceObservation, ...], Field(max_length=64)] = Field(
        default_factory=tuple
    )


def handover_observation_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Drop private source columns before crossing the read-only projection boundary."""
    projected = {
        field: record[field] for field in HandoverGoalObservation.model_fields if field in record
    }
    evidence = record.get("evidence", [])
    if isinstance(evidence, list):
        projected["evidence"] = [
            {
                field: item[field]
                for field in HandoverEvidenceObservation.model_fields
                if field in item
            }
            if isinstance(item, Mapping)
            else {}
            for item in evidence
        ]
    return projected


__all__ = ["HandoverEvidenceObservation", "HandoverGoalObservation", "handover_observation_fields"]
