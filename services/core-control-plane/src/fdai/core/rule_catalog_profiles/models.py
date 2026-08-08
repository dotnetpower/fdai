"""Profile value objects mirroring ``shared/contracts/profile/schema.json``.

Kept in the ``core/`` tree because the resolve algorithm is a pure
function (no I/O) that the composition root calls at startup - a fork
that wants a different resolve strategy overrides the registry, not
this model layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ProfileMode(StrEnum):
    """Per-rule mode override that a profile may apply."""

    SHADOW = "shadow"
    ENFORCE = "enforce"


class SeverityOverride(StrEnum):
    """The severity levels a profile may pin.

    Kept independent from the ``Severity`` enum on the rule schema so
    a profile can be authored without importing the full rule model
    (which pulls in the whole ontology).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[SeverityOverride, int] = {
    SeverityOverride.LOW: 0,
    SeverityOverride.MEDIUM: 1,
    SeverityOverride.HIGH: 2,
    SeverityOverride.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class ProfileRule:
    """One authored line inside a :class:`Profile` (pre-resolution)."""

    id: str
    mode: ProfileMode | None = None
    severity_override: SeverityOverride | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)
    disabled: bool = False


@dataclass(frozen=True, slots=True)
class Profile:
    """A named bundle of :class:`ProfileRule` entries.

    ``extends`` may reference upstream profiles; :meth:`resolve`
    walks the chain deterministically and merges children over parents.
    """

    id: str
    title: str
    rules: tuple[ProfileRule, ...]
    extends: tuple[str, ...] = ()
    parameters: Mapping[str, object] = field(default_factory=dict)
    description: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ProfileResolutionError(f"profile {self.id!r} declares rule {rule.id!r} twice")
            seen.add(rule.id)


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    """One :class:`ProfileRule` after the extend chain is flattened."""

    id: str
    mode: ProfileMode
    severity_override: SeverityOverride | None
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    """Flat, deterministic view produced by :meth:`ProfileRegistry.resolve`.

    ``rules`` is ordered by rule id so a diff between two resolved
    profiles is byte-stable.
    """

    id: str
    title: str
    rules: tuple[ResolvedRule, ...]

    def get(self, rule_id: str) -> ResolvedRule | None:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    def ids(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.rules)


class ProfileResolutionError(ValueError):
    """Raised on any structural error the registry refuses to proceed on.

    - cycle in the extends graph
    - unknown parent id
    - profile referencing an unknown rule id
    - severity_override downgrading below a floor
    - duplicate rule declaration inside one profile
    """


def severity_at_or_above_floor(candidate: SeverityOverride, floor: SeverityOverride) -> bool:
    """True if ``candidate`` is at least as severe as ``floor``.

    Used by :class:`ProfileRegistry.resolve` to enforce the "profile MAY
    escalate severity but MAY NOT downgrade below the rule's authored
    floor" rule in the schema description.
    """
    return _SEVERITY_ORDER[candidate] >= _SEVERITY_ORDER[floor]


__all__ = [
    "Profile",
    "ProfileMode",
    "ProfileResolutionError",
    "ProfileRule",
    "ResolvedProfile",
    "ResolvedRule",
    "SeverityOverride",
    "severity_at_or_above_floor",
]
