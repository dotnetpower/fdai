"""HIL delegation gate - who may approve a parked HIL item, and how.

The :class:`~fdai.core.hil_resume.coordinator.HilResumeCoordinator` already
enforces the hard floor: no self-approval (``approver == submitter``) and a
verifiable, distinct approver identity. This module adds the **delegation
policy** on top of that floor, in one pure, testable place:

- A HIL item is **role-scoped**, not locked to one named person. Any operator
  who holds the HIL-approval capability may resolve it (a queue, not an inbox).
- When the item carries an ``assignee`` (the operator it was surfaced to) and a
  *different* authorized operator approves it, that is a **delegation** - it is
  allowed (same authority) but recorded distinctly, so the audit shows both the
  actual approver and the original assignee.
- Self-approval is refused here too (defense in depth with the coordinator),
  and an operator lacking the HIL-approval capability is refused.

Pure function: no I/O. The coordinator and the read-API HIL callback both call
it so the rule never drifts between the two entry points.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DelegationMode(StrEnum):
    """How an allowed HIL approval relates to the item's assignee."""

    DIRECT = "direct"
    """The approver is the assignee the item was surfaced to."""

    DELEGATED = "delegated"
    """A different authorized operator approved on the assignee's behalf."""

    ROLE_SCOPED = "role_scoped"
    """The item had no specific assignee; any authorized approver resolves it."""


class DelegationRefusal(StrEnum):
    """Why a HIL approval was refused before any execution."""

    BLANK_APPROVER = "blank_approver"
    """The approver identity is empty / unverifiable."""

    UNKNOWN_SUBMITTER = "unknown_submitter"
    """The park has no recorded submitter, so distinctness cannot be proven."""

    SELF_APPROVAL = "self_approval"
    """The approver is the submitter of the action (no self-approval)."""

    MISSING_CAPABILITY = "missing_capability"
    """The approver does not hold the HIL-approval capability."""


@dataclass(frozen=True, slots=True)
class DelegationDecision:
    """The verdict of :func:`evaluate_hil_delegation`."""

    allowed: bool
    mode: DelegationMode | None = None
    refusal: DelegationRefusal | None = None

    @property
    def is_delegated(self) -> bool:
        """True when an authorized operator approved on another's behalf."""

        return self.allowed and self.mode is DelegationMode.DELEGATED


def evaluate_hil_delegation(
    *,
    approver_oid: str,
    submitter_oid: str,
    approver_can_approve_hil: bool,
    assignee_oid: str | None = None,
) -> DelegationDecision:
    """Decide whether ``approver_oid`` may resolve a parked HIL item.

    The checks run in a fixed, fail-closed order:

    1. blank approver -> refuse (unverifiable identity);
    2. blank submitter -> refuse (cannot prove distinctness);
    3. approver == submitter -> refuse (no self-approval);
    4. approver lacks the HIL-approval capability -> refuse;
    5. otherwise allowed, with the mode derived from the assignee:
       - no assignee -> ``ROLE_SCOPED``;
       - approver == assignee -> ``DIRECT``;
       - approver != assignee -> ``DELEGATED`` (recorded for the audit).

    ``approver_can_approve_hil`` is supplied by the caller's RBAC check
    (``Capability.APPROVE_RUNTIME_HIL``); this function never reads roles
    itself, so it stays pure and identical across entry points.
    """

    approver = approver_oid.strip()
    submitter = submitter_oid.strip()
    assignee = (assignee_oid or "").strip()

    if not approver:
        return DelegationDecision(allowed=False, refusal=DelegationRefusal.BLANK_APPROVER)
    if not submitter:
        return DelegationDecision(allowed=False, refusal=DelegationRefusal.UNKNOWN_SUBMITTER)
    if approver == submitter:
        return DelegationDecision(allowed=False, refusal=DelegationRefusal.SELF_APPROVAL)
    if not approver_can_approve_hil:
        return DelegationDecision(allowed=False, refusal=DelegationRefusal.MISSING_CAPABILITY)

    if not assignee:
        return DelegationDecision(allowed=True, mode=DelegationMode.ROLE_SCOPED)
    if approver == assignee:
        return DelegationDecision(allowed=True, mode=DelegationMode.DIRECT)
    return DelegationDecision(allowed=True, mode=DelegationMode.DELEGATED)


__all__ = [
    "DelegationDecision",
    "DelegationMode",
    "DelegationRefusal",
    "evaluate_hil_delegation",
]
