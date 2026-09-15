"""Immutable ownership-only case records and digest-bound H10 review observations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fdai_service_contracts.scoped_duty import ExactRef, ScopedDutyRequest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.core.human_assignment.scoped_duties import (
    DutySubject,
    DutySubjectKind,
    ScopedDutyBinding,
    ScopedDutyInput,
    canonical_digest,
    canonical_json,
    utc_instant,
)
from fdai.core.stewardship import Duty

Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ScopedDutyState = Literal[
    "draft",
    "pending_review",
    "approved",
    "ownership_pr_open",
    "ownership_merged",
    "rejected",
]
SCOPED_CASE_PREFIX = "human_assignment:scoped-case:"


class ScopedDutyCommand(BaseModel):
    """An exact authenticated command receipt inside the same CAS as its result."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal_id: Annotated[str, Field(pattern=r"^operator-[0-9a-f]{32}$")]
    request_digest: Digest
    result_state: ScopedDutyState | None = None
    result_revision: Annotated[int, Field(strict=True, ge=1)] | None = None

    @model_validator(mode="after")
    def exact_command_identity(self) -> ScopedDutyCommand:
        """A receipt id cannot be reused with a different authenticated command digest."""
        if self.proposal_id != "operator-" + self.request_digest[:32]:
            raise ValueError("scoped command identity does not match its digest")
        if (self.result_state is None) != (self.result_revision is None):
            raise ValueError("scoped command result state and revision MUST be retained together")
        return self

    def materialized(self, state: ScopedDutyState, revision: int) -> ScopedDutyCommand:
        """Pin the command's original transition inside the case CAS, not a later snapshot."""
        if self.result_state is not None or self.result_revision is not None:
            raise ValueError("scoped command result is immutable")
        return ScopedDutyCommand.model_validate(
            {
                **self.model_dump(),
                "result_state": state,
                "result_revision": revision,
            }
        )


class ScopedDutyReview(BaseModel):
    """Independent human review of the exact retained plan, never an IAM approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewer_ref: ExactRef
    decision: Literal["approve", "reject"]
    plan_digest: Digest
    reviewed_at: datetime

    @model_validator(mode="after")
    def exact_reviewer(self) -> ScopedDutyReview:
        """Reject normalized-identity ambiguity and timestamps without an explicit offset."""
        if self.reviewer_ref != self.reviewer_ref.casefold():
            raise ValueError("scoped review identity MUST already be normalized")
        utc_instant(self.reviewed_at)
        return self


class ScopedDutyCase(BaseModel):
    """Core-owned reviewed duty intent; only a verified artifact merge establishes ownership.

    No case state can mean active IAM. Plans are stored as canonical immutable text so
    a caller cannot edit a nested dict after validation. Projection always rereads sources.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["scoped_duty_case"] = "scoped_duty_case"
    case_id: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")]
    requester_ref: ExactRef
    idempotency_key: ExactRef
    justification: Annotated[str, Field(strict=True, min_length=20, max_length=2000)]
    request: ScopedDutyRequest
    state: ScopedDutyState
    revision: Annotated[int, Field(strict=True, ge=1)]
    plan_json: Annotated[str, Field(strict=True, min_length=1, max_length=1_048_576)]
    created_at: datetime
    updated_at: datetime
    reviews: Annotated[tuple[ScopedDutyReview, ...], Field(max_length=2)] = ()
    commands: Annotated[tuple[ScopedDutyCommand, ...], Field(min_length=1, max_length=100)]
    pr_ref: ExactRef | None = None
    candidate_digest: Digest | None = None
    merge_commit_sha: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")] | None = None
    execution_authority: Literal[False] = False

    @field_validator("execution_authority", mode="before")
    @classmethod
    def explicit_no_authority(cls, value: object) -> object:
        """Reject integer and string coercion at the persisted no-authority boundary."""
        if value is not False:
            raise ValueError("scoped case execution authority MUST be explicitly false")
        return value

    @model_validator(mode="after")
    def consistent_record(self) -> ScopedDutyCase:
        """Validate source binding, review separation, state, and immutable receipt consistency."""
        if (
            self.requester_ref != self.requester_ref.casefold()
            or self.execution_authority is not False
        ):
            raise ValueError("scoped case requires canonical identity and no execution authority")
        if utc_instant(self.updated_at) < utc_instant(self.created_at):
            raise ValueError("scoped case time cannot move backwards")
        plan = self.plan()
        if (
            plan.get("kind") != "scoped_duty_review"
            or plan.get("schema_version") != "1.0.0"
            or plan.get("execution_authority") is not False
            or plan.get("review_required") is not True
            or plan.get("input_digest") != scoped_input(self.request).digest
            or plan.get("source_revision") != self.request.source_revision
            or plan.get("digest")
            != canonical_digest({k: v for k, v in plan.items() if k != "digest"})
        ):
            raise ValueError("scoped case plan does not match its immutable request")
        reviewers = {review.reviewer_ref for review in self.reviews}
        if len(reviewers) != len(self.reviews) or self.requester_ref in reviewers:
            raise ValueError("scoped case reviewers MUST be distinct and independent")
        if any(review.plan_digest != plan["digest"] for review in self.reviews):
            raise ValueError("scoped case review does not bind the retained plan")
        approved = len(self.reviews) == 2 and all(row.decision == "approve" for row in self.reviews)
        if approved != (self.state in {"approved", "ownership_pr_open", "ownership_merged"}):
            raise ValueError("scoped ownership requires two independent Owner reviews")
        if self.state == "draft" and self.reviews:
            raise ValueError("a scoped draft cannot carry a human review")
        if any(row.decision == "reject" for row in self.reviews) != (self.state == "rejected"):
            raise ValueError("scoped rejection MUST remain terminal")
        if self.state in {"ownership_pr_open", "ownership_merged"} and not (
            self.pr_ref and self.candidate_digest
        ):
            raise ValueError("scoped ownership requires its exact review artifact")
        if (self.state == "ownership_merged") != (self.merge_commit_sha is not None):
            raise ValueError("scoped ownership requires a separately verified merge")
        if len({command.proposal_id for command in self.commands}) != len(self.commands):
            raise ValueError("scoped case command receipts MUST be unique")
        if any(
            command.result_state is None
            or command.result_revision is None
            or command.result_revision > self.revision
            for command in self.commands
        ):
            raise ValueError("scoped case MUST retain each original materialized command result")
        return self

    def command_receipt(self, command: ScopedDutyCommand) -> ScopedDutyCommand | None:
        """Find exact command identity; a matching id with a different payload is a conflict."""
        for retained in self.commands:
            if retained.proposal_id == command.proposal_id:
                if retained.request_digest != command.request_digest:
                    raise ValueError("scoped command payload differs from its retained receipt")
                return retained
        return None

    def plan(self) -> dict[str, Any]:
        """Decode a fresh copy of bounded canonical plan text; callers cannot mutate this case."""
        value: object = json.loads(self.plan_json)
        if not isinstance(value, dict) or canonical_json(value) + "\n" != self.plan_json:
            raise ValueError("scoped case plan MUST be one canonical object")
        return value


