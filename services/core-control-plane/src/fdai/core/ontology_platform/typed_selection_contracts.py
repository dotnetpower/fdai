"""Immutable evidence for governed read selection, never execution authority."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

READ_PROMOTION_ACTION = "governance.promote-typed-selection-read"
READ_FUNCTION = "query.ontology_typed_instance_candidates"
READ_QUALIFICATION_PURPOSE = "typed-selection-read-qualification"
READ_DEMOTION_EVENT = "governance.typed-selection-read.revoked"
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class ReadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


class ReadCapabilityBinding(ReadRecord):
    source_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_digest: Digest
    principal_scope_digest: Digest
    model_binding_digest: Digest
    data_policy_digest: Digest
    context_protocol: Literal["typed-selection-context-transport.v1"]


class ReadQualification(ReadRecord):
    binding: ReadCapabilityBinding
    outcome: Literal["qualified", "held", "refuted"]
    qualification_evidence_digest: Digest
    answer_latency_evidence_digest: Digest
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _time(self) -> ReadQualification:
        if (
            self.issued_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("read qualification requires an aware bounded validity interval")
        return self


class ReadCapabilityPointer(ReadRecord):
    revision: int = Field(ge=1, strict=True)
    binding: ReadCapabilityBinding
    qualification_digest: Digest
    enabled: bool = Field(default=False, strict=True)
    approval_key: str = Field(min_length=1, max_length=512)
    approval_fingerprint: str = Field(min_length=1, max_length=256)
    promotion_request_digest: Digest


class ReadSelectionEvidence(ReadRecord):
    binding: ReadCapabilityBinding
    registry_revision: int = Field(ge=1, strict=True)
    qualification_digest: Digest
    principal_ref: str = Field(min_length=1, max_length=256)
    request_ref: str = Field(min_length=1, max_length=256)
    query_digest: Digest
    snapshot_digest: Digest
    generation_digest: Digest
    source_projection_digest: Digest
    selection_json: str = Field(min_length=1, max_length=32768)
    agreement_digest: Digest
    issued_at: datetime
    expires_at: datetime
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _time(self) -> ReadSelectionEvidence:
        if (
            self.issued_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
            or not 0 < (self.expires_at - self.issued_at).total_seconds() <= 30
        ):
            raise ValueError("selection evidence requires an aware validity of at most 30 seconds")
        return self


class ReadModelStageContract(ReadRecord):
    network_allowed: Literal[True] = True
    credentials_allowed: Literal[True] = True
    max_model_calls: Literal[2] = 2
    per_call_timeout_seconds: Literal[20] = 20
    total_timeout_seconds: Literal[24] = 24
    execution_authority: Literal[False] = False


class ReadDemotionCommand(ReadRecord):
    principal_scope_digest: Digest
    expected_revision: int = Field(ge=1, strict=True)
    qualification_digest: Digest
    action_run_identity: Digest
    source_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    reason: Literal["revoked", "regression", "rollback"]
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _time(self) -> ReadDemotionCommand:
        if (
            self.issued_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("read demotion command requires an aware bounded validity interval")
        return self
