"""Terminal response-effect outcome for simulation and pattern learning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ._base import IdempotencyKey, SemVer, _Base
from .enums import Mode

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1, max_length=512)]


class ResponseOutcomeLabel(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNSCORABLE = "unscorable"


class ResponseVerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    HOLD = "hold"


class ResponseOutcome(_Base):
    """One immutable comparison of an expected action effect with reality."""

    schema_version: SemVer
    outcome_id: UUID
    idempotency_key: IdempotencyKey
    action_id: UUID
    event_id: UUID
    action_type_id: NonEmpty
    target_digest: Digest
    prediction_id: NonEmpty | None = None
    metric: NonEmpty | None = None
    expected_min: float | None = None
    expected_max: float | None = None
    observed_value: float | None = None
    predicted_at: datetime | None = None
    observation_deadline: datetime | None = None
    observed_at: datetime | None = None
    label: ResponseOutcomeLabel
    verification_status: ResponseVerificationStatus
    verification_reason: NonEmpty
    execution_mode: Mode
    execution_outcome: NonEmpty
    decision: Literal["auto", "hil", "deny", "abstain"]
    rollback_succeeded: bool | None = None
    evidence_refs: Annotated[tuple[NonEmpty, ...], Field(min_length=1)]
    recorded_at: datetime

    @property
    def scorable(self) -> bool:
        return self.label is not ResponseOutcomeLabel.UNSCORABLE

    @property
    def verification_passed(self) -> bool:
        return self.label is ResponseOutcomeLabel.VERIFIED

    @model_validator(mode="after")
    def _validate_semantics(self) -> ResponseOutcome:
        timestamps = (
            self.predicted_at,
            self.observation_deadline,
            self.observed_at,
            self.recorded_at,
        )
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("response outcome timestamps MUST be timezone-aware")
        numeric = (self.expected_min, self.expected_max, self.observed_value)
        if any(value is not None and not isfinite(value) for value in numeric):
            raise ValueError("response outcome numeric evidence MUST be finite")
        expected = (
            self.prediction_id,
            self.metric,
            self.expected_min,
            self.expected_max,
            self.predicted_at,
            self.observation_deadline,
        )
        has_prediction_evidence = any(value is not None for value in expected)
        has_incomplete_prediction_evidence = any(value is None for value in expected)
        if has_prediction_evidence and has_incomplete_prediction_evidence:
            raise ValueError("response outcome prediction evidence MUST be supplied together")
        if (self.observed_value is None) != (self.observed_at is None):
            raise ValueError(
                "response outcome observation value and time MUST be supplied together"
            )
        if (
            self.expected_min is not None
            and self.expected_max is not None
            and self.expected_min > self.expected_max
        ):
            raise ValueError("response outcome expected_min MUST be <= expected_max")
        if (
            self.predicted_at is not None
            and self.observation_deadline is not None
            and self.predicted_at > self.observation_deadline
        ):
            raise ValueError("response outcome deadline MUST NOT precede prediction")
        if self.observed_at is not None:
            if self.predicted_at is None or self.observation_deadline is None:
                raise ValueError("response outcome observation requires prediction timing")
            if not self.predicted_at <= self.observed_at <= self.observation_deadline:
                raise ValueError("response outcome observation MUST fall inside its effect window")
            if self.observed_at > self.recorded_at:
                raise ValueError("response outcome observation MUST NOT follow recording")
        if self.label is ResponseOutcomeLabel.VERIFIED:
            if self.verification_status is not ResponseVerificationStatus.VERIFIED:
                raise ValueError("verified response outcome requires verified status")
            if self.observed_value is None:
                raise ValueError("verified response outcome requires an observation")
        elif self.label is ResponseOutcomeLabel.MISMATCH:
            if self.verification_status is not ResponseVerificationStatus.MISMATCH:
                raise ValueError("mismatch response outcome requires mismatch status")
            if self.observed_value is None:
                raise ValueError("mismatch response outcome requires an observation")
        elif self.verification_status is not ResponseVerificationStatus.HOLD:
            raise ValueError("unscorable response outcome requires hold status")
        return self


__all__ = [
    "ResponseOutcome",
    "ResponseOutcomeLabel",
    "ResponseVerificationStatus",
]
