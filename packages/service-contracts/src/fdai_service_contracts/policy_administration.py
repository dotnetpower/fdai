"""Typed policy-administration requests and Mimir activation receipts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.approval_profile import approval_profile_from_audit_dict
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from fdai_service_contracts.operator_request_receipt import OperatorRequestReceipt

POLICY_REVISION_REQUEST_TOPIC = "operator.policy-revision.requests"
POLICY_REVISION_CONSUMER_GROUP = "mimir-policy-revision-v1"
POLICY_OBJECT_TOPIC = "object.policy"
POLICY_ACTIVATION_REQUEST_TOPIC = "object.policy-activation-request"

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_REVISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACTION_TYPE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class PolicyKind(StrEnum):
    """Policy families Mimir can validate and activate."""

    APPROVAL = "approval"
    ADMISSION = "admission"


class PolicyMode(StrEnum):
    """Maximum runtime mode declared for one ActionType or Workflow."""

    SHADOW = "shadow"
    ENFORCE = "enforce"


class PolicyAdministrationContract(BaseModel):
    """Reject unknown fields and keep every policy administration record immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AdmissionPolicyContent(PolicyAdministrationContract):
    """OPA/Rego admission content plus declared ActionType modes."""

    rego: Annotated[str, Field(strict=True, min_length=1, max_length=200_000)]
    action_type_modes: dict[str, PolicyMode] = Field(default_factory=dict)
    policy_tests: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=128)

    @field_validator("action_type_modes")
    @classmethod
    def _action_type_modes_are_bounded(
        cls,
        value: dict[str, PolicyMode],
    ) -> dict[str, PolicyMode]:
        if len(value) > 512:
            raise ValueError("policy action_type_modes MUST contain at most 512 entries")
        if any(_ACTION_TYPE.fullmatch(key) is None for key in value):
            raise ValueError("policy action_type_modes keys MUST be canonical ActionType names")
        if tuple(value) != tuple(sorted(value)):
            raise ValueError("policy action_type_modes MUST use canonical key order")
        return value


class ApprovalPolicyContent(PolicyAdministrationContract):
    """Approval policy document plus declared ActionType modes."""

    document: dict[str, Any]
    action_type_modes: dict[str, PolicyMode] = Field(default_factory=dict)

    @field_validator("document")
    @classmethod
    def _approval_document_is_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        approval_profile_from_audit_dict(value)
        return value

    @field_validator("action_type_modes")
    @classmethod
    def _action_type_modes_are_bounded(
        cls,
        value: dict[str, PolicyMode],
    ) -> dict[str, PolicyMode]:
        return AdmissionPolicyContent._action_type_modes_are_bounded(value)


class PolicyRevisionRequestBody(PolicyAdministrationContract):
    """Operator-authored policy revision request accepted by the Operator API."""

    policy_kind: PolicyKind
    content: AdmissionPolicyContent | ApprovalPolicyContent
    parent_revision_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    reason: Annotated[str, Field(strict=True, min_length=20, max_length=1_000)]

    @model_validator(mode="after")
    def _content_matches_kind(self) -> PolicyRevisionRequestBody:
        if self.policy_kind is PolicyKind.ADMISSION and not isinstance(
            self.content, AdmissionPolicyContent
        ):
            raise ValueError("admission policy revisions require Rego content")
        if self.policy_kind is PolicyKind.APPROVAL and not isinstance(
            self.content, ApprovalPolicyContent
        ):
            raise ValueError("approval policy revisions require approval document content")
        if (
            self.parent_revision_id is not None
            and _REVISION_ID.fullmatch(self.parent_revision_id) is None
        ):
            raise ValueError("parent_revision_id MUST be a bounded revision identifier")
        if self.reason != self.reason.strip():
            raise ValueError("policy revision reason MUST NOT contain surrounding whitespace")
        return self


class PolicyRevisionRequestEvent(PolicyRevisionRequestBody):
    """Typed event Mimir consumes; possession grants no execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_type: Literal["policy_revision_request"] = "policy_revision_request"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    author_principal: Annotated[str, Field(min_length=1, max_length=512)]
    requested_at: datetime
    authentication_receipt_ref: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authentication_receipt: OperatorAuthenticationReceipt | None = None
    operator_request_receipt: OperatorRequestReceipt | None = None
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    accountable_agent: Literal["Mimir"] = "Mimir"
    execution_authority: Literal[False] = False

    @field_validator("requested_at")
    @classmethod
    def _requested_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy revision requested_at MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _digest_matches(self) -> PolicyRevisionRequestEvent:
        expected = policy_revision_request_digest(self)
        if self.request_digest != expected:
            raise ValueError("policy revision request digest mismatched")
        if (
            self.authentication_receipt is not None
            and self.authentication_receipt.receipt_digest != self.authentication_receipt_ref
        ):
            raise ValueError("authentication receipt ref mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        body: PolicyRevisionRequestBody,
        request_id: str,
        correlation_id: str,
        idempotency_key: str,
        author_principal: str,
        requested_at: datetime,
        authentication_receipt: OperatorAuthenticationReceipt,
        operator_request_receipt: OperatorRequestReceipt | None,
    ) -> Self:
        candidate = cls.model_construct(
            policy_kind=body.policy_kind,
            content=body.content,
            parent_revision_id=body.parent_revision_id,
            reason=body.reason,
            schema_version="1.0.0",
            event_type="policy_revision_request",
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            author_principal=author_principal,
            requested_at=requested_at.astimezone(UTC),
            authentication_receipt_ref=authentication_receipt.receipt_digest,
            authentication_receipt=authentication_receipt,
            operator_request_receipt=operator_request_receipt,
            request_digest="sha256:" + "0" * 64,
            accountable_agent="Mimir",
            execution_authority=False,
        )
        payload = candidate.model_dump(mode="json", exclude={"request_digest"})
        return cls.model_validate({**payload, "request_digest": canonical_digest(payload)})

    @staticmethod
    def operator_receipt_event(
        *,
        body: PolicyRevisionRequestBody,
        request_id: str,
        correlation_id: str,
        idempotency_key: str,
        author_principal: str,
        authenticated_at: datetime,
        app_roles: frozenset[str],
    ) -> dict[str, object]:
        """Return the flat signed Operator request receipt input."""

        return {
            "operator_request_receipt_schema_version": "1.2.0",
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "initiator_principal": author_principal,
            "action_type": "policy.revision-request",
            "resource_id": f"policy:{body.policy_kind.value}",
            "params": {
                "policy_kind": body.policy_kind.value,
                "parent_revision_id": body.parent_revision_id,
                "content_digest": policy_content_digest(body.content),
            },
            "authenticated_at": authenticated_at.astimezone(UTC).isoformat(),
            "max_auth_age_seconds": 600,
            "principal_roles": tuple(sorted(app_roles)),
        }


class PolicyValidationResult(PolicyAdministrationContract):
    """Mimir's deterministic validation summary for one accepted revision."""

    schema_valid: Literal[True] = True
    rego_valid: bool
    release_maximums_valid: bool
    policy_tests_valid: bool
    validation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    details: tuple[str, ...] = Field(default_factory=tuple, max_length=64)


