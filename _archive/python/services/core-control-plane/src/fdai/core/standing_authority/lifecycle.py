"""Immutable A3-E lifecycle records, replay, and fencing.

This module defines the shadow-only state machine. It does not evaluate standing
authorization eligibility and is not imported by any dispatch path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self

from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
)
from fdai.core.standing_authority.lifecycle_codec import (
    aware_utc as _aware_utc,
)
from fdai.core.standing_authority.lifecycle_codec import (
    content_digest as _content_digest,
)
from fdai.core.standing_authority.lifecycle_codec import (
    instant as _instant,
)
from fdai.core.standing_authority.lifecycle_codec import (
    require_aware as _require_aware,
)
from fdai.core.standing_authority.lifecycle_codec import (
    require_digest as _require_digest,
)
from fdai.core.standing_authority.lifecycle_codec import (
    require_text as _require_text,
)
from fdai.core.standing_authority.lifecycle_revision import (
    AuthorizationProofBindings,
    AuthorizationRevision,
    authorization_revision_id,
)
from fdai.shared.providers.standing_authority import StandingAuthorizationLifecycleStore


class AuthorizationCommandKind(StrEnum):
    """Mutations accepted by the single Core lifecycle writer."""

    ADMIT = "admit"
    RENEW = "renew"
    REVOKE = "revoke"


class AuthorizationSnapshotStatus(StrEnum):
    """Current lifecycle projection state."""

    ACTIVE = "active"
    REVOKED = "revoked"


class AuthorizationWriteStatus(StrEnum):
    """Whether a lifecycle command changed durable state."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class AuthenticatedAuthorizationCommand:
    """Authenticated human command context carried from typed ingress."""

    command_id: str
    actor_ref: str
    actor_kind: Literal["human"]
    actor_roles: frozenset[str]
    authentication_evidence_digest: str
    authenticated_at: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        for name in ("command_id", "actor_ref", "correlation_id"):
            _require_text(name, getattr(self, name))
        if self.actor_kind != "human":
            raise AuthorizationLifecycleError("standing authority mutation requires a human actor")
        if (
            not self.actor_roles
            or any(not role.strip() for role in self.actor_roles)
            or not self.actor_roles.intersection({"owner", "service_owner"})
        ):
            raise AuthorizationLifecycleError("authenticated command roles MUST be non-empty")
        if self.actor_ref.startswith("agent:") or self.actor_ref.startswith("identity:thor"):
            raise AuthorizationLifecycleError("standing authority mutation requires a human actor")
        _require_digest(
            "authentication_evidence_digest",
            self.authentication_evidence_digest,
        )
        _require_aware("authenticated_at", self.authenticated_at)


