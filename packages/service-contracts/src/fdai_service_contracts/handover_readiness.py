"""Bounded observed lifecycle readiness; source checks never certify deployment or promotion."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HANDOVER_READINESS_KEY = "human_assignment:readiness:current"
_Count = Annotated[int, Field(strict=True, ge=0)]


class HandoverReadinessReport(BaseModel):
    """Content-free, expiry-bound sample with explicit source and external completion blockers."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: Annotated[int, Field(strict=True, ge=1)]
    observed_at: datetime
    expires_at: datetime
    mode: Literal["shadow"] = "shadow"
    execution_authority: Literal[False] = False
    operationally_ready: Literal[False] = False
    enabled: Annotated[bool, Field(strict=True)]
    sample_limit: Annotated[int, Field(strict=True, ge=1, le=1000)]
    cases_observed: _Count
    cases_total: _Count
    cases_invalid: _Count
    cases_by_state: dict[str, _Count]
    knowledge_observed: _Count
    knowledge_total: _Count
    knowledge_invalid: _Count
    knowledge_by_disposition: dict[str, _Count]
    partial: Annotated[bool, Field(strict=True)]
    convergence_samples: _Count
    mean_effect_interval_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    alerts: tuple[str, ...]
    source_gaps: tuple[str, ...]
    external_blockers: tuple[str, ...]

    @model_validator(mode="after")
    def _bounded_snapshot(self) -> HandoverReadinessReport:
        if self.observed_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("handover readiness timestamps MUST include a timezone")
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(hours=1):
            raise ValueError("handover readiness expiry MUST be bounded")
        for observed, total, invalid, counts in (
            (self.cases_observed, self.cases_total, self.cases_invalid, self.cases_by_state),
            (
                self.knowledge_observed,
                self.knowledge_total,
                self.knowledge_invalid,
                self.knowledge_by_disposition,
            ),
        ):
            if (
                observed > self.sample_limit
                or observed > total
                or invalid + sum(counts.values()) != observed
            ):
                raise ValueError("handover readiness counts are inconsistent")
        if self.partial != (
            self.cases_observed < self.cases_total or self.knowledge_observed < self.knowledge_total
        ):
            raise ValueError("handover readiness partial state does not match source totals")
        if (self.convergence_samples == 0) != (self.mean_effect_interval_seconds is None):
            raise ValueError("missing convergence samples MUST report an unavailable mean")
        if self.convergence_samples > self.cases_observed - self.cases_invalid:
            raise ValueError("convergence samples exceed verified case observations")
        for codes in (self.alerts, self.source_gaps, self.external_blockers):
            if len(codes) > 32 or len(codes) != len(set(codes)):
                raise ValueError("handover readiness reason codes MUST be bounded and distinct")
        return self

    def require_current(self, now: datetime) -> None:
        """A future or expired observation cannot be reported as current readiness."""
        if now.utcoffset() is None or not self.observed_at <= now < self.expires_at:
            raise ValueError("handover readiness observation is not current")


__all__ = ["HANDOVER_READINESS_KEY", "HandoverReadinessReport"]
