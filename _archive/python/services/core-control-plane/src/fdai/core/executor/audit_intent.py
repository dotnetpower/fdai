"""Authoritative pre-effect audit-intent identity and append/readback evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol, Self, cast, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
    ReservationState,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class AuditIntentAppendDecision(StrEnum):
    """Atomic append/readback disposition."""

    APPENDED = "appended"
    DUPLICATE_SAME = "duplicate_same"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PreEffectAuditIntent:
    """Exact pre-effect intent bound to reservation and lock acquisition."""

    schema_version: Literal["1.0.0"]
    reservation_receipt: IdempotencyReservationTransitionReceipt
    actor: str
    audit_phase: Literal["pre_effect"]
    created_at: datetime
    intent_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported pre-effect audit intent schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("pre-effect audit intent MUST NOT grant authority")
        if type(self.reservation_receipt) is not IdempotencyReservationTransitionReceipt:
            raise ValueError("audit intent requires an exact reservation receipt")
        reservation = self.reservation_receipt.record
        if reservation.state is not ReservationState.RESERVED:
            raise ValueError("audit intent requires a current reserved idempotency state")
        _validate_text("actor", self.actor)
        if type(self.audit_phase) is not str or self.audit_phase != "pre_effect":
            raise ValueError("audit intent phase MUST be pre_effect")
        _validate_utc("created_at", self.created_at)
        if not (
            self.reservation_receipt.recorded_at <= self.created_at < reservation.lease_expires_at
        ):
            raise ValueError("audit intent time is outside the reservation lease")
        _validate_digest("intent_digest", self.intent_digest)
        if self.intent_digest != _content_digest(self, "pre-effect-audit-intent"):
            raise ValueError("pre-effect audit intent digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        reservation_receipt: IdempotencyReservationTransitionReceipt,
        actor: str,
        created_at: datetime,
    ) -> Self:
        """Create one immutable intent before a provider can observe dispatch."""

        if cls is not PreEffectAuditIntent:
            raise TypeError("pre-effect audit intent does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "reservation_receipt": reservation_receipt,
            "actor": actor,
            "audit_phase": "pre_effect",
            "created_at": _utc(created_at, "created_at"),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["intent_digest"] = _payload_digest(
            values,
            "pre-effect-audit-intent",
            digest_field="intent_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AuditIntentAppendReceipt:
    """No-authority proof of persistence and exact authoritative readback."""

    schema_version: Literal["1.0.0"]
    intent: PreEffectAuditIntent
    persisted_intent_digest: str
    store_receipt_digest: str
    persisted_at: datetime
    read_back_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported audit intent append receipt schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("audit intent append receipt MUST NOT grant authority")
        if type(self.intent) is not PreEffectAuditIntent:
            raise ValueError("audit intent append receipt requires an exact intent")
        _validate_digest("persisted_intent_digest", self.persisted_intent_digest)
        if self.persisted_intent_digest != self.intent.intent_digest:
            raise ValueError("audit intent authoritative readback mismatched candidate")
        _validate_digest("store_receipt_digest", self.store_receipt_digest)
        _validate_utc("persisted_at", self.persisted_at)
        _validate_utc("read_back_at", self.read_back_at)
        if not (
            self.intent.created_at
            <= self.persisted_at
            <= self.read_back_at
            < self.intent.reservation_receipt.record.lease_expires_at
        ):
            raise ValueError("audit intent persistence chronology is invalid")
        _validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != _content_digest(self, "audit-intent-append-receipt"):
            raise ValueError("audit intent append receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        intent: PreEffectAuditIntent,
        persisted_intent_digest: str,
        store_receipt_digest: str,
        persisted_at: datetime,
        read_back_at: datetime,
    ) -> Self:
        """Create evidence after persistence and exact authoritative readback."""

        if cls is not AuditIntentAppendReceipt:
            raise TypeError("audit intent append receipt does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "intent": intent,
            "persisted_intent_digest": persisted_intent_digest,
            "store_receipt_digest": store_receipt_digest,
            "persisted_at": _utc(persisted_at, "persisted_at"),
            "read_back_at": _utc(read_back_at, "read_back_at"),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = _payload_digest(
            values,
            "audit-intent-append-receipt",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AuditIntentAppendResult:
    """Candidate-bound atomic append decision."""

    candidate_intent_digest: str
    decision: AuditIntentAppendDecision
    observed_intent_digest: str
    receipt: AuditIntentAppendReceipt | None

    def __post_init__(self) -> None:
        _validate_digest("candidate_intent_digest", self.candidate_intent_digest)
        if type(self.decision) is not AuditIntentAppendDecision:
            raise ValueError("audit intent append decision is invalid")
        _validate_digest("observed_intent_digest", self.observed_intent_digest)
        if self.decision in {
            AuditIntentAppendDecision.APPENDED,
            AuditIntentAppendDecision.DUPLICATE_SAME,
        }:
            if (
                type(self.receipt) is not AuditIntentAppendReceipt
                or self.candidate_intent_digest != self.observed_intent_digest
                or self.receipt.intent.intent_digest != self.candidate_intent_digest
            ):
                raise ValueError("successful audit intent append result mismatched candidate")
        elif (
            self.receipt is not None or self.observed_intent_digest == self.candidate_intent_digest
        ):
            raise ValueError("conflicting audit intent result MUST NOT contain success evidence")


@runtime_checkable
class AuditIntentStore(Protocol):
    """Atomic append plus authoritative readback seam."""

    async def append_and_readback(
        self,
        intent: PreEffectAuditIntent,
    ) -> AuditIntentAppendResult:
        """Persist once, read back, and classify exact duplicate or conflict."""
        ...


def audit_intent_to_mapping(
    intent: PreEffectAuditIntent,
) -> dict[str, object]:
    """Serialize one validated intent for exact durable JSON readback."""

    if type(intent) is not PreEffectAuditIntent:
        raise ValueError("audit intent serializer requires an exact intent")
    normalized = _normalize_digest_value(asdict(intent))
    if type(normalized) is not dict:
        raise ValueError("audit intent serialization is not an object")
    return cast(dict[str, object], normalized)


def _validate_text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"audit intent {name} MUST be canonical and bounded")


def _validate_digest(name: str, value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"audit intent {name} MUST be SHA-256")


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"audit intent {name} MUST include a timezone")
    return value.astimezone(UTC)


def _validate_utc(name: str, value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"audit intent {name} MUST be normalized to UTC")


def _payload_digest(
    payload: Mapping[str, object],
    domain: str,
    *,
    digest_field: str,
) -> str:
    body = dict(payload)
    body.pop(digest_field, None)
    return content_digest({"domain": domain, "body": _normalize_digest_value(body)})


def _content_digest(
    value: PreEffectAuditIntent | AuditIntentAppendReceipt,
    domain: str,
) -> str:
    digest_field = "intent_digest" if type(value) is PreEffectAuditIntent else "receipt_digest"
    return _payload_digest(asdict(value), domain, digest_field=digest_field)


def _normalize_digest_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(
        value,
        (
            PreEffectAuditIntent,
            AuditIntentAppendReceipt,
            IdempotencyReservationTransitionReceipt,
        ),
    ):
        return _normalize_digest_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_digest_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_digest_value(item) for item in value]
    return value


__all__ = [
    "AuditIntentAppendDecision",
    "AuditIntentAppendReceipt",
    "AuditIntentAppendResult",
    "AuditIntentStore",
    "PreEffectAuditIntent",
    "audit_intent_to_mapping",
]
