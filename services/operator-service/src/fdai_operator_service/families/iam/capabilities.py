"""Fixed Operator role ceilings used by the service-local IAM family."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from fdai_service_contracts import OperatorRole


class IamCapability(StrEnum):
    """Capabilities required by the extracted IAM and governance routes."""

    VIEW_CONSOLE = "view-console"
    AUTHOR_DRAFT_PR = "author-draft-pr"
    APPROVE_RUNTIME_HIL = "approve-runtime-hil"
    TRIGGER_KILL_SWITCH = "trigger-kill-switch"
    MANAGE_RUNTIME_SETTINGS = "manage-runtime-settings"
    MANAGE_GROUP_MEMBERSHIP = "manage-group-membership"


ROLE_CAPABILITIES: Final[dict[OperatorRole, frozenset[IamCapability]]] = {
    OperatorRole.READER: frozenset({IamCapability.VIEW_CONSOLE}),
    OperatorRole.CONTRIBUTOR: frozenset(
        {IamCapability.VIEW_CONSOLE, IamCapability.AUTHOR_DRAFT_PR}
    ),
    OperatorRole.APPROVER: frozenset(
        {
            IamCapability.VIEW_CONSOLE,
            IamCapability.AUTHOR_DRAFT_PR,
            IamCapability.APPROVE_RUNTIME_HIL,
        }
    ),
    OperatorRole.OWNER: frozenset(
        {
            IamCapability.VIEW_CONSOLE,
            IamCapability.AUTHOR_DRAFT_PR,
            IamCapability.APPROVE_RUNTIME_HIL,
            IamCapability.TRIGGER_KILL_SWITCH,
            IamCapability.MANAGE_RUNTIME_SETTINGS,
            IamCapability.MANAGE_GROUP_MEMBERSHIP,
        }
    ),
    OperatorRole.BREAK_GLASS: frozenset(
        {IamCapability.VIEW_CONSOLE, IamCapability.TRIGGER_KILL_SWITCH}
    ),
}


def capabilities_for(roles: Iterable[OperatorRole]) -> frozenset[IamCapability]:
    """Return the explicit union without treating BreakGlass as Owner."""
    capabilities: frozenset[IamCapability] = frozenset()
    for role in roles:
        capabilities |= ROLE_CAPABILITIES[role]
    return capabilities


def has_capability(roles: Iterable[OperatorRole], capability: IamCapability) -> bool:
    """Return whether any asserted role carries the exact capability."""
    return capability in capabilities_for(roles)


__all__ = [
    "IamCapability",
    "ROLE_CAPABILITIES",
    "capabilities_for",
    "has_capability",
]
