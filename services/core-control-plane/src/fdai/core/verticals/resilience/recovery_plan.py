"""Immutable control-plane recovery plan and legal transition reducer."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class RecoveryProfile(StrEnum):
    """Amount of alternate-region infrastructure kept ready."""

    RESTORE = "restore"
    WARM = "warm"


class RecoveryMode(StrEnum):
    """Whether a plan activation is an exercise or a real incident."""

    DRILL = "drill"
    INCIDENT = "incident"


class RecoveryState(StrEnum):
    """Durable state of one immutable recovery-plan revision."""

    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    ACTIVATING = "activating"
    PRIMARY_FENCED = "primary_fenced"
    STATE_RESTORED = "state_restored"
    RUNTIME_STARTED = "runtime_started"
    AUDIT_VERIFIED = "audit_verified"
    EVENT_RECOVERY_READY = "event_recovery_ready"
    TRAFFIC_SHIFTED = "traffic_shifted"
    SERVICE_VERIFIED = "service_verified"
    ACTIVE_RECOVERY = "active_recovery"
    FAILBACK_READY = "failback_ready"
    FAILING_BACK = "failing_back"
    PRIMARY_VERIFIED = "primary_verified"
    CLOSED = "closed"
    HALTED = "halted"


_ORDERED_STATES: Final[tuple[RecoveryState, ...]] = (
    RecoveryState.DRAFT,
    RecoveryState.READY,
    RecoveryState.APPROVED,
    RecoveryState.ACTIVATING,
    RecoveryState.PRIMARY_FENCED,
    RecoveryState.STATE_RESTORED,
    RecoveryState.RUNTIME_STARTED,
    RecoveryState.AUDIT_VERIFIED,
    RecoveryState.EVENT_RECOVERY_READY,
    RecoveryState.TRAFFIC_SHIFTED,
    RecoveryState.SERVICE_VERIFIED,
    RecoveryState.ACTIVE_RECOVERY,
    RecoveryState.FAILBACK_READY,
    RecoveryState.FAILING_BACK,
    RecoveryState.PRIMARY_VERIFIED,
    RecoveryState.CLOSED,
)

_ACTIVATING_INDEX = _ORDERED_STATES.index(RecoveryState.ACTIVATING)
_HALTABLE_STATES: Final[frozenset[RecoveryState]] = frozenset(_ORDERED_STATES[_ACTIVATING_INDEX:-1])

_legal_recovery_transitions: dict[RecoveryState, frozenset[RecoveryState]] = {
    state: frozenset(
        {
            *({_ORDERED_STATES[index + 1]} if index + 1 < len(_ORDERED_STATES) else set()),
            *({RecoveryState.HALTED} if state in _HALTABLE_STATES else set()),
        }
    )
    for index, state in enumerate(_ORDERED_STATES)
}
_legal_recovery_transitions[RecoveryState.HALTED] = frozenset()
LEGAL_RECOVERY_TRANSITIONS: Final[Mapping[RecoveryState, frozenset[RecoveryState]]] = (
    MappingProxyType(_legal_recovery_transitions)
)

_EPOCH_STATES: Final[frozenset[RecoveryState]] = frozenset(
    state
    for state in RecoveryState
    if state not in {RecoveryState.DRAFT, RecoveryState.READY, RecoveryState.APPROVED}
)
_APPROVAL_STATES: Final = frozenset({RecoveryState.APPROVED, RecoveryState.FAILBACK_READY})
_MAX_PLAN_ID_CHARS = 128
_MAX_REF_CHARS = 256
_MAX_EVIDENCE_REFS = 32
_MAX_RECOVERY_EPOCH = (2**63) - 1


class RecoveryPlanError(ValueError):
    """Raised when a plan or transition cannot be proven safe."""


@dataclass(frozen=True, slots=True)
class RecoveryObjectives:
    """Approved numeric objectives for one deployment recovery plan."""

    rpo_seconds: float
    rto_seconds: float
    max_degraded_seconds: float

    def __post_init__(self) -> None:
        _require_finite_non_negative("rpo_seconds", self.rpo_seconds)
        _require_finite_positive("rto_seconds", self.rto_seconds)
        _require_finite_positive("max_degraded_seconds", self.max_degraded_seconds)
        if self.max_degraded_seconds < self.rto_seconds:
            raise RecoveryPlanError("max_degraded_seconds MUST be >= rto_seconds")


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """One immutable, versioned control-plane recovery plan projection."""

    plan_id: str
    revision: int
    mode: RecoveryMode
    profile: RecoveryProfile
    primary_region: str
    recovery_region: str
    requester_ref: str
    scope: tuple[str, ...]
    objectives: RecoveryObjectives
    stop_conditions: tuple[str, ...]
    rollback_ref: str
    max_affected_resources: int
    state: RecoveryState = RecoveryState.DRAFT
    recovery_epoch: int = 0

    def __post_init__(self) -> None:
        _require_text(
            "plan_id",
            self.plan_id,
            max_chars=_MAX_PLAN_ID_CHARS,
            separator_safe=True,
        )
        _require_text("primary_region", self.primary_region, max_chars=64)
        _require_text("recovery_region", self.recovery_region, max_chars=64)
        _require_text(
            "requester_ref",
            self.requester_ref,
            max_chars=_MAX_REF_CHARS,
            separator_safe=True,
        )
        _require_text("rollback_ref", self.rollback_ref, max_chars=_MAX_REF_CHARS)
        if self.primary_region == self.recovery_region:
            raise RecoveryPlanError("primary_region and recovery_region MUST differ")
        if self.revision < 1:
            raise RecoveryPlanError("revision MUST be >= 1")
        if self.max_affected_resources < 1:
            raise RecoveryPlanError("max_affected_resources MUST be >= 1")
        _require_unique_refs("scope", self.scope)
        _require_unique_refs("stop_conditions", self.stop_conditions)
        if len(self.scope) > self.max_affected_resources:
            raise RecoveryPlanError("scope exceeds max_affected_resources")
        _require_epoch(self.recovery_epoch)
        if self.state in _EPOCH_STATES and self.recovery_epoch < 1:
            raise RecoveryPlanError("active recovery states require recovery_epoch >= 1")
        if self.state not in _EPOCH_STATES and self.recovery_epoch != 0:
            raise RecoveryPlanError("pre-activation states require recovery_epoch == 0")


@dataclass(frozen=True, slots=True)
class RecoveryTransition:
    """Append-only evidence for one accepted recovery-plan transition."""

    plan_id: str
    revision: int
    from_state: RecoveryState
    to_state: RecoveryState
    actor_ref: str
    at: datetime
    evidence_refs: tuple[str, ...]
    recovery_epoch: int
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(
            "plan_id",
            self.plan_id,
            max_chars=_MAX_PLAN_ID_CHARS,
            separator_safe=True,
        )
        _require_text(
            "actor_ref",
            self.actor_ref,
            max_chars=_MAX_REF_CHARS,
            separator_safe=True,
        )
        if self.revision < 1:
            raise RecoveryPlanError("revision MUST be >= 1")
        if self.to_state not in LEGAL_RECOVERY_TRANSITIONS[self.from_state]:
            raise RecoveryPlanError("transition record contains an illegal recovery edge")
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise RecoveryPlanError("transition timestamp MUST be timezone-aware")
        _require_unique_refs(
            "evidence_refs",
            self.evidence_refs,
            max_items=_MAX_EVIDENCE_REFS,
        )
        _require_epoch(self.recovery_epoch)
        if self.to_state in _EPOCH_STATES and self.recovery_epoch < 1:
            raise RecoveryPlanError("active recovery transition requires recovery_epoch >= 1")
        if self.to_state in _APPROVAL_STATES:
            if self.approval_ref is None:
                raise RecoveryPlanError("approval transition requires approval_ref")
            _require_text("approval_ref", self.approval_ref, max_chars=_MAX_REF_CHARS)
        elif self.approval_ref is not None:
            raise RecoveryPlanError("approval_ref is valid only on approval transitions")

    @property
    def idempotency_key(self) -> str:
        """Return the stable identity for redelivery of this transition intent."""
        intent = json.dumps(
            {
                "approval_ref": self.approval_ref,
                "evidence_refs": list(self.evidence_refs),
                "recovery_epoch": self.recovery_epoch,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        digest = hashlib.sha256(intent.encode()).hexdigest()
        return (
            f"{self.plan_id}::{self.revision}::"
            f"{self.from_state.value}->{self.to_state.value}::"
            f"{self.actor_ref}::{self.at.astimezone(UTC).isoformat()}::{digest}"
        )


class RecoveryPlanStateMachine:
    """Validate one legal edge and return a new plan plus audit record."""

    def transition(
        self,
        plan: RecoveryPlan,
        *,
        target: RecoveryState,
        actor_ref: str,
        at: datetime,
        evidence_refs: Sequence[str],
        approval_ref: str | None = None,
        recovery_epoch: int | None = None,
    ) -> tuple[RecoveryPlan, RecoveryTransition]:
        allowed = LEGAL_RECOVERY_TRANSITIONS[plan.state]
        if target not in allowed:
            raise RecoveryPlanError(
                f"illegal recovery transition {plan.state.value!r} -> {target.value!r}: "
                f"allowed={sorted(state.value for state in allowed) or ['<terminal>']}"
            )
        _require_text(
            "actor_ref",
            actor_ref,
            max_chars=_MAX_REF_CHARS,
            separator_safe=True,
        )
        if at.tzinfo is None or at.utcoffset() is None:
            raise RecoveryPlanError("transition timestamp MUST be timezone-aware")
        evidence = tuple(evidence_refs)
        _require_unique_refs("evidence_refs", evidence, max_items=_MAX_EVIDENCE_REFS)

        next_epoch = self._resolve_epoch(
            plan=plan,
            target=target,
            recovery_epoch=recovery_epoch,
        )
        self._validate_approval(
            plan=plan,
            target=target,
            actor_ref=actor_ref,
            approval_ref=approval_ref,
        )
        updated = replace(plan, state=target, recovery_epoch=next_epoch)
        transition = RecoveryTransition(
            plan_id=plan.plan_id,
            revision=plan.revision,
            from_state=plan.state,
            to_state=target,
            actor_ref=actor_ref,
            at=at,
            evidence_refs=evidence,
            recovery_epoch=next_epoch,
            approval_ref=approval_ref,
        )
        return updated, transition

    @staticmethod
    def _resolve_epoch(
        *,
        plan: RecoveryPlan,
        target: RecoveryState,
        recovery_epoch: int | None,
    ) -> int:
        if target in {RecoveryState.ACTIVATING, RecoveryState.FAILING_BACK}:
            if recovery_epoch is None or recovery_epoch <= plan.recovery_epoch:
                raise RecoveryPlanError(f"{target.value} requires a monotonically increasing epoch")
            _require_epoch(recovery_epoch)
            return recovery_epoch
        if plan.state in _EPOCH_STATES or target in _EPOCH_STATES:
            if recovery_epoch != plan.recovery_epoch:
                raise RecoveryPlanError("transition recovery_epoch MUST match the active epoch")
            return plan.recovery_epoch
        if recovery_epoch not in (None, 0):
            raise RecoveryPlanError("pre-activation transition MUST NOT bind a recovery epoch")
        return 0

    @staticmethod
    def _validate_approval(
        *,
        plan: RecoveryPlan,
        target: RecoveryState,
        actor_ref: str,
        approval_ref: str | None,
    ) -> None:
        if target in _APPROVAL_STATES:
            if _normalized_principal(actor_ref) == _normalized_principal(plan.requester_ref):
                raise RecoveryPlanError("requester MUST NOT approve the same recovery plan")
            if approval_ref is None:
                raise RecoveryPlanError(f"{target.value} transition requires approval_ref")
            _require_text("approval_ref", approval_ref, max_chars=_MAX_REF_CHARS)
        elif approval_ref is not None:
            raise RecoveryPlanError("approval_ref is valid only on approval transitions")


def _require_text(
    name: str,
    value: str,
    *,
    max_chars: int,
    separator_safe: bool = False,
) -> None:
    if not value or value != value.strip():
        raise RecoveryPlanError(f"{name} MUST be non-empty and trimmed")
    if len(value) > max_chars:
        raise RecoveryPlanError(f"{name} exceeds {max_chars} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise RecoveryPlanError(f"{name} contains a control character")
    if separator_safe and "::" in value:
        raise RecoveryPlanError(f"{name} contains the reserved '::' separator")


def _require_unique_refs(
    name: str,
    values: Sequence[str],
    *,
    max_items: int | None = None,
) -> None:
    if not values:
        raise RecoveryPlanError(f"{name} MUST be non-empty")
    if max_items is not None and len(values) > max_items:
        raise RecoveryPlanError(f"{name} exceeds {max_items} entries")
    if len(set(values)) != len(values):
        raise RecoveryPlanError(f"{name} MUST NOT contain duplicates")
    for value in values:
        _require_text(name, value, max_chars=_MAX_REF_CHARS)


def _require_finite_non_negative(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise RecoveryPlanError(f"{name} MUST be finite and >= 0")


def _require_finite_positive(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise RecoveryPlanError(f"{name} MUST be finite and > 0")


def _require_epoch(value: int) -> None:
    if isinstance(value, bool) or value < 0 or value > _MAX_RECOVERY_EPOCH:
        raise RecoveryPlanError(
            f"recovery_epoch MUST be an integer from 0 to {_MAX_RECOVERY_EPOCH}"
        )


def _normalized_principal(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "LEGAL_RECOVERY_TRANSITIONS",
    "RecoveryMode",
    "RecoveryObjectives",
    "RecoveryPlan",
    "RecoveryPlanError",
    "RecoveryPlanStateMachine",
    "RecoveryProfile",
    "RecoveryState",
    "RecoveryTransition",
]
