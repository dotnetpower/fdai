"""Verifier identity separation and proof-store writer readback.

The verifier must differ from every source, producer, reviewer, and executor-class principal.
It refuses to start on equality. A proof store that another role can write makes the verifier
``self_verified``: that state exists only in capability state and writes no rejection record.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .trust_registry import DeploymentAnchors, TrustRegistry


class VerifierSeparationError(RuntimeError):
    """The verifier identity equals an identity it must stay independent of."""


@dataclass(frozen=True, slots=True)
class ProofStoreGrantReadback:
    """Grants and memberships read back from the proof store's catalog."""

    writer_role: str
    reader_roles: tuple[str, ...]
    insert_holders: tuple[str, ...]
    mutation_holders: tuple[str, ...]
    writer_role_members: tuple[str, ...]
    immutability_guards: tuple[str, ...]
    expected_guards: tuple[str, ...]
    allowed_writer_members: tuple[str, ...] = field(default_factory=tuple)

    def self_verified_reasons(self) -> tuple[str, ...]:
        """Return why another principal could write proofs; empty means writer-exclusive."""

        reasons: list[str] = []
        if set(self.insert_holders) - {self.writer_role}:
            reasons.append("foreign_insert_grant")
        if self.mutation_holders:
            reasons.append("update_or_delete_grant")
        if set(self.writer_role_members) - set(self.allowed_writer_members):
            reasons.append("foreign_writer_membership")
        if set(self.reader_roles) & set(self.writer_role_members):
            reasons.append("consumer_holds_writer_role")
        if set(self.expected_guards) - set(self.immutability_guards):
            reasons.append("immutability_guard_missing")
        return tuple(sorted(reasons))


def assert_verifier_separation(
    registry: TrustRegistry,
    anchors: DeploymentAnchors,
    *,
    verifier_principal: str,
    executor_class_principals: Iterable[str],
) -> None:
    """Refuse to start when the verifier principal equals any independent principal."""

    protected = {principal for principal in executor_class_principals if principal}
    for entry in registry.purposes.values():
        for anchor in entry.independent_anchor_ids():
            principal = anchors.principal(anchor)
            if principal is not None:
                protected.add(principal)
    if verifier_principal in protected:
        raise VerifierSeparationError(
            "operational evidence verifier identity equals a source, producer, reviewer, "
            "or executor-class identity"
        )


__all__ = ["ProofStoreGrantReadback", "VerifierSeparationError", "assert_verifier_separation"]
