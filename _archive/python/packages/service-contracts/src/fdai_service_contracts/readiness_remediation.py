"""Typed Operational Readiness remediation requests for governed Core ingress."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest

READINESS_REMEDIATION_EVENT_TYPE = "readiness_remediation_request"
READINESS_REMEDIATION_EVENT_SOURCE = "operational_readiness"
READINESS_REMEDIATION_REQUEST_TOPIC = "operational-readiness.remediation.requests"
READINESS_REMEDIATION_CONSUMER_GROUP = "core-readiness-remediation-v1"


class ReadinessRemediationRequest(ContractBase):
    """One content-addressed shadow request with no approval or execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(pattern=r"^orr-remediation-[a-f0-9]{32}$")]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    action_type: Annotated[str, Field(min_length=1, max_length=256)]
    target_resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    target_revision: Annotated[str, Field(min_length=1, max_length=512)]
    params: dict[str, object]
    citing_rule_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    evidence_refs: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    submitter: Annotated[str, Field(min_length=1, max_length=256)]
    approver: Annotated[str, Field(min_length=1, max_length=256)]
    approved_at: datetime
    requested_at: datetime
    severity: Literal["low", "medium", "high", "critical"]
    source_mode: Literal["shadow"] = "shadow"
    request_digest: Digest
    approval_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "idempotency_key",
        "action_type",
        "target_resource_ref",
        "target_revision",
        "submitter",
        "approver",
    )
    @classmethod
    def _exact_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("readiness remediation text MUST be exact")
        return value

    @field_validator("approved_at", "requested_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("readiness remediation time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _identity_and_authority(self) -> ReadinessRemediationRequest:
        submitter_key = unicodedata.normalize("NFKC", self.submitter).casefold()
        approver_key = unicodedata.normalize("NFKC", self.approver).casefold()
        if submitter_key == approver_key:
            raise ValueError("readiness remediation submitter MUST NOT approve the same request")
        if self.approved_at > self.requested_at:
            raise ValueError("readiness remediation approval MUST precede publication")
        for name, values in (
            ("citing_rule_ids", self.citing_rule_ids),
            ("evidence_refs", self.evidence_refs),
        ):
            if values != tuple(sorted(set(values))) or any(
                not value or value != value.strip() for value in values
            ):
                raise ValueError(f"readiness remediation {name} MUST be unique and ordered")
        expected = readiness_remediation_request_digest(self)
        if self.request_digest != expected:
            raise ValueError("readiness remediation request digest mismatched")
        if self.request_id != f"orr-remediation-{expected.removeprefix('sha256:')[:32]}":
            raise ValueError("readiness remediation request id mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        action_type: str,
        target_resource_ref: str,
        target_revision: str,
        params: dict[str, object],
        citing_rule_ids: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        submitter: str,
        approver: str,
        approved_at: datetime,
        requested_at: datetime,
        severity: Literal["low", "medium", "high", "critical"],
    ) -> Self:
        if approved_at.tzinfo is None or approved_at.utcoffset() is None:
            raise ValueError("readiness remediation approved_at MUST include a timezone")
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("readiness remediation requested_at MUST include a timezone")
        candidate = cls.model_construct(
            schema_version="1.0.0",
            request_id="orr-remediation-" + "0" * 32,
            idempotency_key=idempotency_key,
            action_type=action_type,
            target_resource_ref=target_resource_ref,
            target_revision=target_revision,
            params=dict(params),
            citing_rule_ids=tuple(sorted(set(citing_rule_ids))),
            evidence_refs=tuple(sorted(set(evidence_refs))),
            submitter=submitter,
            approver=approver,
            approved_at=approved_at.astimezone(UTC),
            requested_at=requested_at.astimezone(UTC),
            severity=severity,
            source_mode="shadow",
            request_digest="sha256:" + "0" * 64,
            approval_authority=False,
            execution_authority=False,
        )
        payload = candidate.model_dump(mode="json", exclude={"request_id", "request_digest"})
        digest = canonical_digest(payload)
        return cls.model_validate(
            {
                **payload,
                "request_id": f"orr-remediation-{digest.removeprefix('sha256:')[:32]}",
                "request_digest": digest,
            }
        )


def readiness_remediation_request_digest(value: ReadinessRemediationRequest) -> str:
    """Return the digest covering every authority-relevant request field."""

    return canonical_digest(value.model_dump(mode="json", exclude={"request_id", "request_digest"}))


__all__ = [
    "READINESS_REMEDIATION_CONSUMER_GROUP",
    "READINESS_REMEDIATION_EVENT_SOURCE",
    "READINESS_REMEDIATION_EVENT_TYPE",
    "READINESS_REMEDIATION_REQUEST_TOPIC",
    "ReadinessRemediationRequest",
    "readiness_remediation_request_digest",
]
