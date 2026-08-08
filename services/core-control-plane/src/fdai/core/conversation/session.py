"""Session and principal data model for the operator console.

Data-only module; no I/O. See
[operator-console.md § 6](../../../../docs/roadmap/interfaces/operator-console.md).

The design intent is that a :class:`ConversationSession` is a bounded,
stateless-in-memory projection of the audit log: on recovery, the
coordinator reloads the session by replaying ``console.turn`` audit
entries for the given ``session_id``. Day 1 keeps the session in
process memory; the audit-log projection ships in Wave W1 when the
approval flow lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    """RBAC roles used by the console tool floor.

    Mirrors :mod:`fdai.shared.contracts.models.CeilingRole` and the
    ladder in
    [user-rbac-and-identity.md § 2](../../../../docs/roadmap/interfaces/user-rbac-and-identity.md).
    ``BREAK_GLASS`` is off-ladder and grants HIL-approval eligibility
    without ever returning ``enforce_auto`` on the RiskGate role axis.
    """

    READER = "reader"
    CONTRIBUTOR = "contributor"
    APPROVER = "approver"
    OWNER = "owner"
    BREAK_GLASS = "break_glass"


_ROLE_LADDER: dict[Role, int] = {
    Role.READER: 0,
    Role.CONTRIBUTOR: 1,
    Role.APPROVER: 2,
    Role.OWNER: 3,
    # BreakGlass is off-ladder (docs/roadmap/interfaces/user-rbac-and-identity.md).
    # It never satisfies min_role via the ladder; approval eligibility
    # is handled at dispatch time. Its rank is deliberately below Reader
    # so principal_has_role_at_least never returns True for BG on any
    # normal min_role check.
    Role.BREAK_GLASS: -1,
}


def principal_has_role_at_least(principal_role: Role, min_role: Role) -> bool:
    """True iff ``principal_role`` sits at or above ``min_role`` in the
    ordinary ladder. BreakGlass never satisfies the check.

    See docs/roadmap/decisioning/execution-model.md 2.5 (Axis F).
    """

    return _ROLE_LADDER[principal_role] >= _ROLE_LADDER[min_role]


@dataclass(frozen=True)
class Principal:
    """The caller identity for a console conversation.

    Kept intentionally small at Day 1: id (Entra OID or CLI principal
    id), role, and a channel-scoped display name for audit rendering.
    """

    id: str
    role: Role
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Principal.id MUST be non-empty")


TurnDirection = Literal["inbound", "outbound", "tool_call", "tool_result", "system"]


@dataclass(frozen=True)
class Turn:
    """One entry in a conversation transcript.

    Fields align with the ``console.turn`` audit contract in
    [operator-console.md § 13.1](../../../../docs/roadmap/interfaces/operator-console.md)
    so a future audit-log projection can reload sessions verbatim.
    """

    turn_id: str
    direction: TurnDirection
    content: str
    tool_name: str | None = None
    arguments: dict[str, object] = field(default_factory=dict)
    result_preview: str = ""
    tier: Literal["T0", "T1", "T2", "system"] = "T0"
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __post_init__(self) -> None:
        if not self.turn_id:
            raise ValueError("Turn.turn_id MUST be non-empty")


@dataclass
class ConversationSession:
    """Bounded, in-memory session state.

    Kept mutable at Day 1 for the CLI REPL. Wave W1 wraps this in an
    audit-log projection so the coordinator can crash and recover.
    """

    session_id: str
    principal: Principal
    channel_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    turns: list[Turn] = field(default_factory=list)

    def append(self, turn: Turn) -> None:
        self.turns.append(turn)

    def snapshot(self) -> tuple[Turn, ...]:
        """Return an immutable snapshot for inspection or audit projection."""

        return tuple(self.turns)


__all__ = [
    "ConversationSession",
    "Principal",
    "Role",
    "Turn",
    "TurnDirection",
    "principal_has_role_at_least",
]
