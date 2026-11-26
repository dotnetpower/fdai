"""Versioned Operator request to clear one ordered bus poison halt."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.operator import OperatorPrincipalKind, OperatorRole

ORDERED_POISON_HALT_CLEAR_TOPIC = "fdai.operator.ordered-poison-halt.clear.v1"


class OrderedPoisonHaltClearRequest(ContractBase):
    """Exact, stale-fenced request to clear one durable ordered poison halt."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    requested_at: datetime
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_kind: OperatorPrincipalKind
    principal_roles: tuple[OperatorRole, ...]
    group_id: Annotated[str, Field(min_length=1, max_length=512)]
    agent_name: Annotated[str, Field(min_length=1, max_length=128)]
    topic: Annotated[str, Field(min_length=1, max_length=512)]
    halt_revision: Annotated[int, Field(ge=1)]
    halt_record_digest: Digest
    parked_record_topic: Annotated[str, Field(min_length=1, max_length=512)]
    parked_record_key: Annotated[str, Field(min_length=1, max_length=512)]
    parked_record_offset: int | None = None
    parked_record_digest: Digest
    operator_request_receipt: Mapping[str, Any] | None = None

    @field_validator("requested_at")
    @classmethod
    def _normalize_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ordered poison halt clear time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _owner_only(self) -> OrderedPoisonHaltClearRequest:
        if self.principal_kind is not OperatorPrincipalKind.HUMAN:
            raise ValueError("ordered poison halt clear requires a human principal")
        if OperatorRole.BREAK_GLASS in self.principal_roles or OperatorRole.OWNER not in set(
            self.principal_roles
        ):
            raise ValueError("ordered poison halt clear requires Owner")
        if self.parked_record_topic != f"{self.topic}.dlq":
            raise ValueError("parked record topic MUST be the halted topic DLQ")
        return self


def ordered_poison_halt_clear_receipt_event(
    request: OrderedPoisonHaltClearRequest | Mapping[str, Any],
) -> dict[str, object]:
    """Return the flat receipt event that signs the exact clear authority fields."""

    payload = (
        request.model_dump(mode="json", exclude={"operator_request_receipt"})
        if isinstance(request, OrderedPoisonHaltClearRequest)
        else {
            key: value for key, value in dict(request).items() if key != "operator_request_receipt"
        }
    )
    return {
        "idempotency_key": payload.get("idempotency_key"),
        "correlation_id": payload.get("request_id"),
        "initiator_principal": payload.get("principal_id"),
        "action_type": "bus.ordered-poison-halt.clear",
        "resource_id": f"{payload.get('group_id')}:{payload.get('topic')}",
        "params": payload,
    }


__all__ = [
    "ORDERED_POISON_HALT_CLEAR_TOPIC",
    "OrderedPoisonHaltClearRequest",
    "ordered_poison_halt_clear_receipt_event",
]
