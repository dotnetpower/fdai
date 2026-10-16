"""Immutable prediction-time facts; neither predictions nor scores grant authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ._base import ContractBase

_Text = Annotated[str, Field(min_length=1, max_length=512)]
_Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EffectPredictionSnapshot(ContractBase):
    """One frozen scalar prediction with independent episode and source provenance."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    prediction_id: _Text
    event_id: UUID
    action_id: UUID
    action_type_id: _Text
    target_digest: _Digest
    metric: _Text
    unit: _Text
    objective: Literal["minimize", "maximize"]
    model_ref: _Text
    model_digest: _Digest
    source_digest: _Digest
    independence_key: _Digest
    point_prediction: Annotated[float, Field(strict=True)]
    interval_lower: Annotated[float, Field(strict=True)]
    interval_upper: Annotated[float, Field(strict=True)]
    nominal_coverage: Annotated[float, Field(gt=0, lt=1, strict=True)]
    known_at: datetime
    predicted_at: datetime
    observation_deadline: datetime
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_snapshot(self) -> EffectPredictionSnapshot:
        values = (self.point_prediction, self.interval_lower, self.interval_upper)
        if any(not isfinite(value) for value in values):
            raise ValueError("effect prediction values MUST be finite")
        if not self.interval_lower <= self.point_prediction <= self.interval_upper:
            raise ValueError("effect prediction interval MUST contain its point prediction")
        if any(
            value.tzinfo is None
            for value in (self.known_at, self.predicted_at, self.observation_deadline)
        ):
            raise ValueError("effect prediction timestamps MUST be timezone-aware")
        if not self.known_at <= self.predicted_at <= self.observation_deadline:
            raise ValueError("effect prediction knowledge and horizon ordering is invalid")
        for field in ("known_at", "predicted_at", "observation_deadline"):
            object.__setattr__(self, field, getattr(self, field).astimezone(UTC))
        for field in ("point_prediction", "interval_lower", "interval_upper"):
            if getattr(self, field) == 0.0:
                object.__setattr__(self, field, 0.0)
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
