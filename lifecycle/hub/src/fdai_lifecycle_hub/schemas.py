"""JSON boundary: request bodies, operator input files, and the JSON form of Hub records."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self, assert_never

from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from fdai_lifecycle_hub.domain import (
    CandidateCheck,
    Configuration,
    Evaluation,
    Installation,
    Issued,
    NoEligibleRelease,
    PlanOutcome,
    ReportedState,
    Settings,
    Unchanged,
    UpToDate,
    Waiting,
)

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

installation_json = TypeAdapter(Installation)
settings_json = TypeAdapter(Settings)
configuration_json = TypeAdapter(Configuration)
reported_state_json = TypeAdapter(ReportedState)
suppressions_json = TypeAdapter(tuple[SuppressionWindow, ...])
checks_json = TypeAdapter(tuple[CandidateCheck, ...])
evaluation_json = TypeAdapter(Evaluation)


class PlanReport(BaseModel):
    """What the installation agent reports after one attempt at one Plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int = Field(ge=1)
    outcome: Literal["dry-run-admitted", "rejected"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    exact_plan_digest: Digest | None
    summary: str = Field(max_length=2000)
    reported_at: AwareDatetime

    @model_validator(mode="after")
    def _admitted_names_the_plan_bytes(self) -> Self:
        if self.outcome == "dry-run-admitted" and self.exact_plan_digest is None:
            raise ValueError("an admitted report must carry exact_plan_digest")
        return self


def outcome_record(outcome: PlanOutcome) -> dict[str, Any]:
    record: dict[str, Any] = {
        "outcome": outcome.kind,
        "checks": checks_json.dump_python(outcome.checks, mode="json"),
    }
    match outcome:
        case Issued(plan=plan) | Unchanged(plan=plan):
            record |= {"plan_id": plan.plan_id, "target": plan.target_release_id}
        case Waiting(release_id=release_id):
            record |= {"target": release_id}
        case NoEligibleRelease() | UpToDate():
            pass
        case _:
            assert_never(outcome)
    return record
