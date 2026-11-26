"""Effect-spanning standing-authorization lease.

This module is **inert**: it defines the data types, idempotency key derivation,
bounded validity, fencing generation binding, provider-commit fence protocol, and
terminal release record for an A3-E effect-spanning lease.

Nothing in the shipped runtime wires this module. It remains unused by risk gate,
HIL resume, workflow, control loop, agents, and executor paths until later promotion
work provides governed shadow evidence and independent promotion review.

FDAI-CONST-008 conditions must already be satisfied (via the evaluator and the
lifecycle fence) before a lease may be acquired. The lease then holds a second,
time-bounded check across the effect: every provider effect-commit boundary must
validate the current lease and fencing generation atomically, or the ActionType
is ineligible for A3-E.

## Fail-closed invariants

- Revocation, expiry, stale generation, lease loss, or persistence failure prevents
  the later provider commit and produces a typed outcome.
- A crash between provider commit and terminal lease persistence is reconciled via
  authoritative provider operation status; the same idempotency key never produces
  a duplicate effect.
- Revocation after a committed effect preserves the committed fact and cannot be
  reported as no-effect (``REVOKED_AFTER_COMMIT``).
- An ineligible capability (provider cannot enforce the atomic fence) fails closed
  with ``INELIGIBLE_CAPABILITY``.
- Silence never grants authority. Every unresolved state fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)

#: Maximum bounded lease validity. Enforcement tightens this by envelope duration;
#: no lease may outlast the authorization's valid_until. This is a hard upper bound,
#: not a governed threshold (FDAI-CONST-004).
LEASE_MAX_VALID_SECONDS: int = 3600

#: Minimum valid window. A lease window shorter than this cannot be acquired.
LEASE_MIN_VALID_SECONDS: int = 10


class LeaseOutcome(StrEnum):
    """Typed fail-closed outcome for every lease state transition.

    Every value other than ``ACQUIRED`` is a fail-closed result that prevents or
    confirms the absence of an unauthorized provider commit.
    """

    ACQUIRED = "acquired"
    """The lease was successfully acquired and is valid."""

    REVOKED_BEFORE_COMMIT = "revoked_before_commit"
    """Revocation was detected before the provider committed; no effect occurred."""

    REVOKED_AFTER_COMMIT = "revoked_after_commit"
    """Revocation detected after the provider committed. The committed effect is
    preserved and cannot be treated as absent."""

    EXPIRED = "expired"
    """The lease ``valid_until`` was reached before the effect completed."""

    STALE_GENERATION = "stale_generation"
    """The lifecycle fencing generation advanced (revoke or renew) since
    acquisition; the lease is no longer current."""

    LEASE_LOSS = "lease_loss"
    """Another holder acquired the same idempotency slot, indicating a concurrent
    restart or duplicate executor. Effect is not committed by this holder."""

    PERSISTENCE_FAILURE = "persistence_failure"
    """The lease store could not complete a required operation. Treated
    conservatively as stale."""

    INELIGIBLE_CAPABILITY = "ineligible_capability"
    """The provider cannot enforce an atomic current-lease/fence check at its
    effect-commit boundary; the ActionType is ineligible for A3-E."""


class EffectStatus(StrEnum):
    """Authoritative provider operation status used for crash reconciliation."""

    NOT_COMMITTED = "not_committed"
    """No effect was committed by the provider for this idempotency key."""

    COMMITTED = "committed"
    """The provider committed an effect for this idempotency key."""

    UNKNOWN = "unknown"
    """The provider cannot determine whether the effect was committed. Treated
    as committed to prevent optimistic assumptions."""


def provider_idempotency_key(
    *,
    revision_id: str,
    action_digest: str,
    target_digest: str,
) -> str:
    """Derive the stable provider idempotency key.

    The key is content-addressed over the authorization revision, action, and
    target. It is stable across crash and restart so that reconciliation after a
    crash between provider commit and terminal lease persistence can detect an
    already-committed effect without issuing a duplicate.

    Args:
        revision_id: The exact immutable authorization revision digest.
        action_digest: Content digest of the canonical action description.
        target_digest: Content digest of the canonical target scope.

    Returns:
        A ``sha256:`` digest that uniquely identifies this effect slot.
    """
    require_digest("revision_id", revision_id)
    require_digest("action_digest", action_digest)
    require_digest("target_digest", target_digest)
    return content_digest(
        {
            "revision_id": revision_id,
            "action_digest": action_digest,
            "target_digest": target_digest,
        }
    )


@dataclass(frozen=True, slots=True)
class StandingAuthorizationLease:
    """Acquired effect-spanning lease.

    Binds one immutable authorization revision, exact action and target scope,
    executor identity, source revision, and lifecycle fencing generation. The
    lease grants no execution authority by itself; it is a time-bounded evidence
    record that the human delegation remained current at acquisition time.

    ``execution_authority`` is always ``False``. Autonomy requires governed
    shadow evidence and independent promotion review that do not exist.
    """

    #: Stable idempotency key, equal to ``provider_idempotency_key(...)``.
    lease_id: str
    #: Family identifier from the authorization lifecycle.
    family_id: str
    #: Exact immutable authorization revision bound at acquisition.
    revision_id: str
    #: Lifecycle fencing generation at acquisition. Must match primary store.
    fencing_generation: int
    #: Exact head-transition digest at acquisition.
    transition_digest: str
    #: Content digest of the canonical action description.
    action_digest: str
    #: Content digest of the canonical target scope.
    target_digest: str
    #: Principal identity of the executor holding this lease.
    executor_identity: str
    #: Software or catalog revision under which the effect runs.
    source_revision_id: str
    #: UTC timestamp when the lease was acquired.
    acquired_at: datetime
    #: UTC timestamp after which the lease is invalid.
    valid_until: datetime
    #: Monotonic generation counter for this idempotency slot, assigned by the store.
    lease_generation: int
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        require_digest("lease_id", self.lease_id)
        require_text("family_id", self.family_id)
        require_digest("revision_id", self.revision_id)
        require_digest("transition_digest", self.transition_digest)
        require_digest("action_digest", self.action_digest)
        require_digest("target_digest", self.target_digest)
        require_text("executor_identity", self.executor_identity)
        require_text("source_revision_id", self.source_revision_id)
        require_aware("acquired_at", self.acquired_at)
        require_aware("valid_until", self.valid_until)
        if self.fencing_generation < 1:
            raise AuthorizationLifecycleError("lease fencing_generation MUST be positive")
        if self.lease_generation < 1:
            raise AuthorizationLifecycleError("lease_generation MUST be positive")
        if self.valid_until <= self.acquired_at:
            raise AuthorizationLifecycleError("lease valid_until MUST be after acquired_at")
        expected_key = provider_idempotency_key(
            revision_id=self.revision_id,
            action_digest=self.action_digest,
            target_digest=self.target_digest,
        )
        if self.lease_id != expected_key:
            raise AuthorizationLifecycleError("lease_id MUST equal the derived idempotency key")
        if self.execution_authority is not False:
            raise AuthorizationLifecycleError("lease execution_authority MUST be False")
        if self.promotion_authority is not False:
            raise AuthorizationLifecycleError("lease promotion_authority MUST be False")

    def is_expired(self, now: datetime) -> bool:
        """Return ``True`` if ``now`` is at or after ``valid_until``."""
        return aware_utc(now) >= aware_utc(self.valid_until)

    def fence(self) -> LifecycleFence:
        """Return the exact lifecycle fence bound at acquisition."""
        return LifecycleFence(
            family_id=self.family_id,
            revision_id=self.revision_id,
            fencing_generation=self.fencing_generation,
            transition_digest=self.transition_digest,
        )

    def idempotency_body(self) -> dict[str, object]:
        """Return the canonical body for audit or persistence."""
        return {
            "lease_id": self.lease_id,
            "family_id": self.family_id,
            "revision_id": self.revision_id,
            "fencing_generation": self.fencing_generation,
            "transition_digest": self.transition_digest,
            "action_digest": self.action_digest,
            "target_digest": self.target_digest,
            "executor_identity": self.executor_identity,
            "source_revision_id": self.source_revision_id,
            "acquired_at": instant(self.acquired_at),
            "valid_until": instant(self.valid_until),
            "lease_generation": self.lease_generation,
            "execution_authority": False,
            "promotion_authority": False,
        }


@dataclass(frozen=True, slots=True)
class LeaseAcquisitionRequest:
    """All inputs required to attempt a lease acquisition."""

    fence: LifecycleFence
    action_digest: str
    target_digest: str
    executor_identity: str
    source_revision_id: str
    requested_at: datetime
    valid_seconds: int

    def __post_init__(self) -> None:
        require_digest("action_digest", self.action_digest)
        require_digest("target_digest", self.target_digest)
        require_text("executor_identity", self.executor_identity)
        require_text("source_revision_id", self.source_revision_id)
        require_aware("requested_at", self.requested_at)
        if not LEASE_MIN_VALID_SECONDS <= self.valid_seconds <= LEASE_MAX_VALID_SECONDS:
            raise AuthorizationLifecycleError(
                f"lease valid_seconds MUST be in "
                f"[{LEASE_MIN_VALID_SECONDS}, {LEASE_MAX_VALID_SECONDS}]"
            )

    @property
    def idempotency_key(self) -> str:
        """Return the stable idempotency key for this request."""
        return provider_idempotency_key(
            revision_id=self.fence.revision_id,
            action_digest=self.action_digest,
            target_digest=self.target_digest,
        )


@dataclass(frozen=True, slots=True)
class LeaseAcquisitionResult:
    """Result of a lease acquisition attempt.

    ``lease`` is populated only when ``outcome`` is ``LeaseOutcome.ACQUIRED``.
    """

    outcome: LeaseOutcome
    lease: StandingAuthorizationLease | None = None

    def __post_init__(self) -> None:
        if (self.outcome is LeaseOutcome.ACQUIRED) != (self.lease is not None):
            raise AuthorizationLifecycleError(
                "lease acquisition result MUST have a lease iff outcome is ACQUIRED"
            )


@dataclass(frozen=True, slots=True)
class LeaseCheckpoint:
    """Heartbeat record written during effect execution.

    Written periodically to signal liveness. A checkpoint that cannot be written
    is treated as a ``PERSISTENCE_FAILURE`` and blocks the provider commit.
    """

    lease_id: str
    lease_generation: int
    checked_at: datetime

    def __post_init__(self) -> None:
        require_digest("lease_id", self.lease_id)
        if self.lease_generation < 1:
            raise AuthorizationLifecycleError("checkpoint lease_generation MUST be positive")
        require_aware("checked_at", self.checked_at)


@dataclass(frozen=True, slots=True)
class ProviderCommitFenceRequest:
    """Atomic fence check submitted by a provider adapter at effect-commit time.

    The provider MUST submit this request atomically - as part of the same
    transaction or two-phase commit that records the provider operation. An
    ActionType whose provider cannot enforce this boundary is ineligible for A3-E.
    """

    lease_id: str
    lease_generation: int
    fence: LifecycleFence

    def __post_init__(self) -> None:
        require_digest("lease_id", self.lease_id)
        if self.lease_generation < 1:
            raise AuthorizationLifecycleError("fence request lease_generation MUST be positive")


@dataclass(frozen=True, slots=True)
class ProviderCommitFenceResult:
    """Result of the atomic provider-commit fence check.

    ``allowed`` is ``True`` only when the lease is still current and the fence
    generation is still the primary-store generation. Any other state → fail closed.
    The result carries no execution authority.
    """

    allowed: bool
    outcome: LeaseOutcome
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.allowed and self.outcome is not LeaseOutcome.ACQUIRED:
            raise AuthorizationLifecycleError("fence result MUST use ACQUIRED outcome when allowed")
        if not self.allowed and self.outcome is LeaseOutcome.ACQUIRED:
            raise AuthorizationLifecycleError(
                "fence result MUST NOT use ACQUIRED outcome when denied"
            )
        if self.execution_authority is not False:
            raise AuthorizationLifecycleError("fence result execution_authority MUST be False")


@dataclass(frozen=True, slots=True)
class TerminalLeaseRecord:
    """Final release record written after the effect concludes.

    Captures the terminal effect status and the exact lease identity. When a crash
    occurs between provider commit and this record, the ``effect_status`` is
    determined by reconciling the authoritative provider operation status via
    ``EffectStatus``.

    A lease must be terminally released - whether the effect succeeded, failed, or
    was rolled back - so that a subsequent lease attempt on the same idempotency
    slot can detect the prior outcome and prevent duplicate effects.
    """

    lease_id: str
    lease_generation: int
    revision_id: str
    fencing_generation: int
    effect_status: EffectStatus
    released_at: datetime

    def __post_init__(self) -> None:
        require_digest("lease_id", self.lease_id)
        require_digest("revision_id", self.revision_id)
        if self.lease_generation < 1:
            raise AuthorizationLifecycleError("terminal record lease_generation MUST be positive")
        if self.fencing_generation < 1:
            raise AuthorizationLifecycleError("terminal record fencing_generation MUST be positive")
        require_aware("released_at", self.released_at)

    def audit_body(self) -> dict[str, object]:
        """Return canonical audit record body for this terminal release."""
        return {
            "kind": "standing_authority.lease.terminal_release",
            "lease_id": self.lease_id,
            "lease_generation": self.lease_generation,
            "revision_id": self.revision_id,
            "fencing_generation": self.fencing_generation,
            "effect_status": self.effect_status.value,
            "released_at": instant(self.released_at),
            "execution_authority": False,
            "promotion_authority": False,
        }


def build_acquisition_request(
    *,
    fence: LifecycleFence,
    action_digest: str,
    target_digest: str,
    executor_identity: str,
    source_revision_id: str,
    requested_at: datetime,
    valid_seconds: int,
) -> LeaseAcquisitionRequest:
    """Construct and validate a lease acquisition request.

    This is a pure factory; it does not contact the store. Use the returned
    request with a ``StandingAuthorizationLeaseStore`` implementation.
    """
    return LeaseAcquisitionRequest(
        fence=fence,
        action_digest=action_digest,
        target_digest=target_digest,
        executor_identity=executor_identity,
        source_revision_id=source_revision_id,
        requested_at=aware_utc(requested_at),
        valid_seconds=valid_seconds,
    )


def build_provider_commit_fence_request(
    lease: StandingAuthorizationLease,
) -> ProviderCommitFenceRequest:
    """Build the provider-commit fence request from an acquired lease.

    The provider submits this as part of its atomic effect-commit transaction.
    """
    return ProviderCommitFenceRequest(
        lease_id=lease.lease_id,
        lease_generation=lease.lease_generation,
        fence=lease.fence(),
    )


def build_terminal_record(
    lease: StandingAuthorizationLease,
    *,
    effect_status: EffectStatus,
    released_at: datetime,
) -> TerminalLeaseRecord:
    """Build a terminal release record from an acquired lease and the final effect status.

    When a crash occurred between provider commit and this call, ``effect_status``
    MUST be set to the value returned by the store's ``reconcile_provider_status``
    method, not optimistically inferred.
    """
    return TerminalLeaseRecord(
        lease_id=lease.lease_id,
        lease_generation=lease.lease_generation,
        revision_id=lease.revision_id,
        fencing_generation=lease.fencing_generation,
        effect_status=effect_status,
        released_at=aware_utc(released_at),
    )


def build_checkpoint(
    lease: StandingAuthorizationLease,
    *,
    checked_at: datetime,
) -> LeaseCheckpoint:
    """Build a lease heartbeat checkpoint from an acquired lease."""
    return LeaseCheckpoint(
        lease_id=lease.lease_id,
        lease_generation=lease.lease_generation,
        checked_at=aware_utc(checked_at),
    )


__all__ = [
    "LEASE_MAX_VALID_SECONDS",
    "LEASE_MIN_VALID_SECONDS",
    "EffectStatus",
    "LeaseAcquisitionRequest",
    "LeaseAcquisitionResult",
    "LeaseCheckpoint",
    "LeaseOutcome",
    "ProviderCommitFenceRequest",
    "ProviderCommitFenceResult",
    "StandingAuthorizationLease",
    "TerminalLeaseRecord",
    "build_acquisition_request",
    "build_checkpoint",
    "build_provider_commit_fence_request",
    "build_terminal_record",
    "provider_idempotency_key",
]
