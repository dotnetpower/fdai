"""Role enum + capability matrix.

Data-only module (SRP): no I/O, no framework, no adapter imports. The
capability matrix mirrors [§ 3 Persona → Action Matrix]
(../../../../docs/roadmap/user-rbac-and-identity.md#3-persona--action-matrix)
of the design doc so a code change and a doc change stay diff-visible together.

Break-Glass isolation
---------------------

:attr:`Role.BREAK_GLASS` is a **hard-isolated** principal:

- It is NOT a superset of :attr:`Role.OWNER`; the two role bags overlap
  only where the matrix explicitly says so (kill-switch).
- It is never auto-activated by claims alone. The
  :class:`~aiopspilot.core.rbac.resolver.RoleResolver` drops
  :attr:`Role.BREAK_GLASS` from the derived Principal even when the token
  advertises it; activation requires an operator-recorded
  :class:`~aiopspilot.core.rbac.resolver.BreakGlassActivation`
  (incident id + timebox) and is a separate call.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class Role(StrEnum):
    """The five human-user roles governed by this module.

    Values are stable string tokens (App Role claim values) — see
    [`user-rbac-and-identity.md § 4.4 App Roles`]
    (../../../../docs/roadmap/user-rbac-and-identity.md#44-app-roles-token-surface).
    Do NOT rename without a coordinated Entra ID app-registration update.
    """

    READER = "Reader"
    CONTRIBUTOR = "Contributor"
    APPROVER = "Approver"
    OWNER = "Owner"
    BREAK_GLASS = "BreakGlass"


class Capability(StrEnum):
    """Individual actions the read API may gate.

    One capability per matrix row. Kept coarse-grained on purpose —
    differentiation for high-risk paths comes from
    :func:`aiopspilot.core.rbac.enforcer.RoleEnforcer.no_self_approval`
    and PR-side CI checks, not from adding more capabilities.
    """

    VIEW_CONSOLE = "view-console"
    AUTHOR_DRAFT_PR = "author-draft-pr"
    REVIEW_GOVERNANCE_PR = "review-governance-pr"
    APPROVE_QUORUM_PROMOTION = "approve-quorum-promotion"
    APPROVE_EXEMPTION = "approve-exemption"
    APPROVE_OVERRIDE = "approve-override"
    APPROVE_RUNTIME_HIL = "approve-runtime-hil"
    TRIGGER_KILL_SWITCH = "trigger-kill-switch"
    GRANT_EMERGENCY_ACCESS = "grant-emergency-access"
    MANAGE_GROUP_MEMBERSHIP = "manage-group-membership"
    APPLY_INFRA_IAC = "apply-infra-iac"


# The capability bag for each role. The doc's matrix uses ✓/blank; the
# code encodes the same rows as frozensets so a lookup is O(1). Any
# change here MUST update
# `docs/roadmap/user-rbac-and-identity.md § 3` in the same PR — the
# doc row and the frozenset entry are the single source of truth
# together (see coding-conventions.instructions.md § Documentation).
_READER_CAPS: Final = frozenset({Capability.VIEW_CONSOLE})

_CONTRIBUTOR_CAPS: Final = _READER_CAPS | frozenset({Capability.AUTHOR_DRAFT_PR})

_APPROVER_CAPS: Final = _CONTRIBUTOR_CAPS | frozenset(
    {
        Capability.REVIEW_GOVERNANCE_PR,
        Capability.APPROVE_QUORUM_PROMOTION,
        Capability.APPROVE_EXEMPTION,
        Capability.APPROVE_OVERRIDE,
        Capability.APPROVE_RUNTIME_HIL,
    }
)

_OWNER_CAPS: Final = _APPROVER_CAPS | frozenset(
    {
        Capability.TRIGGER_KILL_SWITCH,
        Capability.MANAGE_GROUP_MEMBERSHIP,
        Capability.APPLY_INFRA_IAC,
    }
)

# BreakGlass is intentionally NOT a superset of Owner. It carries only the
# emergency-scoped capabilities, so a compromised Owner-account attacker
# cannot pivot into break-glass grants without also compromising the
# separately guarded `aw-break-glass` membership (doc § 2 note).
_BREAK_GLASS_CAPS: Final = frozenset(
    {
        Capability.VIEW_CONSOLE,
        Capability.TRIGGER_KILL_SWITCH,
        Capability.GRANT_EMERGENCY_ACCESS,
    }
)


ROLE_CAPABILITIES: Final[Mapping[Role, frozenset[Capability]]] = MappingProxyType(
    {
        Role.READER: _READER_CAPS,
        Role.CONTRIBUTOR: _CONTRIBUTOR_CAPS,
        Role.APPROVER: _APPROVER_CAPS,
        Role.OWNER: _OWNER_CAPS,
        Role.BREAK_GLASS: _BREAK_GLASS_CAPS,
    }
)
"""Read-only mapping of :class:`Role` → the capability bag it carries.

Wrapped in :class:`types.MappingProxyType` so a caller cannot mutate the
matrix at runtime — the only way to change a role's bag is a code edit
that goes through review.
"""


def capabilities_for(roles: Iterable[Role]) -> frozenset[Capability]:
    """Return the union of capabilities held by the given roles.

    An empty iterable returns an empty frozenset — an unassigned user
    holds no capabilities. Callers MUST NOT infer "at least
    :attr:`Capability.VIEW_CONSOLE`" from a valid Entra sign-in; the
    read API's first-sign-in-denied audit path
    ([`user-rbac-and-identity.md § 10.3`]
    (../../../../docs/roadmap/user-rbac-and-identity.md#103-first-sign-in-unassigned-users))
    depends on this being deny-by-default.
    """
    acc: frozenset[Capability] = frozenset()
    for role in roles:
        acc = acc | ROLE_CAPABILITIES[role]
    return acc


def has_capability(roles: Iterable[Role], capability: Capability) -> bool:
    """Return ``True`` iff *any* of ``roles`` carries ``capability``."""
    for role in roles:
        if capability in ROLE_CAPABILITIES[role]:
            return True
    return False


__all__ = [
    "ROLE_CAPABILITIES",
    "Capability",
    "Role",
    "capabilities_for",
    "has_capability",
]
