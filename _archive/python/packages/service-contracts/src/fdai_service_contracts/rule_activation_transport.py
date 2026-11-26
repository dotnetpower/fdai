"""Content-free Operator notices for governed Rule activation intake."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RULE_ACTIVATION_REQUEST_TOPIC = "operator.rule-activation.requests"
RULE_ACTIVATION_CONSUMER_GROUP = "core-rule-activation-v1"
RULE_ACTIVATION_PROJECTION_TOPIC = "core.rule-activation.projections"


class RuleActivationRequestNotice(BaseModel):
    """Reference one immutable Operator proposal without copying its body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    proposal_ref: Annotated[
        str,
        Field(pattern=r"^operator-proposal:workflow:[a-f0-9]{64}$"),
    ]
    proposal_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    request_id: Annotated[str, Field(pattern=r"^operator-[a-f0-9]{32}$")]
    proposal_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    operation: Literal["rule.activation-request", "rule.activation-approve"]
    accepted_at: datetime
    producer_service: Literal["operator-service"] = "operator-service"
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _identity(self) -> RuleActivationRequestNotice:
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("Rule activation notice accepted_at MUST be timezone-aware")
        if self.proposal_id != f"operator-{self.proposal_digest[:32]}":
            raise ValueError("Rule activation notice identity does not match its digest")
        if self.operation == "rule.activation-request" and self.request_id != self.proposal_id:
            raise ValueError("Rule activation request notice must reference itself")
        return self


__all__ = [
    "RULE_ACTIVATION_CONSUMER_GROUP",
    "RULE_ACTIVATION_PROJECTION_TOPIC",
    "RULE_ACTIVATION_REQUEST_TOPIC",
    "RuleActivationRequestNotice",
]
