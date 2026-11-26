"""Terminal response-effect outcome for simulation and pattern learning."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from ._base import IdempotencyKey, SemVer, _Base
from .effect_prediction import EffectPredictionSnapshot
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
    outcome_revision: Annotated[int | None, Field(ge=1, strict=True)] = None
    previous_revision_digest: Digest | None = None
    prediction_snapshot: EffectPredictionSnapshot | None = None
    observation_unit: NonEmpty | None = None
    observation_receipt_ref: NonEmpty | None = None

    @field_validator("expected_min", "expected_max", "observed_value", mode="before")
    @classmethod
    def _numeric_evidence(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("response outcome numeric evidence MUST NOT be boolean")
        return value

    @model_serializer(mode="wrap")
    def _serialize_version(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        payload: dict[str, object] = dict(handler(self))
        if self.schema_version == "1.0.0":
            for field in (
                "outcome_revision",
                "previous_revision_digest",
                "prediction_snapshot",
                "observation_unit",
                "observation_receipt_ref",
            ):
                payload.pop(field, None)
        return payload

    @property
    def revision_digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()

    @property
    def scorable(self) -> bool:
        return self.label is not ResponseOutcomeLabel.UNSCORABLE

    @property
    def verification_passed(self) -> bool:
        return self.label is ResponseOutcomeLabel.VERIFIED

    @model_validator(mode="after")
    def _validate_semantics(self) -> ResponseOutcome:
        if self.schema_version not in {"1.0.0", "1.1.0"}:
            raise ValueError("response outcome schema version is unsupported")
        extension = (
            self.outcome_revision,
            self.previous_revision_digest,
            self.prediction_snapshot,
            self.observation_unit,
            self.observation_receipt_ref,
        )
        if self.schema_version == "1.0.0" and any(value is not None for value in extension):
            raise ValueError("response outcome revision evidence requires version 1.1.0")
        if self.schema_version == "1.1.0":
            if self.outcome_revision is None or (
                (self.outcome_revision == 1) != (self.previous_revision_digest is None)
            ):
                raise ValueError("response outcome revisions MUST bind their predecessor")
            snapshot = self.prediction_snapshot
            if snapshot is not None and (
                snapshot.prediction_id != self.prediction_id
                or snapshot.action_id != self.action_id
                or snapshot.event_id != self.event_id
                or snapshot.action_type_id != self.action_type_id
                or snapshot.target_digest != self.target_digest
                or snapshot.metric != self.metric
                or snapshot.predicted_at != self.predicted_at
                or snapshot.observation_deadline != self.observation_deadline
            ):
                raise ValueError("response outcome MUST match its frozen prediction identity")
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
        if self.schema_version == "1.1.0":
            for field in ("predicted_at", "observation_deadline", "observed_at", "recorded_at"):
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(self, field, value.astimezone(UTC))
            for field in ("expected_min", "expected_max", "observed_value"):
                if getattr(self, field) == 0.0:
                    object.__setattr__(self, field, 0.0)
        return self


__all__ = [
    "ResponseOutcome",
    "ResponseOutcomeLabel",
    "ResponseVerificationStatus",
]
