"""Versioned terminal classification evidence without operational authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from fdai_service_contracts.executor_models import ContractBase
from fdai_service_contracts.measurement_time import measurement_timestamp_input

CONTROL_LOOP_MEASUREMENT_ACTION_KIND = "measurement.control_loop.v1"
CONTROL_LOOP_MEASUREMENT_ACTOR = "fdai.measurement"

SourceText = Annotated[str, Field(min_length=1, max_length=4096, strict=True)]
SourceKey = Annotated[str, Field(min_length=1, max_length=512, strict=True)]
TerminalToken = Annotated[str, Field(min_length=1, max_length=128, strict=True)]


def control_loop_measurement_id(idempotency_key: str) -> UUID:
    """Identify one normalized event using its complete, unchanged source key."""
    return uuid5(NAMESPACE_URL, f"fdai:measurement.control_loop.v1:{idempotency_key}")


class ControlLoopMeasurement(ContractBase):
    """One normalized terminal, not an effect, success, or promotion receipt.

    ``occurred_at`` is the source event's detection time; ``ingested_at`` is
    its normalization time. ``recorded_at`` is when its terminal result was
    captured, not a persistence retry time. An unclassified tier stays null.
    The raw terminal outcome and gate route are independent observations.
    ``synthetic`` preserves an explicit source marker, or null when unknown.
    A false source marker is not authentication or governed cohort admission.
    ``action_ids`` preserves every terminal execution-result identity in order,
    including refused and failed attempts, duplicates, and unbuilt-action
    placeholders. It is not a list of verified successes or a dispatch permit.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
    measurement_id: UUID
    event_id: UUID
    idempotency_key: SourceKey
    correlation_id: SourceText | None = None
    source: SourceText
    event_type: SourceText
    mode: Literal["shadow", "enforce"]
    synthetic: StrictBool | None = None
    occurred_at: AwareDatetime
    ingested_at: AwareDatetime
    recorded_at: AwareDatetime
    tier: Literal["t0", "t1", "t2"] | None
    terminal_outcome: TerminalToken
    gate_route: TerminalToken
    resource_type: SourceText | None = None
    action_ids: Annotated[tuple[SourceText, ...], Field(max_length=4096)] = ()

    @field_validator("occurred_at", "ingested_at", "recorded_at", mode="before")
    @classmethod
    def _timestamp_representation(cls, value: object) -> object:
        return measurement_timestamp_input(value)

    @field_validator("action_ids", mode="before")
    @classmethod
    def _validate_action_ids_container(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("measurement action IDs MUST be an ordered array")
        return value

    @classmethod
    def from_audit_entry(cls, entry: Mapping[str, object]) -> ControlLoopMeasurement:
        """Parse the canonical audit JSON entry with exact producer discriminators.

        Pass the audit row's ``entry`` object, not its database/hash-chain
        wrapper. Only ``actor`` and ``action_kind`` are stripped; unknown
        fields, wrong versions, and malformed measurements raise ValueError.
        Sequence and hash validation remain the read adapter's responsibility.
        Discriminator validation alone does not authenticate the writer.
        """
        if not isinstance(entry, Mapping):
            raise ValueError("control-loop measurement audit entry MUST be an object")
        if entry.get("actor") != CONTROL_LOOP_MEASUREMENT_ACTOR:
            raise ValueError("control-loop measurement actor is not canonical")
        if entry.get("action_kind") != CONTROL_LOOP_MEASUREMENT_ACTION_KIND:
            raise ValueError("control-loop measurement action kind is not canonical")
        if entry.get("schema_version") != "1.0.0":
            raise ValueError("control-loop measurement schema version is not supported")
        return cls.model_validate(
            {key: value for key, value in entry.items() if key not in {"actor", "action_kind"}}
        )

    @model_validator(mode="after")
    def _validate_identity(self) -> ControlLoopMeasurement:
        if self.measurement_id != control_loop_measurement_id(self.idempotency_key):
            raise ValueError("measurement identity MUST match the normalized event key")
        if self.terminal_outcome == "deduped":
            raise ValueError("duplicate deliveries MUST NOT create terminal measurements")
        return self
