"""Expiring server-owned dialogue context, never an identity or authority credential."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.adaptive_answer import AdaptiveAgentName
from fdai_service_contracts.ontology_query import QueryContract

AdaptiveRelationshipUnknownReason = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]{0,79}$")
]


class AdaptiveRelationshipProof(QueryContract):
    """Carry a current ownership read across authenticated service transport only."""

    target_agent: AdaptiveAgentName
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    kind: Literal["steward", "collaborator"]
    source_revision: Annotated[str, Field(min_length=1, max_length=256)]
    verified_at: datetime
    expires_at: datetime
    execution_authority: Literal[False] = False

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _deny_authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("relationship context MUST NOT grant execution authority")
        return value

    @model_validator(mode="after")
    def _time_is_bounded(self) -> AdaptiveRelationshipProof:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.verified_at, self.expires_at)
        ):
            raise ValueError("relationship proof timestamps MUST be timezone-aware")
        if not timedelta(0) < self.expires_at - self.verified_at <= timedelta(minutes=5):
            raise ValueError(
                "relationship proof lifetime MUST be positive and at most five minutes"
            )
        return self