@dataclass(frozen=True, slots=True)
class AuthorizationLifecycleCommand:
    """One admit, renew, or revoke intent delivered at least once."""

    kind: AuthorizationCommandKind
    family_id: str
    context: AuthenticatedAuthorizationCommand
    occurred_at: datetime
    expected_revision_id: str | None
    expected_fencing_generation: int
    revision: AuthorizationRevision | None = None
    whole_family: bool = False

    def __post_init__(self) -> None:
        _require_text("family_id", self.family_id)
        _require_aware("occurred_at", self.occurred_at)
        if self.expected_fencing_generation < 0:
            raise AuthorizationLifecycleError("expected fencing generation MUST be non-negative")
        if self.expected_revision_id is not None:
            _require_digest("expected_revision_id", self.expected_revision_id)
        if self.kind is AuthorizationCommandKind.ADMIT:
            if (
                self.revision is None
                or self.revision.family_id != self.family_id
                or self.revision.predecessor_revision_id is not None
                or self.expected_revision_id is not None
                or self.expected_fencing_generation != 0
                or self.whole_family
            ):
                raise AuthorizationLifecycleError("admit command shape is invalid")
        elif self.kind is AuthorizationCommandKind.RENEW:
            if (
                self.revision is None
                or self.revision.family_id != self.family_id
                or self.revision.predecessor_revision_id != self.expected_revision_id
                or self.expected_revision_id is None
                or self.expected_fencing_generation < 1
                or self.whole_family
            ):
                raise AuthorizationLifecycleError("renew command shape is invalid")
        elif (
            self.revision is not None
            or self.expected_fencing_generation < 1
            or self.whole_family == (self.expected_revision_id is not None)
        ):
            raise AuthorizationLifecycleError(
                "revoke MUST target either the expected revision or the whole family"
            )

    @property
    def command_digest(self) -> str:
        """Return the stable identity used to detect conflicting redelivery."""

        return _content_digest(
            {
                "kind": self.kind.value,
                "family_id": self.family_id,
                "command_id": self.context.command_id,
                "actor_ref": self.context.actor_ref,
                "actor_roles": sorted(self.context.actor_roles),
                "authentication_evidence_digest": self.context.authentication_evidence_digest,
                "authenticated_at": _instant(self.context.authenticated_at),
                "correlation_id": self.context.correlation_id,
                "occurred_at": _instant(self.occurred_at),
                "expected_revision_id": self.expected_revision_id,
                "expected_fencing_generation": self.expected_fencing_generation,
                "revision_id": self.revision.revision_id if self.revision else None,
                "approvals_digest": (
                    self.revision.proof_bindings.approvals_digest
                    if self.revision is not None
                    else None
                ),
                "approval_claim_digest": (
                    self.revision.proof_bindings.approval_claim_digest
                    if self.revision is not None
                    else None
                ),
                "evidence_verification_bundle_digest": (
                    self.revision.proof_bindings.evidence_verification_bundle_digest
                    if self.revision is not None
                    else None
                ),
                "evidence_claim_digest": (
                    self.revision.proof_bindings.evidence_claim_digest
                    if self.revision is not None
                    else None
                ),
                "whole_family": self.whole_family,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorizationTransition:
    """One hash-chained append-only lifecycle transition."""

    family_id: str
    sequence: int
    kind: AuthorizationCommandKind
    command_id: str
    command_digest: str
    actor_ref: str
    actor_roles: tuple[str, ...]
    authentication_evidence_digest: str
    authenticated_at: datetime
    correlation_id: str
    revision_id: str
    predecessor_revision_id: str | None
    fencing_generation: int
    occurred_at: datetime
    previous_transition_digest: str | None
    transition_digest: str

    def __post_init__(self) -> None:
        for name in ("family_id", "command_id", "actor_ref", "correlation_id"):
            _require_text(name, getattr(self, name))
        for name in (
            "command_digest",
            "authentication_evidence_digest",
            "revision_id",
            "transition_digest",
        ):
            _require_digest(name, getattr(self, name))
        if not self.actor_roles or self.actor_roles != tuple(sorted(set(self.actor_roles))):
            raise AuthorizationLifecycleError("transition actor roles MUST be canonical")
        if self.predecessor_revision_id is not None:
            _require_digest("predecessor_revision_id", self.predecessor_revision_id)
        if self.previous_transition_digest is not None:
            _require_digest("previous_transition_digest", self.previous_transition_digest)
        if self.sequence < 1 or self.fencing_generation < 1:
            raise AuthorizationLifecycleError("transition sequence and generation MUST be positive")
        _require_aware("authenticated_at", self.authenticated_at)
        _require_aware("occurred_at", self.occurred_at)
        if self.occurred_at < self.authenticated_at:
            raise AuthorizationLifecycleError("transition cannot precede command authentication")
        if self.transition_digest != _content_digest(self.body()):
            raise AuthorizationLifecycleError("transition digest mismatch")

    def body(self) -> dict[str, object]:
        """Return the canonical transition body without its digest."""

        return {
            "family_id": self.family_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "command_id": self.command_id,
            "command_digest": self.command_digest,
            "actor_ref": self.actor_ref,
            "actor_roles": list(self.actor_roles),
            "authentication_evidence_digest": self.authentication_evidence_digest,
            "authenticated_at": _instant(self.authenticated_at),
            "correlation_id": self.correlation_id,
            "revision_id": self.revision_id,
            "predecessor_revision_id": self.predecessor_revision_id,
            "fencing_generation": self.fencing_generation,
            "occurred_at": _instant(self.occurred_at),
            "previous_transition_digest": self.previous_transition_digest,
        }

    @classmethod
    def create(
        cls,
        *,
        snapshot: AuthorizationSnapshot | None,
        command: AuthorizationLifecycleCommand,
    ) -> Self:
        sequence = 1 if snapshot is None else snapshot.last_sequence + 1
        generation = 1 if snapshot is None else snapshot.fencing_generation + 1
        revision_id = (
            command.revision.revision_id
            if command.revision is not None
            else snapshot.current_revision_id
            if snapshot is not None
            else ""
        )
        predecessor = command.revision.predecessor_revision_id if command.revision else revision_id
        body: dict[str, object] = {
            "family_id": command.family_id,
            "sequence": sequence,
            "kind": command.kind.value,
            "command_id": command.context.command_id,
            "command_digest": command.command_digest,
            "actor_ref": command.context.actor_ref,
            "actor_roles": sorted(command.context.actor_roles),
            "authentication_evidence_digest": command.context.authentication_evidence_digest,
            "authenticated_at": _instant(command.context.authenticated_at),
            "correlation_id": command.context.correlation_id,
            "revision_id": revision_id,
            "predecessor_revision_id": predecessor,
            "fencing_generation": generation,
            "occurred_at": _instant(command.occurred_at),
            "previous_transition_digest": (
                snapshot.head_transition_digest if snapshot is not None else None
            ),
        }
        return cls(
            family_id=command.family_id,
            sequence=sequence,
            kind=command.kind,
            command_id=command.context.command_id,
            command_digest=command.command_digest,
            actor_ref=command.context.actor_ref,
            actor_roles=tuple(sorted(command.context.actor_roles)),
            authentication_evidence_digest=command.context.authentication_evidence_digest,
            authenticated_at=_aware_utc(command.context.authenticated_at),
            correlation_id=command.context.correlation_id,
            revision_id=revision_id,
            predecessor_revision_id=predecessor,
            fencing_generation=generation,
            occurred_at=_aware_utc(command.occurred_at),
            previous_transition_digest=(
                snapshot.head_transition_digest if snapshot is not None else None
            ),
            transition_digest=_content_digest(body),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationSnapshot:
    """Rebuildable current-state projection for one family."""

    family_id: str
    current_revision_id: str
    status: AuthorizationSnapshotStatus
    fencing_generation: int
    last_sequence: int
    head_transition_digest: str
    snapshot_digest: str

    def __post_init__(self) -> None:
        _require_text("family_id", self.family_id)
        for name in ("current_revision_id", "head_transition_digest", "snapshot_digest"):
            _require_digest(name, getattr(self, name))
        if self.fencing_generation < 1 or self.last_sequence < 1:
            raise AuthorizationLifecycleError("snapshot counters MUST be positive")
        if self.snapshot_digest != _content_digest(self.body()):
            raise AuthorizationLifecycleError("authorization snapshot digest mismatch")

    def body(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "current_revision_id": self.current_revision_id,
            "status": self.status.value,
            "fencing_generation": self.fencing_generation,
            "last_sequence": self.last_sequence,
            "head_transition_digest": self.head_transition_digest,
        }

    @classmethod
    def from_transition(cls, transition: AuthorizationTransition) -> Self:
        status = (
            AuthorizationSnapshotStatus.REVOKED
            if transition.kind is AuthorizationCommandKind.REVOKE
            else AuthorizationSnapshotStatus.ACTIVE
        )
        body: dict[str, object] = {
            "family_id": transition.family_id,
            "current_revision_id": transition.revision_id,
            "status": status.value,
            "fencing_generation": transition.fencing_generation,
            "last_sequence": transition.sequence,
            "head_transition_digest": transition.transition_digest,
        }
        return cls(
            family_id=transition.family_id,
            current_revision_id=transition.revision_id,
            status=status,
            fencing_generation=transition.fencing_generation,
            last_sequence=transition.sequence,
            head_transition_digest=transition.transition_digest,
            snapshot_digest=_content_digest(body),
        )

    def fence(self) -> LifecycleFence:
        return LifecycleFence(
            family_id=self.family_id,
            revision_id=self.current_revision_id,
            fencing_generation=self.fencing_generation,
            transition_digest=self.head_transition_digest,
        )


@dataclass(frozen=True, slots=True)
class LifecycleFence:
    """Exact primary-store state that must remain current before dispatch."""

    family_id: str
    revision_id: str
    fencing_generation: int
    transition_digest: str

    def __post_init__(self) -> None:
        _require_text("family_id", self.family_id)
        _require_digest("revision_id", self.revision_id)
        _require_digest("transition_digest", self.transition_digest)
        if self.fencing_generation < 1:
            raise AuthorizationLifecycleError("fencing generation MUST be positive")


@dataclass(frozen=True, slots=True)
class AuthorizationLifecycleWriteResult:
    status: AuthorizationWriteStatus
    transition: AuthorizationTransition
    snapshot: AuthorizationSnapshot


class StandingAuthorizationLifecycleWriter:
    """The only Core service allowed to request lifecycle mutations."""

    def __init__(self, store: StandingAuthorizationLifecycleStore) -> None:
        self._store = store

    async def apply(
        self,
        command: AuthorizationLifecycleCommand,
    ) -> AuthorizationLifecycleWriteResult:
        """Delegate one authenticated command to the atomic persistence boundary."""

        return await self._store.apply(command)


def plan_lifecycle_transition(
    *,
    snapshot: AuthorizationSnapshot | None,
    transitions: tuple[AuthorizationTransition, ...],
    revisions: dict[str, AuthorizationRevision],
    command: AuthorizationLifecycleCommand,
) -> AuthorizationLifecycleWriteResult:
    """Validate current state and return one deterministic state transition."""

    replayed = replay_lifecycle(transitions=transitions, revisions=revisions)
    if replayed != snapshot:
        raise AuthorizationLifecycleError("lifecycle projection does not match transition history")
    duplicate = next(
        (
            transition
            for transition in transitions
            if transition.command_id == command.context.command_id
        ),
        None,
    )
    if duplicate is not None:
        if duplicate.command_digest != command.command_digest:
            raise AuthorizationLifecycleError("idempotency key payload conflict")
        if snapshot is None:
            raise AuthorizationLifecycleError("duplicate command has no current projection")
        return AuthorizationLifecycleWriteResult(
            status=AuthorizationWriteStatus.DUPLICATE,
            transition=duplicate,
            snapshot=snapshot,
        )
    if command.kind is AuthorizationCommandKind.ADMIT:
        if snapshot is not None or transitions:
            raise AuthorizationLifecycleError("authorization family already exists")
    else:
        if snapshot is None or snapshot.status is not AuthorizationSnapshotStatus.ACTIVE:
            raise AuthorizationLifecycleError("authorization family is not active")
        if snapshot.fencing_generation != command.expected_fencing_generation:
            raise AuthorizationLifecycleError("stale fencing generation")
        if (
            command.expected_revision_id is not None
            and snapshot.current_revision_id != command.expected_revision_id
        ):
            raise AuthorizationLifecycleError("stale authorization revision")
    if command.revision is not None:
        if command.revision.revision_id in revisions:
            raise AuthorizationLifecycleError("authorization revision already exists")
        for revision in revisions.values():
            if (
                revision.proof_bindings.approvals_digest
                == command.revision.proof_bindings.approvals_digest
                or revision.proof_bindings.evidence_verification_bundle_digest
                == command.revision.proof_bindings.evidence_verification_bundle_digest
            ):
                raise AuthorizationLifecycleError(
                    "authorization approval and evidence proofs MUST NOT be reused"
                )

    transition = AuthorizationTransition.create(snapshot=snapshot, command=command)
    next_snapshot = AuthorizationSnapshot.from_transition(transition)
    return AuthorizationLifecycleWriteResult(
        status=AuthorizationWriteStatus.APPLIED,
        transition=transition,
        snapshot=next_snapshot,
    )


def replay_lifecycle(
    *,
    transitions: tuple[AuthorizationTransition, ...],
    revisions: dict[str, AuthorizationRevision],
) -> AuthorizationSnapshot | None:
    """Replay one complete ordered hash chain or fail closed."""

    snapshot: AuthorizationSnapshot | None = None
    seen_commands: set[str] = set()
    for expected_sequence, transition in enumerate(transitions, start=1):
        if transition.sequence != expected_sequence or transition.command_id in seen_commands:
            raise AuthorizationLifecycleError("lifecycle transition sequence is invalid")
        if transition.family_id != transitions[0].family_id:
            raise AuthorizationLifecycleError("lifecycle history mixed authorization families")
        if snapshot is None:
            if (
                transition.kind is not AuthorizationCommandKind.ADMIT
                or transition.previous_transition_digest is not None
                or transition.fencing_generation != 1
                or transition.predecessor_revision_id is not None
            ):
                raise AuthorizationLifecycleError("lifecycle history MUST start with admit")
        else:
            if (
                snapshot.status is not AuthorizationSnapshotStatus.ACTIVE
                or transition.previous_transition_digest != snapshot.head_transition_digest
                or transition.fencing_generation != snapshot.fencing_generation + 1
            ):
                raise AuthorizationLifecycleError("lifecycle transition chain is invalid")
            if transition.kind is AuthorizationCommandKind.RENEW:
                if transition.predecessor_revision_id != snapshot.current_revision_id:
                    raise AuthorizationLifecycleError("renewal predecessor is invalid")
            elif transition.kind is AuthorizationCommandKind.REVOKE:
                if transition.revision_id != snapshot.current_revision_id:
                    raise AuthorizationLifecycleError("revocation revision is invalid")
            else:
                raise AuthorizationLifecycleError("admit can occur only once")
        revision = revisions.get(transition.revision_id)
        if revision is None:
            raise AuthorizationLifecycleError("lifecycle transition references a missing revision")
        if transition.kind is AuthorizationCommandKind.RENEW and (
            revision.predecessor_revision_id != transition.predecessor_revision_id
        ):
            raise AuthorizationLifecycleError("renewal revision lineage is invalid")
        seen_commands.add(transition.command_id)
        snapshot = AuthorizationSnapshot.from_transition(transition)
    return snapshot


def fence_matches(snapshot: AuthorizationSnapshot | None, fence: LifecycleFence) -> bool:
    """Return true only for the exact active primary-store snapshot."""

    return (
        snapshot is not None
        and snapshot.status is AuthorizationSnapshotStatus.ACTIVE
        and snapshot.family_id == fence.family_id
        and snapshot.current_revision_id == fence.revision_id
        and snapshot.fencing_generation == fence.fencing_generation
        and snapshot.head_transition_digest == fence.transition_digest
    )


def audit_entry_for(
    transition: AuthorizationTransition,
) -> MappingProxyType[str, object]:
    """Build the immutable lifecycle audit entry committed with the transition."""

    body: dict[str, object] = {
        "kind": f"standing_authority.{transition.kind.value}",
        "family_id": transition.family_id,
        "sequence": transition.sequence,
        "revision_id": transition.revision_id,
        "fencing_generation": transition.fencing_generation,
        "transition_digest": transition.transition_digest,
        "actor_ref": transition.actor_ref,
        "actor_roles": list(transition.actor_roles),
        "authentication_evidence_digest": transition.authentication_evidence_digest,
        "authenticated_at": _instant(transition.authenticated_at),
        "correlation_id": transition.correlation_id,
        "occurred_at": _instant(transition.occurred_at),
        "execution_authority": False,
    }
    return MappingProxyType({**body, "audit_digest": _content_digest(body)})


__all__ = [
    "AuthenticatedAuthorizationCommand",
    "AuthorizationCommandKind",
    "AuthorizationLifecycleCommand",
    "AuthorizationLifecycleError",
    "AuthorizationLifecycleWriteResult",
    "AuthorizationProofBindings",
    "AuthorizationRevision",
    "AuthorizationSnapshot",
    "AuthorizationSnapshotStatus",
    "AuthorizationTransition",
    "AuthorizationWriteStatus",
    "LifecycleFence",
    "StandingAuthorizationLifecycleWriter",
    "audit_entry_for",
    "authorization_revision_id",
    "fence_matches",
    "plan_lifecycle_transition",
    "replay_lifecycle",
]