def scoped_input(request: ScopedDutyRequest) -> ScopedDutyInput:
    """Convert the shared wire declaration to the Core planner's validated immutable types."""
    return ScopedDutyInput(
        request.source_revision,
        tuple(
            ScopedDutyBinding(
                DutySubject(DutySubjectKind(row.subject.kind), row.subject.ref),
                row.agent_name,
                row.scope_ref,
                Duty(row.duty),
                row.effective_from,
                row.effective_until,
                DutySubject(DutySubjectKind.PERSON, row.fallback.ref) if row.fallback else None,
            )
            for row in request.bindings
        ),
        request.supersedes_case_id,
    )


def resolved_targets_digest(plan: dict[str, Any]) -> str:
    """Bind reviewed declarations and people, excluding only changing observation timestamps.

    Freshness is independently rechecked by the current planner. A changed source revision,
    person, fallback, coverage, or held reason cannot reuse a prior human review.
    """
    return canonical_digest(
        {
            "input_digest": plan["input_digest"],
            "policy": plan["policy"],
            "coverage": plan["coverage"],
            "bindings": [
                {
                    "binding": row["binding"],
                    "scope": row["scope"],
                    "held_reason": row["held_reason"],
                    "schedule_failure": row["schedule_failure"],
                    "subject": row["resolution"]["subject"] if row["resolution"] else None,
                    "people": row["resolution"]["people"] if row["resolution"] else None,
                }
                for row in plan["bindings"]
            ],
        }
    )


def require_current_plan(plan: dict[str, Any], *, at: datetime) -> None:
    """Recheck the current observation after reviewer I/O, never reuse its expired window."""
    instant = utc_instant(at)
    checked = utc_instant(datetime.fromisoformat(plan["checked_at"]))
    max_age = timedelta(microseconds=plan["policy"]["max_resolution_age_microseconds"])
    if instant < checked:
        raise ValueError("scoped duty observation expired or clock moved backwards")
    for row in plan["bindings"]:
        declaration = row["binding"]
        start = utc_instant(datetime.fromisoformat(declaration["effective_from"]))
        end = utc_instant(datetime.fromisoformat(declaration["effective_until"]))
        if (start <= checked < end) != (start <= instant < end):
            raise ValueError("scoped duty observation expired across a duty transition")
        resolution = row["resolution"]
        if row["held_reason"] is not None or resolution is None:
            continue
        observed = utc_instant(datetime.fromisoformat(resolution["observed_at"]))
        until = utc_instant(datetime.fromisoformat(resolution["valid_until"]))
        if not observed <= instant < until or instant - observed >= max_age:
            raise ValueError("scoped duty observation expired during review")


def plan_expiry(plan: dict[str, Any]) -> datetime:
    """Cap projection validity at every source expiry and next declared duty transition."""
    checked = utc_instant(datetime.fromisoformat(plan["checked_at"]))
    max_age = timedelta(microseconds=plan["policy"]["max_resolution_age_microseconds"])
    deadlines = [checked + max_age]
    for row in plan["bindings"]:
        binding = row["binding"]
        for name in ("effective_from", "effective_until"):
            instant = utc_instant(datetime.fromisoformat(binding[name]))
            if instant > checked:
                deadlines.append(instant)
        resolution = row["resolution"]
        if row["held_reason"] is None and resolution is not None:
            deadlines.extend(
                (
                    utc_instant(datetime.fromisoformat(resolution["valid_until"])),
                    utc_instant(datetime.fromisoformat(resolution["observed_at"])) + max_age,
                )
            )
    return min(deadlines)


__all__ = [
    "SCOPED_CASE_PREFIX",
    "ScopedDutyCase",
    "ScopedDutyCommand",
    "ScopedDutyReview",
    "ScopedDutyState",
    "plan_expiry",
    "require_current_plan",
    "resolved_targets_digest",
    "scoped_input",
]
