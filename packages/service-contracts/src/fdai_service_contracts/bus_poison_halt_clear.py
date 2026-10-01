"""Versioned Operator request to clear one ordered bus poison halt."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

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


__all__ = [
    "ORDERED_POISON_HALT_CLEAR_TOPIC",
    "OrderedPoisonHaltClearRequest",
]
