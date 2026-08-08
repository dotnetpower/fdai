"""Stewardship data model - pure dataclasses and enums (SRP: no I/O, no parsing).

The parsing + fail-fast validation that turns a config mapping into these types
lives in :mod:`fdai.core.stewardship.resolver`; the coverage findings live in
:mod:`fdai.core.stewardship.coverage`; escalation routing lives in
:mod:`fdai.core.stewardship.escalation`. This module only defines the shapes.

Design authority:
[`docs/roadmap/interfaces/agent-stewardship-and-handover.md`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class StewardshipValidationError(ValueError):
    """Raised when stewardship config fails structural / policy validation.

    Fail-fast: FDAI does not boot the stewardship layer with a missing
    maintainer, an unmapped agent, or a placeholder id left in a fork.
    The message is English and points at the offending key so a fork can
    fix its config without reading the code.
    """


class Responsibility(StrEnum):
    """RACI-lite tag on a steward entry.

    ``ACCOUNTABLE`` is on the escalation hot path (paged first).
    ``INFORMED`` is notified for awareness only, after the accountable tier.
    """

    ACCOUNTABLE = "accountable"
    INFORMED = "informed"


class Duty(StrEnum):
    """Ordered operational duty for an accountable steward."""

    PRIMARY = "primary"
    BACKUP = "backup"
    ESCALATION = "escalation"


class StewardKind(StrEnum):
    """Whether a steward subject is a single person or an Entra group.

    A ``GROUP`` subject means "whoever is in this Entra group is a steward";
    it is expanded through a
    :class:`~fdai.core.stewardship.directory.GroupMembershipProvider` at
    routing time, best-effort.
    """

    USER = "user"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class StewardSubject:
    """One steward: an Entra object id, its kind, and its responsibility."""

    kind: StewardKind
    id: str
    responsibility: Responsibility
    duty: Duty | None = None

    @property
    def is_accountable(self) -> bool:
        """Return ``True`` iff this subject is on the accountable tier."""
        return self.responsibility is Responsibility.ACCOUNTABLE


@dataclass(frozen=True, slots=True)
class AgentStewardship:
    """The steward set for one pantheon agent.

    ``accept_autonomous_reason`` is set (non-empty) only when the agent runs
    with no accountable steward; the maintainer is then its escalation
    fallback. An agent with neither an accountable steward nor a reason is
    rejected at load time.
    """

    agent_name: str
    stewards: tuple[StewardSubject, ...] = ()
    accept_autonomous_reason: str | None = None

    @property
    def is_autonomous(self) -> bool:
        """Return ``True`` iff the agent is declared ``accept_autonomous``."""
        return bool(self.accept_autonomous_reason)

    @property
    def accountable(self) -> tuple[StewardSubject, ...]:
        """Accountable-tier stewards, in declared order."""
        return tuple(s for s in self.stewards if s.is_accountable)

    @property
    def informed(self) -> tuple[StewardSubject, ...]:
        """Informed-tier stewards, in declared order."""
        return tuple(s for s in self.stewards if not s.is_accountable)

    @property
    def primary(self) -> tuple[StewardSubject, ...]:
        """Primary accountable owners, in declared order."""
        return tuple(s for s in self.accountable if s.duty is Duty.PRIMARY)

    @property
    def backup(self) -> tuple[StewardSubject, ...]:
        """Backup accountable owners, in declared order."""
        return tuple(s for s in self.accountable if s.duty is Duty.BACKUP)

    @property
    def escalation(self) -> tuple[StewardSubject, ...]:
        """Final domain escalation owners, in declared order."""
        return tuple(s for s in self.accountable if s.duty is Duty.ESCALATION)

    @property
    def accountable_user_ids(self) -> frozenset[str]:
        """Distinct accountable **user** (not group) object ids.

        Used for the bus-factor metric - a group counts as one opaque unit
        elsewhere, but bus-factor measures how many distinct *people* can act.
        """
        return frozenset(
            s.id for s in self.stewards if s.is_accountable and s.kind is StewardKind.USER
        )


@dataclass(frozen=True, slots=True)
class Maintainer:
    """An FDAI platform owner, identified by stable Entra user object id."""

    oid: str


@dataclass(frozen=True, slots=True)
class StewardshipMap:
    """The validated handover map - maintainers + all 15 agents.

    Built by :func:`fdai.core.stewardship.resolver.load_stewardship_from_mapping`
    (which enforces the fail-fast invariants). Once constructed it is immutable
    and safe to share across the control loop.
    """

    version: int
    maintainers: tuple[Maintainer, ...]
    agents: Mapping[str, AgentStewardship]
    channels: Mapping[str, str] = field(default_factory=dict)
    hop_timeout_seconds: int = 900
    over_assigned_max: int = 5

    def __post_init__(self) -> None:
        # Freeze the mappings so a caller cannot mutate them after validation.
        object.__setattr__(self, "channels", MappingProxyType(dict(self.channels)))
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))

    @property
    def maintainer_oids(self) -> tuple[str, ...]:
        """Maintainer object ids, in declared order."""
        return tuple(m.oid for m in self.maintainers)

    def agent(self, name: str) -> AgentStewardship:
        """Return the :class:`AgentStewardship` for ``name`` (KeyError if absent)."""
        return self.agents[name]


__all__ = [
    "AgentStewardship",
    "Duty",
    "Maintainer",
    "Responsibility",
    "StewardKind",
    "StewardSubject",
    "StewardshipMap",
    "StewardshipValidationError",
]
