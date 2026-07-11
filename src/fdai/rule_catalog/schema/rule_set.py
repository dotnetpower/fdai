"""Governance rule-set (initiative) - a named, versioned group of rules.

The Azure-Policy *initiative* analog (rule-governance.md "Model"): a versioned
bundle (e.g. a security baseline) whose members are pinned by rule id + version
and may each declare a ``default_effect``. An :class:`Assignment` binds the whole
set to a scope; :func:`assignment_from_rule_set` derives that assignment,
carrying the per-rule defaults as ``effect_overrides`` (which an assignment-level
override may further tune - rule-governance.md).

Pure and I/O-free.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.rule_catalog.schema.assignment import Assignment
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.scope import Scope


@dataclass(frozen=True, slots=True)
class RuleSetMember:
    """One rule in a rule-set, version-pinned with a per-rule default effect."""

    rule_id: str
    version: str
    default_effect: Effect = Effect.AUDIT

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("RuleSetMember.rule_id MUST be non-empty")
        if not self.version.strip():
            raise ValueError("RuleSetMember.version MUST be non-empty (members are version-pinned)")


@dataclass(frozen=True, slots=True)
class RuleSet:
    """A named, versioned group of rules (an initiative / baseline)."""

    id: str
    version: str
    members: tuple[RuleSetMember, ...]
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("RuleSet.id MUST be non-empty")
        if not self.version.strip():
            raise ValueError("RuleSet.version MUST be non-empty")
        if not self.members:
            raise ValueError("RuleSet.members MUST contain at least one rule")
        seen: set[str] = set()
        for m in self.members:
            if m.rule_id in seen:
                raise ValueError(f"RuleSet {self.id!r} has duplicate member rule {m.rule_id!r}")
            seen.add(m.rule_id)

    def rule_ids(self) -> frozenset[str]:
        return frozenset(m.rule_id for m in self.members)

    def default_effect_for(self, rule_id: str) -> Effect:
        for m in self.members:
            if m.rule_id == rule_id:
                return m.default_effect
        raise KeyError(f"{rule_id!r} is not a member of rule-set {self.id!r}")

    def version_for(self, rule_id: str) -> str:
        for m in self.members:
            if m.rule_id == rule_id:
                return m.version
        raise KeyError(f"{rule_id!r} is not a member of rule-set {self.id!r}")


def assignment_from_rule_set(
    rule_set: RuleSet,
    *,
    id: str,
    scope: Scope,
    effect: Effect = Effect.AUDIT,
    enforcement: Enforcement = Enforcement.DO_NOT_ENFORCE,
    parameters: Mapping[str, str] | None = None,
    extra_overrides: Mapping[str, Effect] | None = None,
    provenance: Provenance | None = None,
) -> Assignment:
    """Derive an :class:`Assignment` that binds every member of ``rule_set`` to
    ``scope``.

    The rule-set's per-rule ``default_effect`` becomes the assignment's
    ``effect_overrides``; an ``extra_overrides`` entry (an assignment-level tune)
    wins over the set default for that rule. The top-level ``effect`` /
    ``enforcement`` default to shadow. ``provenance`` is the binding assignment's
    own attribution (not the rule-set's).
    """
    overrides: dict[str, Effect] = {m.rule_id: m.default_effect for m in rule_set.members}
    if extra_overrides:
        overrides.update(extra_overrides)
    return Assignment(
        id=id,
        target_rule_ids=rule_set.rule_ids(),
        scope=scope,
        effect=effect,
        enforcement=enforcement,
        parameters=dict(parameters or {}),
        effect_overrides=overrides,
        provenance=provenance,
    )


__all__ = ["RuleSet", "RuleSetMember", "assignment_from_rule_set"]
