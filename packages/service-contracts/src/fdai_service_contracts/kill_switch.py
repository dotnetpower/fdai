"""Typed Operator-to-Core global kill-switch requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from fdai_service_contracts.operator_request_receipt import OperatorRequestReceipt

KILL_SWITCH_REQUEST_TOPIC = "operator.kill-switch.requests"
KILL_SWITCH_CONSUMER_GROUP = "var-kill-switch-v1"

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class KillSwitchContract(BaseModel):
    """Reject unknown fields and keep kill-switch records immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KillSwitchRequestBody(KillSwitchContract):
    """Operator-authored state transition accepted by the Operator API."""

    engaged: bool
    reason: Annotated[str, Field(strict=True, min_length=20, max_length=500)]

    @field_validator("reason")
    @classmethod
    def _reason_has_no_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("kill-switch reason MUST NOT contain surrounding whitespace")
        return value


class KillSwitchRequestEvent(KillSwitchRequestBody):
    """Typed request Var consumes; possession grants no execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_type: Literal["kill_switch_request"] = "kill_switch_request"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]
    initiator_principal: Annotated[str, Field(min_length=1, max_length=512)]
    requested_at: datetime
    authentication_receipt_ref: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authentication_receipt: OperatorAuthenticationReceipt
    operator_request_receipt: OperatorRequestReceipt | None = None
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    accountable_agent: Literal["Var"] = "Var"
    execution_authority: Literal[False] = False

    @field_validator("requested_at")
    @classmethod
    def _requested_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kill-switch requested_at MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _digest_matches(self) -> KillSwitchRequestEvent:
        expected = kill_switch_request_digest(self)
        if self.request_digest != expected:
            raise ValueError("kill-switch request digest mismatched")
        if self.authentication_receipt.receipt_digest != self.authentication_receipt_ref:
            raise ValueError("authentication receipt ref mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        body: KillSwitchRequestBody,
        request_id: str,
        correlation_id: str,
        idempotency_key: str,
        initiator_principal: str,
        requested_at: datetime,
        authentication_receipt: OperatorAuthenticationReceipt,
        operator_request_receipt: OperatorRequestReceipt | None,
    ) -> Self:
        candidate = cls.model_construct(
            engaged=body.engaged,
            reason=body.reason,
            schema_version="1.0.0",
            event_type="kill_switch_request",
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            initiator_principal=initiator_principal,
            requested_at=requested_at.astimezone(UTC),
            authentication_receipt_ref=authentication_receipt.receipt_digest,
            authentication_receipt=authentication_receipt,
            operator_request_receipt=operator_request_receipt,
            request_digest="sha256:" + "0" * 64,
            accountable_agent="Var",
            execution_authority=False,
        )
        payload = candidate.model_dump(mode="json", exclude={"request_digest"})
        return cls.model_validate({**payload, "request_digest": canonical_digest(payload)})

    @staticmethod
    def operator_receipt_event(
        *,
        body: KillSwitchRequestBody,
        correlation_id: str,
        idempotency_key: str,
        initiator_principal: str,
        requested_at: datetime,
        authenticated_at: datetime,
        principal_roles: frozenset[str],
    ) -> dict[str, object]:
        """Return the flat signed Operator request receipt input."""

        return {
            "operator_request_receipt_schema_version": "1.2.0",
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "initiator_principal": initiator_principal,
            "action_type": "system.kill-switch.set-state",
            "resource_id": "system:kill-switch",
            "params": {
                "engaged": body.engaged,
                "reason": body.reason,
                "requested_at": requested_at.astimezone(UTC).isoformat(),
            },
            "authenticated_at": authenticated_at.astimezone(UTC).isoformat(),
            "max_auth_age_seconds": 600,
            "principal_roles": tuple(sorted(principal_roles)),
        }


def kill_switch_request_digest(event: KillSwitchRequestEvent) -> str:
    """Return the content digest for one immutable kill-switch request."""

    return canonical_digest(event.model_dump(mode="json", exclude={"request_digest"}))


__all__ = [
    "KILL_SWITCH_CONSUMER_GROUP",
    "KILL_SWITCH_REQUEST_TOPIC",
    "KillSwitchRequestBody",
    "KillSwitchRequestEvent",
    "kill_switch_request_digest",
]
