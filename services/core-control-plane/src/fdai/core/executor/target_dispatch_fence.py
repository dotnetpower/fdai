"""Target-wide mutation fence identity, transitions, and durable store seam."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from typing import TYPE_CHECKING, Literal, Self

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.audit_intent import AuditIntentAppendReceipt
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")

if TYPE_CHECKING:
    from fdai.core.executor.target_dispatch_fence_store import (
        TargetDispatchFenceAcquireDecision,
        TargetDispatchFenceAcquireResult,
        TargetDispatchFenceStore,
        classify_target_fence,
        target_mutation_blocked,
    )


class TargetDispatchFenceState(StrEnum):
    """Monotonic target-wide mutation admission state."""

    PREPARING = "preparing"
    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    RELEASE_PENDING = "release_pending"
    RESOLVED = "resolved"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class TargetDispatchFenceIdentity:
    """Exact target, attempt, policy, and sink correlation for one generation."""

    schema_version: Literal["1.0.0"]
    target_digest: str
    reservation_identity_digest: str
    reservation_attempt: int
    acquisition_receipt_digest: str
    acquisition_acquired_at: datetime
    continuity_policy_digest: str
    continuity_strategy: Literal["quarantined_reconciliation"]
    generation: int
    client_correlation_id: str
    sink_idempotency_key: str
    identity_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported target dispatch fence identity schema")
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("target dispatch fence identity MUST NOT grant authority")
        _validate_digest("target_digest", self.target_digest)
        _validate_digest(
            "reservation_identity_digest",
            self.reservation_identity_digest,
        )
        if type(self.reservation_attempt) is not int or self.reservation_attempt < 1:
            raise ValueError("target dispatch fence reservation attempt MUST be positive")
        _validate_digest(
            "acquisition_receipt_digest",
            self.acquisition_receipt_digest,
        )
        _validate_utc("acquisition_acquired_at", self.acquisition_acquired_at)
        _validate_digest(
            "continuity_policy_digest",
            self.continuity_policy_digest,
        )
        if (
            type(self.continuity_strategy) is not str
            or self.continuity_strategy != "quarantined_reconciliation"
        ):
            raise ValueError("target dispatch fence supports quarantined reconciliation only")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("target dispatch fence generation MUST be positive")
        _validate_text("client_correlation_id", self.client_correlation_id)
        _validate_text("sink_idempotency_key", self.sink_idempotency_key)
        _validate_digest("identity_digest", self.identity_digest)
        if self.identity_digest != _content_digest(self, "target-dispatch-fence-identity"):
            raise ValueError("target dispatch fence identity digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        target_digest: str,
        reservation_identity: IdempotencyReservationIdentity,
        continuity_policy: EffectSinkContinuityPolicy,
        generation: int,
        client_correlation_id: str,
        sink_idempotency_key: str,
    ) -> Self:
        """Create one target fence identity before audit, bundle, or sink work."""

        if cls is not TargetDispatchFenceIdentity:
            raise TypeError("target dispatch fence identity does not support subclasses")
        if type(reservation_identity) is not IdempotencyReservationIdentity:
            raise ValueError("target dispatch fence requires an exact reservation identity")
        acquisition = reservation_identity.acquisition_receipt
        if acquisition.target_digest != target_digest:
            raise ValueError("target dispatch fence target mismatched acquisition")
        if type(continuity_policy) is not EffectSinkContinuityPolicy:
            raise ValueError("target dispatch fence requires an exact continuity policy")
        if continuity_policy.strategy is not OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION:
            raise ValueError("target dispatch fence supports quarantined reconciliation only")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "target_digest": target_digest,
            "reservation_identity_digest": reservation_identity.identity_digest,
            "reservation_attempt": acquisition.attempt,
            "acquisition_receipt_digest": acquisition.receipt_digest,
            "acquisition_acquired_at": acquisition.acquired_at,
            "continuity_policy_digest": continuity_policy.policy_digest,
            "continuity_strategy": continuity_policy.strategy.value,
            "generation": generation,
            "client_correlation_id": client_correlation_id,
            "sink_idempotency_key": sink_idempotency_key,
            "execution_authority": False,
            "effect_verification_authority": False,
        }
        values["identity_digest"] = _payload_digest(
            values,
            "target-dispatch-fence-identity",
            digest_field="identity_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class TargetDispatchFenceRecord:
    """Immutable current record for one target generation."""

    schema_version: Literal["1.0.0"]
    identity: TargetDispatchFenceIdentity
    state: TargetDispatchFenceState
    revision: int
    prior_record_digest: str | None
    audit_append_receipt_digest: str | None
    safeguard_bundle_digest: str | None
    state_changed_at: datetime
    no_dispatch_evidence_digest: str | None
    resolution_evidence_digest: str | None
    record_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported target dispatch fence record schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("target dispatch fence record MUST NOT grant authority")
        if type(self.identity) is not TargetDispatchFenceIdentity:
            raise ValueError("target dispatch fence record requires an exact identity")
        if type(self.state) is not TargetDispatchFenceState:
            raise ValueError("target dispatch fence state is invalid")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("target dispatch fence revision MUST be positive")
        if self.revision == 1:
            if self.prior_record_digest is not None:
                raise ValueError("initial target dispatch fence MUST NOT have a predecessor")
        else:
            if self.prior_record_digest is None:
                raise ValueError("target dispatch fence transition requires predecessor digest")
            _validate_digest("prior_record_digest", self.prior_record_digest)
        for name, value in (
            ("audit_append_receipt_digest", self.audit_append_receipt_digest),
            ("safeguard_bundle_digest", self.safeguard_bundle_digest),
            ("no_dispatch_evidence_digest", self.no_dispatch_evidence_digest),
            ("resolution_evidence_digest", self.resolution_evidence_digest),
        ):
            if value is not None:
                _validate_digest(name, value)
        _validate_utc("state_changed_at", self.state_changed_at)
        if self.state_changed_at < self.identity.acquisition_acquired_at:
            raise ValueError("target dispatch fence predates lock acquisition")
        _validate_record_shape(self)
        _validate_digest("record_digest", self.record_digest)
        if self.record_digest != _content_digest(self, "target-dispatch-fence-record"):
            raise ValueError("target dispatch fence record digest mismatched")

    @classmethod
    def create_preparing(
        cls,
        *,
        identity: TargetDispatchFenceIdentity,
        changed_at: datetime,
        prior_resolved_record: TargetDispatchFenceRecord | None = None,
    ) -> TargetDispatchFenceRecord:
        """Create generation one or advance an exact resolved predecessor."""

        if cls is not TargetDispatchFenceRecord:
            raise TypeError("target dispatch fence record does not support subclasses")
        if prior_resolved_record is None:
            if identity.generation != 1:
                raise ValueError("initial target dispatch fence generation MUST be one")
            revision = 1
            prior_digest = None
        else:
            if type(prior_resolved_record) is not TargetDispatchFenceRecord:
                raise ValueError("target dispatch fence predecessor is invalid")
            if prior_resolved_record.state is not TargetDispatchFenceState.RESOLVED:
                raise ValueError("new target dispatch generation requires resolved predecessor")
            if prior_resolved_record.identity.target_digest != identity.target_digest:
                raise ValueError("new target dispatch generation changes target")
            if identity.generation != prior_resolved_record.identity.generation + 1:
                raise ValueError("target dispatch fence generation MUST increase by one")
            if (
                identity.acquisition_acquired_at <= prior_resolved_record.state_changed_at
                or identity.reservation_identity_digest
                == prior_resolved_record.identity.reservation_identity_digest
            ):
                raise ValueError("new target dispatch requires a later acquisition")
            revision = prior_resolved_record.revision + 1
            prior_digest = prior_resolved_record.record_digest
        return _build_record(
            identity=identity,
            state=TargetDispatchFenceState.PREPARING,
            revision=revision,
            prior_record_digest=prior_digest,
            state_changed_at=_utc(changed_at, "changed_at"),
        )


@dataclass(frozen=True, slots=True)
class TargetDispatchFenceTransitionReceipt:
    """Exact-predecessor CAS and authoritative readback evidence."""

    schema_version: Literal["1.0.0"]
    prior_record: TargetDispatchFenceRecord | None
    record: TargetDispatchFenceRecord
    store_receipt_digest: str
    recorded_at: datetime
    receipt_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported target dispatch fence transition receipt schema")
        if self.execution_authority is not False:
            raise ValueError("target dispatch fence transition MUST NOT grant authority")
        if type(self.record) is not TargetDispatchFenceRecord:
            raise ValueError("target dispatch fence transition requires an exact record")
        if self.prior_record is None:
            if (
                self.record.revision != 1
                or self.record.prior_record_digest is not None
                or self.record.state is not TargetDispatchFenceState.PREPARING
                or self.record.identity.generation != 1
            ):
                raise ValueError("initial target dispatch fence transition is invalid")
        else:
            if type(self.prior_record) is not TargetDispatchFenceRecord:
                raise ValueError("target dispatch fence transition predecessor is invalid")
            _validate_transition(self.prior_record, self.record)
        _validate_digest("store_receipt_digest", self.store_receipt_digest)
        _validate_utc("recorded_at", self.recorded_at)
        if self.recorded_at < self.record.state_changed_at or (
            self.prior_record is not None and self.recorded_at < self.prior_record.state_changed_at
        ):
            raise ValueError("target dispatch fence transition receipt is backdated")
        _validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != _content_digest(
            self,
            "target-dispatch-fence-transition",
        ):
            raise ValueError("target dispatch fence transition receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        prior_record: TargetDispatchFenceRecord | None,
        record: TargetDispatchFenceRecord,
        store_receipt_digest: str,
        recorded_at: datetime,
    ) -> Self:
        """Create evidence after atomic persistence and exact readback."""

        if cls is not TargetDispatchFenceTransitionReceipt:
            raise TypeError("target dispatch fence transition does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "prior_record": prior_record,
            "record": record,
            "store_receipt_digest": store_receipt_digest,
            "recorded_at": _utc(recorded_at, "recorded_at"),
            "execution_authority": False,
        }
        values["receipt_digest"] = _payload_digest(
            values,
            "target-dispatch-fence-transition",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


def attach_prepared_evidence(
    record: TargetDispatchFenceRecord,
    *,
    audit_append_receipt: AuditIntentAppendReceipt,
    safeguard_bundle_digest: str,
    changed_at: datetime,
) -> TargetDispatchFenceRecord:
    """CAS-fill exact audit and bundle evidence before sink dispatch."""

    if record.state is not TargetDispatchFenceState.PREPARING:
        raise ValueError("target dispatch fence is not preparing")
    reservation_identity = audit_append_receipt.intent.reservation_receipt.record.identity
    if reservation_identity.identity_digest != record.identity.reservation_identity_digest:
        raise ValueError("target dispatch fence audit evidence changed reservation")
    normalized_at = _utc(changed_at, "changed_at")
    if normalized_at < audit_append_receipt.read_back_at:
        raise ValueError("target dispatch fence prepared before audit readback")
    _validate_digest("safeguard_bundle_digest", safeguard_bundle_digest)
    return _next_record(
        record,
        state=TargetDispatchFenceState.PREPARED,
        changed_at=normalized_at,
        audit_append_receipt_digest=audit_append_receipt.receipt_digest,
        safeguard_bundle_digest=safeguard_bundle_digest,
    )


def mark_target_fence_in_flight(
    record: TargetDispatchFenceRecord,
    *,
    changed_at: datetime,
) -> TargetDispatchFenceRecord:
    """Fence the whole target before the sink can observe a request."""

    if record.state is not TargetDispatchFenceState.PREPARED:
        raise ValueError("target dispatch fence is not prepared")
    return _next_record(
        record,
        state=TargetDispatchFenceState.IN_FLIGHT,
        changed_at=changed_at,
    )


def mark_target_fence_release_pending(
    record: TargetDispatchFenceRecord,
    *,
    changed_at: datetime,
) -> TargetDispatchFenceRecord:
    """Persist the pre-release checkpoint before leaving the lock context."""

    if record.state is not TargetDispatchFenceState.IN_FLIGHT:
        raise ValueError("target dispatch fence is not in flight")
    return _next_record(
        record,
        state=TargetDispatchFenceState.RELEASE_PENDING,
        changed_at=changed_at,
    )


def resolve_target_fence_without_dispatch(
    record: TargetDispatchFenceRecord,
    *,
    no_dispatch_evidence_digest: str,
    changed_at: datetime,
) -> TargetDispatchFenceRecord:
    """Resolve preparation only with authoritative no-dispatch evidence."""

    if record.state not in {
        TargetDispatchFenceState.PREPARING,
        TargetDispatchFenceState.PREPARED,
        TargetDispatchFenceState.IN_FLIGHT,
    }:
        raise ValueError("target dispatch fence cannot resolve as undispatched")
    _validate_digest(
        "no_dispatch_evidence_digest",
        no_dispatch_evidence_digest,
    )
    return _next_record(
        record,
        state=TargetDispatchFenceState.RESOLVED,
        changed_at=changed_at,
        no_dispatch_evidence_digest=no_dispatch_evidence_digest,
        clear_prepared_evidence=True,
    )


def close_target_fence_after_release(
    record: TargetDispatchFenceRecord,
    *,
    quarantined: bool,
    resolution_evidence_digest: str,
    changed_at: datetime,
) -> TargetDispatchFenceRecord:
    """Resolve or quarantine the exact release-pending generation."""

    if record.state not in {
        TargetDispatchFenceState.RELEASE_PENDING,
        TargetDispatchFenceState.QUARANTINED,
    }:
        raise ValueError("target dispatch fence is not terminalizable")
    if record.state is TargetDispatchFenceState.QUARANTINED and quarantined:
        raise ValueError("quarantined target dispatch fence requires resolution")
    _validate_digest(
        "resolution_evidence_digest",
        resolution_evidence_digest,
    )
    if (
        record.state is TargetDispatchFenceState.QUARANTINED
        and resolution_evidence_digest == record.resolution_evidence_digest
    ):
        raise ValueError("quarantined target dispatch fence requires fresh reconciliation evidence")
    return _next_record(
        record,
        state=(
            TargetDispatchFenceState.QUARANTINED
            if quarantined
            else TargetDispatchFenceState.RESOLVED
        ),
        changed_at=changed_at,
        resolution_evidence_digest=resolution_evidence_digest,
    )


def _next_record(
    record: TargetDispatchFenceRecord,
    *,
    state: TargetDispatchFenceState,
    changed_at: datetime,
    audit_append_receipt_digest: str | None = None,
    safeguard_bundle_digest: str | None = None,
    no_dispatch_evidence_digest: str | None = None,
    resolution_evidence_digest: str | None = None,
    clear_prepared_evidence: bool = False,
) -> TargetDispatchFenceRecord:
    normalized_at = _utc(changed_at, "changed_at")
    if normalized_at < record.state_changed_at:
        raise ValueError("target dispatch fence transition is backdated")
    return _build_record(
        identity=record.identity,
        state=state,
        revision=record.revision + 1,
        prior_record_digest=record.record_digest,
        audit_append_receipt_digest=(
            None
            if clear_prepared_evidence
            else (
                audit_append_receipt_digest
                if audit_append_receipt_digest is not None
                else record.audit_append_receipt_digest
            )
        ),
        safeguard_bundle_digest=(
            None
            if clear_prepared_evidence
            else (
                safeguard_bundle_digest
                if safeguard_bundle_digest is not None
                else record.safeguard_bundle_digest
            )
        ),
        state_changed_at=normalized_at,
        no_dispatch_evidence_digest=no_dispatch_evidence_digest,
        resolution_evidence_digest=resolution_evidence_digest,
    )


def _build_record(
    *,
    identity: TargetDispatchFenceIdentity,
    state: TargetDispatchFenceState,
    revision: int,
    prior_record_digest: str | None,
    state_changed_at: datetime,
    audit_append_receipt_digest: str | None = None,
    safeguard_bundle_digest: str | None = None,
    no_dispatch_evidence_digest: str | None = None,
    resolution_evidence_digest: str | None = None,
) -> TargetDispatchFenceRecord:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "identity": identity,
        "state": state,
        "revision": revision,
        "prior_record_digest": prior_record_digest,
        "audit_append_receipt_digest": audit_append_receipt_digest,
        "safeguard_bundle_digest": safeguard_bundle_digest,
        "state_changed_at": state_changed_at,
        "no_dispatch_evidence_digest": no_dispatch_evidence_digest,
        "resolution_evidence_digest": resolution_evidence_digest,
        "execution_authority": False,
        "effect_verified": False,
    }
    values["record_digest"] = _payload_digest(
        values,
        "target-dispatch-fence-record",
        digest_field="record_digest",
    )
    return TargetDispatchFenceRecord(**values)  # type: ignore[arg-type]


def _validate_record_shape(record: TargetDispatchFenceRecord) -> None:
    has_prerequisites = bool(
        record.audit_append_receipt_digest is not None
        and record.safeguard_bundle_digest is not None
    )
    if (record.audit_append_receipt_digest is None) != (record.safeguard_bundle_digest is None):
        raise ValueError("target dispatch fence prerequisites are partial")
    if record.state is TargetDispatchFenceState.PREPARING:
        if (
            has_prerequisites
            or record.no_dispatch_evidence_digest is not None
            or record.resolution_evidence_digest is not None
        ):
            raise ValueError("preparing target dispatch fence shape is invalid")
    elif record.state in {
        TargetDispatchFenceState.PREPARED,
        TargetDispatchFenceState.IN_FLIGHT,
        TargetDispatchFenceState.RELEASE_PENDING,
    }:
        if (
            not has_prerequisites
            or record.no_dispatch_evidence_digest is not None
            or record.resolution_evidence_digest is not None
        ):
            raise ValueError("active target dispatch fence shape is invalid")
    elif record.state is TargetDispatchFenceState.QUARANTINED:
        if not has_prerequisites or record.resolution_evidence_digest is None:
            raise ValueError("quarantined target dispatch fence requires terminal evidence")
    elif record.no_dispatch_evidence_digest is None:
        if not has_prerequisites or record.resolution_evidence_digest is None:
            raise ValueError("resolved target dispatch fence requires closure evidence")
    elif has_prerequisites and record.state is TargetDispatchFenceState.RESOLVED:
        raise ValueError("no-dispatch closure cannot retain prepared prerequisites")


def _validate_transition(
    prior: TargetDispatchFenceRecord,
    current: TargetDispatchFenceRecord,
) -> None:
    if (
        prior.state is TargetDispatchFenceState.RESOLVED
        and current.state is TargetDispatchFenceState.PREPARING
    ):
        if (
            current.revision != prior.revision + 1
            or current.prior_record_digest != prior.record_digest
            or current.identity.target_digest != prior.identity.target_digest
            or current.identity.generation != prior.identity.generation + 1
            or current.identity.acquisition_acquired_at <= prior.state_changed_at
            or current.identity.reservation_identity_digest
            == prior.identity.reservation_identity_digest
            or current.state_changed_at < prior.state_changed_at
        ):
            raise ValueError("target dispatch fence generation advance is invalid")
        return
    if (
        current.identity != prior.identity
        or current.revision != prior.revision + 1
        or current.prior_record_digest != prior.record_digest
        or current.state_changed_at < prior.state_changed_at
    ):
        raise ValueError("target dispatch fence predecessor mismatched")
    legal_edges = {
        TargetDispatchFenceState.PREPARING: {
            TargetDispatchFenceState.PREPARED,
            TargetDispatchFenceState.RESOLVED,
        },
        TargetDispatchFenceState.PREPARED: {
            TargetDispatchFenceState.IN_FLIGHT,
            TargetDispatchFenceState.RESOLVED,
        },
        TargetDispatchFenceState.IN_FLIGHT: {
            TargetDispatchFenceState.RELEASE_PENDING,
            TargetDispatchFenceState.RESOLVED,
        },
        TargetDispatchFenceState.RELEASE_PENDING: {
            TargetDispatchFenceState.RESOLVED,
            TargetDispatchFenceState.QUARANTINED,
        },
        TargetDispatchFenceState.QUARANTINED: {
            TargetDispatchFenceState.RESOLVED,
        },
        TargetDispatchFenceState.RESOLVED: set(),
    }
    if current.state not in legal_edges[prior.state]:
        raise ValueError("target dispatch fence transition edge is invalid")
    _validate_transition_evidence(prior, current)


def _validate_transition_evidence(
    prior: TargetDispatchFenceRecord,
    current: TargetDispatchFenceRecord,
) -> None:
    if (
        prior.state
        in {
            TargetDispatchFenceState.PREPARING,
            TargetDispatchFenceState.PREPARED,
            TargetDispatchFenceState.IN_FLIGHT,
        }
        and current.state is TargetDispatchFenceState.RESOLVED
    ):
        if (
            current.no_dispatch_evidence_digest is None
            or current.audit_append_receipt_digest is not None
            or current.safeguard_bundle_digest is not None
            or current.resolution_evidence_digest is not None
        ):
            raise ValueError("target dispatch fence pre-dispatch closure evidence is invalid")
        return
    if current.state is TargetDispatchFenceState.PREPARED:
        if (
            prior.audit_append_receipt_digest is not None
            or prior.safeguard_bundle_digest is not None
            or current.audit_append_receipt_digest is None
            or current.safeguard_bundle_digest is None
        ):
            raise ValueError("target dispatch fence prepared evidence transition is invalid")
        return
    if current.no_dispatch_evidence_digest is not None:
        if (
            current.state is not TargetDispatchFenceState.RESOLVED
            or prior.state
            not in {
                TargetDispatchFenceState.PREPARING,
                TargetDispatchFenceState.PREPARED,
            }
            or current.audit_append_receipt_digest is not None
            or current.safeguard_bundle_digest is not None
            or current.resolution_evidence_digest is not None
        ):
            raise ValueError("target dispatch fence no-dispatch evidence transition is invalid")
        return
    if prior.state in {
        TargetDispatchFenceState.PREPARED,
        TargetDispatchFenceState.IN_FLIGHT,
        TargetDispatchFenceState.RELEASE_PENDING,
        TargetDispatchFenceState.QUARANTINED,
    } and (
        current.audit_append_receipt_digest != prior.audit_append_receipt_digest
        or current.safeguard_bundle_digest != prior.safeguard_bundle_digest
    ):
        raise ValueError("target dispatch fence prepared evidence was rewritten")
    if (
        prior.state is TargetDispatchFenceState.QUARANTINED
        and current.state is TargetDispatchFenceState.RESOLVED
        and current.resolution_evidence_digest == prior.resolution_evidence_digest
    ):
        raise ValueError("target dispatch fence reconciliation evidence is not fresh")
    if current.state in {
        TargetDispatchFenceState.IN_FLIGHT,
        TargetDispatchFenceState.RELEASE_PENDING,
    }:
        if (
            current.no_dispatch_evidence_digest is not None
            or current.resolution_evidence_digest is not None
        ):
            raise ValueError("active target dispatch fence contains terminal evidence")
    elif (
        current.state
        in {
            TargetDispatchFenceState.RESOLVED,
            TargetDispatchFenceState.QUARANTINED,
        }
        and current.resolution_evidence_digest is None
    ):
        raise ValueError("terminal target dispatch fence lacks resolution evidence")


def validate_target_fence_transition(
    prior: TargetDispatchFenceRecord,
    current: TargetDispatchFenceRecord,
) -> None:
    """Validate one exact monotonic target-fence transition."""

    _validate_transition(prior, current)


def _validate_text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"target dispatch fence {name} MUST be canonical and bounded")


def _validate_digest(name: str, value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"target dispatch fence {name} MUST be SHA-256")


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"target dispatch fence {name} MUST include a timezone")
    return value.astimezone(UTC)


def _validate_utc(name: str, value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"target dispatch fence {name} MUST be normalized to UTC")


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
        TargetDispatchFenceIdentity
        | TargetDispatchFenceRecord
        | TargetDispatchFenceTransitionReceipt
    ),
    domain: str,
) -> str:
    digest_field = {
        TargetDispatchFenceIdentity: "identity_digest",
        TargetDispatchFenceRecord: "record_digest",
        TargetDispatchFenceTransitionReceipt: "receipt_digest",
    }[type(value)]
    return _payload_digest(
        asdict(value),
        domain,
        digest_field=digest_field,
    )


def _normalize_digest_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(
        value,
        (
            TargetDispatchFenceIdentity,
            TargetDispatchFenceRecord,
            TargetDispatchFenceTransitionReceipt,
        ),
    ):
        return _normalize_digest_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_digest_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_digest_value(item) for item in value]
    return value


def __getattr__(name: str) -> object:
    """Lazily preserve store-symbol imports from the original module."""

    store_module = import_module("fdai.core.executor.target_dispatch_fence_store")
    if name not in store_module.__all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(store_module, name)
    return value


__all__ = [
    "TargetDispatchFenceAcquireDecision",
    "TargetDispatchFenceAcquireResult",
    "TargetDispatchFenceIdentity",
    "TargetDispatchFenceRecord",
    "TargetDispatchFenceState",
    "TargetDispatchFenceStore",
    "TargetDispatchFenceTransitionReceipt",
    "attach_prepared_evidence",
    "classify_target_fence",
    "close_target_fence_after_release",
    "mark_target_fence_in_flight",
    "mark_target_fence_release_pending",
    "resolve_target_fence_without_dispatch",
    "target_mutation_blocked",
    "validate_target_fence_transition",
]
