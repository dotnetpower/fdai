"""Crash-safe idempotency reservation identity, transitions, and store seam."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import ResourceLockAcquisitionReceipt

from .idempotency_reservation_identity import same_operation

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")


class ReservationState(StrEnum):
    """Monotonic durable reservation lifecycle."""

    RESERVED = "reserved"
    IN_FLIGHT = "in_flight"
    TERMINAL = "terminal"
    ABANDONED = "abandoned"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ReservationEvidenceKind(StrEnum):
    """Authoritative evidence associated with a terminal transition."""

    DISPATCH_NEVER_BEGAN = "dispatch_never_began"
    LEASE_EXPIRED = "lease_expired"
    CONTINUITY_UNPROVEN = "continuity_unproven"
    SINK_TERMINAL_OUTCOME = "sink_terminal_outcome"
    IRREVOCABLE_NON_ACCEPTANCE = "irrevocable_non_acceptance"
    INDEPENDENT_EFFECT_OUTCOME = "independent_effect_outcome"


class ReservationMatch(StrEnum):
    """How one candidate compares with an existing stable-key record."""

    ACQUIRED = "acquired"
    DUPLICATE_SAME = "duplicate_same"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class IdempotencyReservationIdentity:
    """Exact action, path, source, and acquisition bound to one stable key."""

    schema_version: Literal["1.0.0"]
    idempotency_key: str
    action_digest: str
    execution_path: ExecutionPath
    execution_fingerprint: str
    source_revision: str
    acquisition_receipt: ResourceLockAcquisitionReceipt
    identity_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported idempotency reservation identity schema")
        if self.execution_authority is not False:
            raise ValueError("idempotency reservation identity MUST NOT grant authority")
        _validate_text("idempotency_key", self.idempotency_key)
        _validate_digest("action_digest", self.action_digest)
        if type(self.execution_path) is not ExecutionPath:
            raise ValueError("idempotency reservation execution path is invalid")
        if (
            type(self.execution_fingerprint) is not str
            or _FINGERPRINT.fullmatch(self.execution_fingerprint) is None
        ):
            raise ValueError("idempotency reservation fingerprint MUST be lowercase SHA-256")
        if (
            type(self.source_revision) is not str
            or _REVISION.fullmatch(self.source_revision) is None
        ):
            raise ValueError("idempotency reservation source revision MUST be canonical")
        if type(self.acquisition_receipt) is not ResourceLockAcquisitionReceipt:
            raise ValueError("idempotency reservation requires an exact acquisition receipt")
        if (
            self.acquisition_receipt.action_digest != self.action_digest
            or self.acquisition_receipt.source_revision != self.source_revision
        ):
            raise ValueError("idempotency reservation acquisition context mismatched")
        _validate_digest("identity_digest", self.identity_digest)
        if self.identity_digest != _content_digest(self, "idempotency-reservation-identity"):
            raise ValueError("idempotency reservation identity digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        action_digest: str,
        execution_path: ExecutionPath,
        execution_fingerprint: str,
        source_revision: str,
        acquisition_receipt: ResourceLockAcquisitionReceipt,
    ) -> Self:
        """Create one no-authority reservation identity."""

        if cls is not IdempotencyReservationIdentity:
            raise TypeError("idempotency reservation identity does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "idempotency_key": idempotency_key,
            "action_digest": action_digest,
            "execution_path": execution_path,
            "execution_fingerprint": execution_fingerprint,
            "source_revision": source_revision,
            "acquisition_receipt": acquisition_receipt,
            "execution_authority": False,
        }
        values["identity_digest"] = _payload_digest(
            values,
            "idempotency-reservation-identity",
            digest_field="identity_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class IdempotencyReservationRecord:
    """Immutable current state of one durable reservation."""

    schema_version: Literal["1.0.0"]
    identity: IdempotencyReservationIdentity
    state: ReservationState
    revision: int
    owner_reference_digest: str
    reserved_at: datetime
    lease_expires_at: datetime
    state_changed_at: datetime
    dispatch_started_at: datetime | None
    evidence_kind: ReservationEvidenceKind | None
    evidence_digest: str | None
    terminal_outcome_digest: str | None
    record_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported idempotency reservation record schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("idempotency reservation record MUST NOT grant authority")
        if type(self.identity) is not IdempotencyReservationIdentity:
            raise ValueError("idempotency reservation record requires an exact identity")
        if type(self.state) is not ReservationState:
            raise ValueError("idempotency reservation state is invalid")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("idempotency reservation revision MUST be positive")
        _validate_digest("owner_reference_digest", self.owner_reference_digest)
        if self.owner_reference_digest != self.identity.acquisition_receipt.owner_token_digest:
            raise ValueError("idempotency reservation owner mismatched acquisition")
        _validate_utc("reserved_at", self.reserved_at)
        _validate_utc("lease_expires_at", self.lease_expires_at)
        _validate_utc("state_changed_at", self.state_changed_at)
        if self.lease_expires_at <= self.reserved_at:
            raise ValueError("idempotency reservation lease MUST follow reservation")
        if self.reserved_at < self.identity.acquisition_receipt.acquired_at:
            raise ValueError("idempotency reservation predates its lock acquisition")
        if self.state_changed_at < self.reserved_at:
            raise ValueError("idempotency reservation state change predates reservation")
        if self.dispatch_started_at is not None:
            _validate_utc("dispatch_started_at", self.dispatch_started_at)
            if self.dispatch_started_at < self.reserved_at:
                raise ValueError("idempotency dispatch cannot predate reservation")
        if (
            self.evidence_kind is not None
            and type(self.evidence_kind) is not ReservationEvidenceKind
        ):
            raise ValueError("idempotency reservation evidence kind is invalid")
        for name, value in (
            ("evidence_digest", self.evidence_digest),
            ("terminal_outcome_digest", self.terminal_outcome_digest),
        ):
            if value is not None:
                _validate_digest(name, value)
        _validate_state_shape(self)
        _validate_state_revision(self)
        _validate_digest("record_digest", self.record_digest)
        if self.record_digest != _content_digest(self, "idempotency-reservation-record"):
            raise ValueError("idempotency reservation record digest mismatched")

    @classmethod
    def create_reserved(
        cls,
        *,
        identity: IdempotencyReservationIdentity,
        reserved_at: datetime,
        lease_expires_at: datetime,
    ) -> IdempotencyReservationRecord:
        """Create the first durable state before dispatch."""

        if cls is not IdempotencyReservationRecord:
            raise TypeError("idempotency reservation record does not support subclasses")
        return _build_record(
            identity=identity,
            state=ReservationState.RESERVED,
            revision=1,
            reserved_at=_utc(reserved_at, "reserved_at"),
            lease_expires_at=_utc(lease_expires_at, "lease_expires_at"),
            state_changed_at=_utc(reserved_at, "reserved_at"),
        )


@dataclass(frozen=True, slots=True)
class IdempotencyReservationTransitionReceipt:
    """Authoritative CAS/readback evidence for one reservation transition."""

    schema_version: Literal["1.0.0"]
    prior_record: IdempotencyReservationRecord | None
    record: IdempotencyReservationRecord
    expected_prior_revision: int
    store_receipt_digest: str
    recorded_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported idempotency transition receipt schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("idempotency transition receipt MUST NOT grant authority")
        if type(self.record) is not IdempotencyReservationRecord:
            raise ValueError("idempotency transition receipt requires an exact record")
        if (
            type(self.expected_prior_revision) is not int
            or self.expected_prior_revision < 0
            or self.record.revision != self.expected_prior_revision + 1
        ):
            raise ValueError("idempotency transition receipt revision mismatched")
        if self.expected_prior_revision == 0:
            if self.prior_record is not None or self.record.state is not ReservationState.RESERVED:
                raise ValueError("initial idempotency reservation MUST NOT have a predecessor")
        else:
            if type(self.prior_record) is not IdempotencyReservationRecord:
                raise ValueError("idempotency transition receipt requires its predecessor")
            if self.prior_record.revision != self.expected_prior_revision:
                raise ValueError("idempotency transition predecessor mismatched")
            if self.recorded_at < self.prior_record.state_changed_at:
                raise ValueError("idempotency transition receipt predates its predecessor")
            _validate_transition(self.prior_record, self.record)
        _validate_digest("store_receipt_digest", self.store_receipt_digest)
        _validate_utc("recorded_at", self.recorded_at)
        if self.recorded_at < self.record.state_changed_at:
            raise ValueError("idempotency transition receipt predates state change")
        _validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != _content_digest(
            self,
            "idempotency-reservation-transition",
        ):
            raise ValueError("idempotency transition receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        prior_record: IdempotencyReservationRecord | None,
        record: IdempotencyReservationRecord,
        expected_prior_revision: int,
        store_receipt_digest: str,
        recorded_at: datetime,
    ) -> Self:
        """Create evidence only after atomic write and authoritative readback."""

        if cls is not IdempotencyReservationTransitionReceipt:
            raise TypeError("idempotency transition receipt does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "prior_record": prior_record,
            "record": record,
            "expected_prior_revision": expected_prior_revision,
            "store_receipt_digest": store_receipt_digest,
            "recorded_at": _utc(recorded_at, "recorded_at"),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = _payload_digest(
            values,
            "idempotency-reservation-transition",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class IdempotencyReservationReserveResult:
    """Atomic insert result that distinguishes ownership from observation."""

    candidate_identity: IdempotencyReservationIdentity
    match: ReservationMatch
    observed_record: IdempotencyReservationRecord
    transition_receipt: IdempotencyReservationTransitionReceipt | None

    def __post_init__(self) -> None:
        if type(self.match) is not ReservationMatch:
            raise ValueError("idempotency reserve result match is invalid")
        if type(self.candidate_identity) is not IdempotencyReservationIdentity:
            raise ValueError("idempotency reserve result requires an exact candidate")
        if type(self.observed_record) is not IdempotencyReservationRecord:
            raise ValueError("idempotency reserve result requires an exact record")
        if self.match is ReservationMatch.ACQUIRED:
            if (
                type(self.transition_receipt) is not IdempotencyReservationTransitionReceipt
                or self.transition_receipt.record != self.observed_record
                or self.transition_receipt.expected_prior_revision != 0
                or self.observed_record.identity != self.candidate_identity
            ):
                raise ValueError("acquired idempotency reservation requires insert evidence")
        else:
            if self.transition_receipt is not None:
                raise ValueError("observed idempotency reservation MUST NOT claim insert evidence")
            expected_match = classify_reservation(
                self.observed_record,
                self.candidate_identity,
            )
            if self.match is not expected_match:
                raise ValueError("idempotency reserve result mismatched its candidate")


@runtime_checkable
class IdempotencyReservationStore(Protocol):
    """Atomic durable reservation compare-and-set and readback seam."""

    async def reserve(
        self,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationReserveResult:
        """Insert revision one or return a duplicate/conflict decision."""
        ...

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_prior_revision: int,
        record: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt:
        """Atomically replace the exact prior record and read it back."""
        ...

    async def read(self, idempotency_key: str) -> IdempotencyReservationRecord | None:
        """Read the authoritative current stable-key record."""
        ...


def reservation_record_to_mapping(
    record: IdempotencyReservationRecord,
) -> dict[str, object]:
    """Serialize one canonical record for durable JSON storage."""

    from .idempotency_reservation_codec import reservation_record_to_mapping as serialize

    return serialize(record)


def reservation_record_from_mapping(
    value: Mapping[str, object],
) -> IdempotencyReservationRecord:
    """Parse one exact durable record and rerun every semantic invariant."""

    from .idempotency_reservation_codec import reservation_record_from_mapping as parse

    return parse(value)


def classify_reservation(
    existing: IdempotencyReservationRecord | None,
    candidate: IdempotencyReservationIdentity,
) -> ReservationMatch:
    """Classify a stable-key candidate without granting dispatch authority."""

    if existing is None:
        return ReservationMatch.ACQUIRED
    if existing.identity.idempotency_key != candidate.idempotency_key:
        return ReservationMatch.ACQUIRED
    return (
        ReservationMatch.DUPLICATE_SAME
        if existing.identity.identity_digest == candidate.identity_digest
        else ReservationMatch.CONFLICT
    )


def _build_record(
    *,
    identity: IdempotencyReservationIdentity,
    state: ReservationState,
    revision: int,
    reserved_at: datetime,
    lease_expires_at: datetime,
    state_changed_at: datetime,
    dispatch_started_at: datetime | None = None,
    evidence_kind: ReservationEvidenceKind | None = None,
    evidence_digest: str | None = None,
    terminal_outcome_digest: str | None = None,
) -> IdempotencyReservationRecord:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "identity": identity,
        "state": state,
        "revision": revision,
        "owner_reference_digest": identity.acquisition_receipt.owner_token_digest,
        "reserved_at": reserved_at,
        "lease_expires_at": lease_expires_at,
        "state_changed_at": state_changed_at,
        "dispatch_started_at": dispatch_started_at,
        "evidence_kind": evidence_kind,
        "evidence_digest": evidence_digest,
        "terminal_outcome_digest": terminal_outcome_digest,
        "execution_authority": False,
        "effect_verified": False,
    }
    values["record_digest"] = _payload_digest(
        values,
        "idempotency-reservation-record",
        digest_field="record_digest",
    )
    return IdempotencyReservationRecord(**values)  # type: ignore[arg-type]


def _validate_state_shape(record: IdempotencyReservationRecord) -> None:
    from .idempotency_reservation_validation import validate_reservation_state_shape

    validate_reservation_state_shape(record)


def _validate_state_revision(record: IdempotencyReservationRecord) -> None:
    minimum_revision = {
        ReservationState.RESERVED: 1,
        ReservationState.IN_FLIGHT: 2,
        ReservationState.ABANDONED: 2,
        ReservationState.OUTCOME_UNKNOWN: 3,
        ReservationState.TERMINAL: 3,
    }
    if record.revision < minimum_revision[record.state]:
        raise ValueError("idempotency reservation state revision is impossible")


def _validate_transition(
    prior: IdempotencyReservationRecord,
    current: IdempotencyReservationRecord,
) -> None:
    legal_edges = {
        ReservationState.RESERVED: {
            ReservationState.IN_FLIGHT,
            ReservationState.ABANDONED,
        },
        ReservationState.IN_FLIGHT: {
            ReservationState.TERMINAL,
            ReservationState.OUTCOME_UNKNOWN,
        },
        ReservationState.OUTCOME_UNKNOWN: {ReservationState.TERMINAL},
        ReservationState.TERMINAL: {ReservationState.RESERVED},
        ReservationState.ABANDONED: {ReservationState.RESERVED},
    }
    if current.state not in legal_edges[prior.state]:
        raise ValueError("idempotency reservation transition edge is invalid")
    if current.state_changed_at < prior.state_changed_at:
        raise ValueError("idempotency reservation transition is backdated")
    if current.state is ReservationState.RESERVED:
        if not same_operation(prior.identity, current.identity):
            raise ValueError("idempotency reservation recovery changes the stable operation")
        if (
            current.identity.acquisition_receipt.attempt
            <= prior.identity.acquisition_receipt.attempt
        ):
            raise ValueError("idempotency reservation recovery attempt MUST increase")
        if not (
            prior.state_changed_at
            <= current.identity.acquisition_receipt.acquired_at
            <= current.reserved_at
        ):
            raise ValueError("idempotency reservation recovery acquisition time is invalid")
        if not (
            prior.state is ReservationState.ABANDONED
            or (
                prior.state is ReservationState.TERMINAL
                and prior.evidence_kind is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
            )
        ):
            raise ValueError("idempotency reservation recovery lacks non-dispatch evidence")
        return
    if prior.identity != current.identity:
        raise ValueError("idempotency reservation transition identity changed")
    if (
        prior.reserved_at != current.reserved_at
        or prior.lease_expires_at != current.lease_expires_at
        or prior.owner_reference_digest != current.owner_reference_digest
    ):
        raise ValueError("idempotency reservation transition rewrote its lease or owner")
    if (
        prior.dispatch_started_at is not None
        and current.dispatch_started_at != prior.dispatch_started_at
    ):
        raise ValueError("idempotency reservation transition rewrote dispatch time")


def validate_reservation_transition(
    prior: IdempotencyReservationRecord,
    current: IdempotencyReservationRecord,
) -> None:
    """Validate one exact monotonic reservation transition."""

    _validate_transition(prior, current)


def _validate_text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"idempotency reservation {name} MUST be canonical and bounded")


def _validate_digest(name: str, value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"idempotency reservation {name} MUST be SHA-256")


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"idempotency reservation {name} MUST include a timezone")
    return value.astimezone(UTC)


def _validate_utc(name: str, value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"idempotency reservation {name} MUST be normalized to UTC")


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
    value: (
        IdempotencyReservationIdentity
        | IdempotencyReservationRecord
        | IdempotencyReservationTransitionReceipt
    ),
    domain: str,
) -> str:
    digest_field = {
        IdempotencyReservationIdentity: "identity_digest",
        IdempotencyReservationRecord: "record_digest",
        IdempotencyReservationTransitionReceipt: "receipt_digest",
    }[type(value)]
    return _payload_digest(asdict(value), domain, digest_field=digest_field)


def _normalize_digest_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(
        value,
        (
            IdempotencyReservationIdentity,
            IdempotencyReservationRecord,
            IdempotencyReservationReserveResult,
            IdempotencyReservationTransitionReceipt,
            ResourceLockAcquisitionReceipt,
        ),
    ):
        return _normalize_digest_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_digest_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_digest_value(item) for item in value]
    return value


from .idempotency_reservation_lifecycle import (  # noqa: E402
    begin_dispatch,
    complete_reservation,
    complete_reservation_from_verifier,
    dispatch_permitted,
    expire_reservation,
    quarantine_reservation,
    reopen_reservation,
)

__all__ = [
    "IdempotencyReservationIdentity",
    "IdempotencyReservationRecord",
    "IdempotencyReservationReserveResult",
    "IdempotencyReservationStore",
    "IdempotencyReservationTransitionReceipt",
    "ReservationEvidenceKind",
    "ReservationMatch",
    "ReservationState",
    "begin_dispatch",
    "classify_reservation",
    "complete_reservation",
    "complete_reservation_from_verifier",
    "dispatch_permitted",
    "expire_reservation",
    "quarantine_reservation",
    "reopen_reservation",
    "reservation_record_from_mapping",
    "reservation_record_to_mapping",
    "validate_reservation_transition",
]