class PolicyRevisionRecord(PolicyAdministrationContract):
    """Immutable content-addressed policy revision stored by Mimir."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision_id: Annotated[str, Field(min_length=1, max_length=128)]
    policy_kind: PolicyKind
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    content: AdmissionPolicyContent | ApprovalPolicyContent
    signature_ref: Annotated[str, Field(min_length=1, max_length=512)]
    parent_revision_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    author_principal: Annotated[str, Field(min_length=1, max_length=512)]
    reason: Annotated[str, Field(min_length=20, max_length=1_000)]
    created_at: datetime
    activated_at: datetime | None = None
    validation: PolicyValidationResult
    diff_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class PolicyActivationEvent(PolicyAdministrationContract):
    """Typed activation event published by Mimir after durable activation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    object_type: Literal["Policy"] = "Policy"
    kind: Literal["policy_activation"] = "policy_activation"
    policy_id: Annotated[str, Field(min_length=1, max_length=256)]
    event_type: Literal["policy_activation"] = "policy_activation"
    policy_kind: PolicyKind
    revision_id: Annotated[str, Field(min_length=1, max_length=128)]
    policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    activated_at: datetime
    author_principal: Annotated[str, Field(min_length=1, max_length=512)]
    validation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]


class PolicyActivationApprovalRequest(PolicyAdministrationContract):
    """Mimir-owned request for Var quorum before activating a relaxing revision."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    object_type: Literal["PolicyActivationRequest"] = "PolicyActivationRequest"
    kind: Literal["policy_activation_approval_requested"] = "policy_activation_approval_requested"
    event_type: Literal["policy_activation_approval_requested"] = (
        "policy_activation_approval_requested"
    )
    policy_id: Annotated[str, Field(min_length=1, max_length=256)]
    policy_kind: PolicyKind
    revision_id: Annotated[str, Field(min_length=1, max_length=128)]
    policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    author_principal: Annotated[str, Field(min_length=1, max_length=512)]
    validation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    parent_revision_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    requested_at: datetime
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    quorum_required: Annotated[int, Field(ge=2)]
    original_quorum_required: Annotated[int, Field(ge=2)]
    effective_quorum_required: Annotated[int, Field(ge=2)]

    @field_validator("requested_at")
    @classmethod
    def _requested_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy activation approval requested_at MUST include a timezone")
        return value.astimezone(UTC)


class ReleaseCapabilityMaximums(Protocol):
    """Read-side source for Release maximum modes.

    Implementations are supplied by the lifecycle Release manifest in #1822. Until
    one is configured, Mimir fails closed for any requested ActionType above shadow.
    """

    def maximum_mode_for_action_type(self, action_type: str) -> PolicyMode | None: ...


def policy_content_digest(content: AdmissionPolicyContent | ApprovalPolicyContent) -> str:
    """Return the immutable digest over canonical policy content."""

    return canonical_digest(content.model_dump(mode="json"))


def policy_revision_request_digest(event: PolicyRevisionRequestEvent) -> str:
    """Return the canonical request digest excluding the digest field itself."""

    return canonical_digest(event.model_dump(mode="json", exclude={"request_digest"}))


def policy_validation_digest(values: Mapping[str, object]) -> str:
    """Return a digest for validation results and bounded evidence."""

    return canonical_digest(dict(values))


__all__ = [
    "AdmissionPolicyContent",
    "ApprovalPolicyContent",
    "POLICY_OBJECT_TOPIC",
    "POLICY_ACTIVATION_REQUEST_TOPIC",
    "POLICY_REVISION_CONSUMER_GROUP",
    "POLICY_REVISION_REQUEST_TOPIC",
    "PolicyActivationEvent",
    "PolicyActivationApprovalRequest",
    "PolicyKind",
    "PolicyMode",
    "PolicyRevisionRecord",
    "PolicyRevisionRequestBody",
    "PolicyRevisionRequestEvent",
    "PolicyValidationResult",
    "ReleaseCapabilityMaximums",
    "policy_content_digest",
    "policy_revision_request_digest",
    "policy_validation_digest",
]
