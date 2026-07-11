"""The ``ownership_transfer`` signal - the CSP-neutral handoff trigger.

Emitted by whatever the fork wires as the handoff moment (a PR label, a resource
tag, or an explicit console request; see
``docs/roadmap/operations/operational-readiness.md`` "Trigger"). It carries the
target scope, the submitter identity, and the target environment - never a role
or a privileged token.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OwnershipTransfer:
    """A normalized dev-to-ops handoff request.

    ``scope`` is a resource-group-equivalent-or-narrower id (the same scope
    hierarchy the rule-governance overrides use). ``target_environment`` is the
    normalized environment word (``"prod"`` / ``"non-prod"`` / ...); the ORR
    tightens the gate for a ``prod`` target. ``correlation_id`` ties the review
    back to the triggering event for audit.
    """

    scope: str
    submitter: str
    target_environment: str
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        # Validate at the boundary: a handoff with no scope or submitter cannot
        # be reviewed or audited, so fail closed rather than certify a blank.
        if not self.scope.strip():
            raise ValueError("OwnershipTransfer.scope MUST be non-empty")
        if not self.submitter.strip():
            raise ValueError("OwnershipTransfer.submitter MUST be non-empty")
        if not self.target_environment.strip():
            raise ValueError("OwnershipTransfer.target_environment MUST be non-empty")


__all__ = ["OwnershipTransfer"]
