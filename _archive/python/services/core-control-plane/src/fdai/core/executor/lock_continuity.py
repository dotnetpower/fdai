"""Provider-neutral ownership-through-commit policy and terminal evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    ResourceLockAcquisitionReceipt,
    require_current_lock_ownership,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class OwnershipContinuityStrategy(StrEnum):
    """Reviewed ways to preserve or reconcile ownership through commit."""

    FENCED_IDEMPOTENT = "fenced_idempotent"
    LOCK_SESSION_ATOMIC = "lock_session_atomic"
    QUARANTINED_RECONCILIATION = "quarantined_reconciliation"


class DispatchState(StrEnum):
    """Whether the effect request reached its sink."""

    NOT_STARTED = "not_started"
    ATTEMPTED = "attempted"
    ACCEPTED = "accepted"
    NOT_ACCEPTED = "not_accepted"


class SinkCommitState(StrEnum):
    """Authoritative sink-side commit knowledge."""

    NOT_STARTED = "not_started"
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    UNKNOWN = "unknown"


class IndependentEffectState(StrEnum):
    """Independent observation state, separate from dispatch and commit."""

    PENDING = "pending"
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class LockReleaseState(StrEnum):
    """Terminal knowledge about the exact acquisition release."""

    RELEASED = "released"
    LOST = "lost"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EffectSinkContinuityPolicy:
    """Reviewed sink capabilities for one ownership-continuity strategy."""

    schema_version: Literal["1.0.0"]
    sink_id: str
    sink_version: str
    strategy: OwnershipContinuityStrategy
    sink_fencing: bool
    stable_sink_idempotency: bool
    authoritative_operation_status: bool
    same_session_effect_commit: bool
    same_session_reservation_terminalization: bool
    same_session_outbox_publication: bool
    cancellation_supported: bool
    durable_unknown_quarantine: bool
    reconciliation_supported: bool
    policy_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported effect sink continuity policy schema version")
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("effect sink continuity policy MUST NOT grant authority")
        _validate_text("sink_id", self.sink_id)
        _validate_text("sink_version", self.sink_version)
        if type(self.strategy) is not OwnershipContinuityStrategy:
            raise ValueError("effect sink continuity strategy is invalid")
        capabilities = (
            self.sink_fencing,
            self.stable_sink_idempotency,
            self.authoritative_operation_status,
            self.same_session_effect_commit,
            self.same_session_reservation_terminalization,
            self.same_session_outbox_publication,
            self.cancellation_supported,
            self.durable_unknown_quarantine,
            self.reconciliation_supported,
        )
        if any(type(value) is not bool for value in capabilities):
            raise ValueError("effect sink continuity capabilities MUST be boolean")
        if self.strategy is OwnershipContinuityStrategy.FENCED_IDEMPOTENT and not (
            self.sink_fencing
            and (self.stable_sink_idempotency or self.authoritative_operation_status)
        ):
            raise ValueError("fenced continuity requires fencing and sink reconciliation")
        if self.strategy is OwnershipContinuityStrategy.LOCK_SESSION_ATOMIC and not (
            self.same_session_effect_commit
            and self.same_session_reservation_terminalization
            and self.same_session_outbox_publication
        ):
            raise ValueError("session-atomic continuity requires one complete atomic boundary")
        if self.strategy is OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION and not (
            self.cancellation_supported
            and self.durable_unknown_quarantine
            and self.reconciliation_supported
        ):
            raise ValueError("quarantined continuity requires cancellation and reconciliation")
        _validate_digest("policy_digest", self.policy_digest)
        if self.policy_digest != _content_digest(self, "effect-sink-continuity-policy"):
            raise ValueError("effect sink continuity policy digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        sink_id: str,
        sink_version: str,
        strategy: OwnershipContinuityStrategy,
        sink_fencing: bool = False,
        stable_sink_idempotency: bool = False,
        authoritative_operation_status: bool = False,
        same_session_effect_commit: bool = False,
        same_session_reservation_terminalization: bool = False,
        same_session_outbox_publication: bool = False,
        cancellation_supported: bool = False,
        durable_unknown_quarantine: bool = False,
        reconciliation_supported: bool = False,
    ) -> Self:
        """Create one immutable reviewed sink policy."""

        if cls is not EffectSinkContinuityPolicy:
            raise TypeError("effect sink continuity policy does not support subclasses")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "sink_id": sink_id,
            "sink_version": sink_version,
            "strategy": strategy,
            "sink_fencing": sink_fencing,
            "stable_sink_idempotency": stable_sink_idempotency,
            "authoritative_operation_status": authoritative_operation_status,
            "same_session_effect_commit": same_session_effect_commit,
            "same_session_reservation_terminalization": (same_session_reservation_terminalization),
            "same_session_outbox_publication": same_session_outbox_publication,
            "cancellation_supported": cancellation_supported,
            "durable_unknown_quarantine": durable_unknown_quarantine,
            "reconciliation_supported": reconciliation_supported,
            "execution_authority": False,
            "effect_verification_authority": False,
        }
        values["policy_digest"] = _payload_digest(
            values,
            "effect-sink-continuity-policy",
            digest_field="policy_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class OwnershipContinuityReceipt:
    """Terminal no-authority evidence for lock continuity and sink knowledge."""

    schema_version: Literal["1.0.0"]
    policy: EffectSinkContinuityPolicy
    acquisition_receipt: ResourceLockAcquisitionReceipt
    final_ownership_assessment: LiveLockOwnershipAssessment
    dispatch_state: DispatchState
    sink_commit_state: SinkCommitState
    independent_effect_state: IndependentEffectState
    release_state: LockReleaseState
    authoritative_status_digest: str | None
    independent_effect_receipt_digest: str | None
    ownership_observed_at: datetime
    recorded_at: datetime
    quarantine_required: bool
    receipt_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported ownership continuity receipt schema version")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("ownership continuity receipt MUST NOT grant authority")
        if type(self.policy) is not EffectSinkContinuityPolicy:
            raise ValueError("ownership continuity receipt requires an exact sink policy")
        if type(self.acquisition_receipt) is not ResourceLockAcquisitionReceipt:
            raise ValueError("ownership continuity receipt requires an exact acquisition receipt")
        if type(self.final_ownership_assessment) is not LiveLockOwnershipAssessment:
            raise ValueError("ownership continuity receipt requires an exact ownership assessment")
        if self.final_ownership_assessment.acquisition_receipt != self.acquisition_receipt:
            raise ValueError("ownership continuity assessment does not bind the acquisition")
        if (
            self.policy.strategy is OwnershipContinuityStrategy.FENCED_IDEMPOTENT
            and self.acquisition_receipt.fencing_generation is None
        ):
            raise ValueError("fenced continuity requires a fenced lease acquisition")
        if (
            self.policy.strategy is OwnershipContinuityStrategy.LOCK_SESSION_ATOMIC
            and self.acquisition_receipt.session_identity is None
        ):
            raise ValueError("session-atomic continuity requires a session acquisition")
        for state_value, expected_type, name in (
            (self.dispatch_state, DispatchState, "dispatch"),
            (self.sink_commit_state, SinkCommitState, "sink commit"),
            (self.independent_effect_state, IndependentEffectState, "independent effect"),
            (self.release_state, LockReleaseState, "lock release"),
        ):
            if type(state_value) is not expected_type:
                raise ValueError(f"ownership continuity {name} state is invalid")
        _validate_utc("ownership_observed_at", self.ownership_observed_at)
        _validate_utc("recorded_at", self.recorded_at)
        if self.ownership_observed_at > self.recorded_at:
            raise ValueError("ownership continuity observation cannot follow recording")
        require_current_lock_ownership(
            self.final_ownership_assessment,
            observed_at=self.ownership_observed_at,
        )
        for name, digest_value in (
            ("authoritative_status_digest", self.authoritative_status_digest),
            ("independent_effect_receipt_digest", self.independent_effect_receipt_digest),
        ):
            if digest_value is not None:
                _validate_digest(name, digest_value)
        _validate_terminal_axes(self)
        expected_quarantine = _requires_quarantine(
            dispatch_state=self.dispatch_state,
            sink_commit_state=self.sink_commit_state,
            release_state=self.release_state,
        )
        if type(self.quarantine_required) is not bool:
            raise ValueError("ownership continuity quarantine flag MUST be boolean")
        if self.quarantine_required is not expected_quarantine:
            raise ValueError("ownership continuity quarantine flag mismatched terminal state")
        _validate_digest("receipt_digest", self.receipt_digest)
        if self.receipt_digest != _content_digest(self, "ownership-continuity-receipt"):
            raise ValueError("ownership continuity receipt digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        policy: EffectSinkContinuityPolicy,
        acquisition_receipt: ResourceLockAcquisitionReceipt,
        final_ownership_assessment: LiveLockOwnershipAssessment,
        dispatch_state: DispatchState,
        sink_commit_state: SinkCommitState,
        independent_effect_state: IndependentEffectState,
        release_state: LockReleaseState,
        authoritative_status_digest: str | None,
        independent_effect_receipt_digest: str | None,
        ownership_observed_at: datetime,
        recorded_at: datetime,
    ) -> Self:
        """Create one terminal continuity receipt without a success claim."""

        if cls is not OwnershipContinuityReceipt:
            raise TypeError("ownership continuity receipt does not support subclasses")
        normalized_observed_at = _utc(ownership_observed_at, "ownership_observed_at")
        normalized_recorded_at = _utc(recorded_at, "recorded_at")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "policy": policy,
            "acquisition_receipt": acquisition_receipt,
            "final_ownership_assessment": final_ownership_assessment,
            "dispatch_state": dispatch_state,
            "sink_commit_state": sink_commit_state,
            "independent_effect_state": independent_effect_state,
            "release_state": release_state,
            "authoritative_status_digest": authoritative_status_digest,
            "independent_effect_receipt_digest": independent_effect_receipt_digest,
            "ownership_observed_at": normalized_observed_at,
            "recorded_at": normalized_recorded_at,
            "quarantine_required": _requires_quarantine(
                dispatch_state=dispatch_state,
                sink_commit_state=sink_commit_state,
                release_state=release_state,
            ),
            "execution_authority": False,
            "effect_verified": False,
        }
        values["receipt_digest"] = _payload_digest(
            values,
            "ownership-continuity-receipt",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


def _validate_terminal_axes(receipt: OwnershipContinuityReceipt) -> None:
    if receipt.dispatch_state is DispatchState.NOT_STARTED:
        if receipt.sink_commit_state is not SinkCommitState.NOT_STARTED:
            raise ValueError("undispatched continuity cannot claim sink commit knowledge")
    elif receipt.dispatch_state is DispatchState.NOT_ACCEPTED:
        if receipt.sink_commit_state is not SinkCommitState.NOT_COMMITTED:
            raise ValueError("non-accepted dispatch requires authoritative non-commit")
        if receipt.authoritative_status_digest is None:
            raise ValueError("non-accepted dispatch requires authoritative sink status")
    elif receipt.sink_commit_state is SinkCommitState.NOT_STARTED:
        raise ValueError("attempted dispatch cannot retain a not-started sink state")
    if receipt.sink_commit_state is SinkCommitState.COMMITTED:
        if receipt.dispatch_state is not DispatchState.ACCEPTED:
            raise ValueError("sink commit requires accepted dispatch")
    if receipt.sink_commit_state is SinkCommitState.NOT_COMMITTED:
        if receipt.authoritative_status_digest is None:
            raise ValueError("sink non-commit requires authoritative status")
    if receipt.independent_effect_state in {
        IndependentEffectState.VERIFIED,
        IndependentEffectState.MISMATCH,
    }:
        if receipt.independent_effect_receipt_digest is None:
            raise ValueError("independent effect decision requires its receipt")
    elif receipt.independent_effect_receipt_digest is not None:
        raise ValueError("pending or unknown effect state cannot carry a decision receipt")


def _requires_quarantine(
    *,
    dispatch_state: DispatchState,
    sink_commit_state: SinkCommitState,
    release_state: LockReleaseState,
) -> bool:
    return bool(
        sink_commit_state is SinkCommitState.UNKNOWN
        or release_state in {LockReleaseState.LOST, LockReleaseState.UNKNOWN}
        or (
            dispatch_state in {DispatchState.ATTEMPTED, DispatchState.ACCEPTED}
            and sink_commit_state is not SinkCommitState.COMMITTED
        )
    )


def _validate_text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ValueError(f"ownership continuity {name} MUST be bounded")


def _validate_digest(name: str, value: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"ownership continuity {name} MUST be SHA-256")


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"ownership continuity {name} MUST include a timezone")
    return value.astimezone(UTC)


def _validate_utc(name: str, value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"ownership continuity {name} MUST be normalized to UTC")


def _payload_digest(
    payload: Mapping[str, object],
    domain: str,
    *,
    digest_field: str,
) -> str:
    body = dict(payload)
    body.pop(digest_field, None)
    return content_digest(
        {
            "domain": domain,
            "body": _normalize_digest_value(body),
        }
    )


def _content_digest(
    value: EffectSinkContinuityPolicy | OwnershipContinuityReceipt,
    domain: str,
) -> str:
    digest_field = (
        "policy_digest" if type(value) is EffectSinkContinuityPolicy else "receipt_digest"
    )
    return _payload_digest(asdict(value), domain, digest_field=digest_field)


def _normalize_digest_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(
        value,
        (
            EffectSinkContinuityPolicy,
            OwnershipContinuityReceipt,
            ResourceLockAcquisitionReceipt,
            LiveLockOwnershipAssessment,
        ),
    ):
        return _normalize_digest_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _normalize_digest_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_digest_value(item) for item in value]
    return value


__all__ = [
    "DispatchState",
    "EffectSinkContinuityPolicy",
    "IndependentEffectState",
    "LockReleaseState",
    "OwnershipContinuityReceipt",
    "OwnershipContinuityStrategy",
    "SinkCommitState",
]
