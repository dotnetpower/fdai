"""Governance assignment - bind a rule (or rule-set) to a scope with an effect.

An assignment is what makes a rule live (rule-governance.md "Model"): it applies
one or more rules to a :class:`~fdai.rule_catalog.schema.scope.Scope` with an
:class:`~fdai.rule_catalog.schema.effect.Effect` and an
:class:`~fdai.rule_catalog.schema.effect.Enforcement` flag. A rule-set is
pre-expanded to its member rule ids by the caller, so this module stays
independent of the rule-set artifact.

:func:`resolve_assignments` is the runtime conflict resolver: among the
assignments that cover a resource and target a rule, the **strictest effect
wins** and the **most-specific scope** supplies the parameters; a genuine
specificity tie on parameters is flagged for HIL, and the overridden assignments
are recorded for the audit trail (rule-governance.md "Scope precedence").

Pure and I/O-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fdai.rule_catalog.schema.effect import (
    Effect,
    Enforcement,
    strictest_effect,
)
from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.scope import (
    ResourceContext,
    ScopeMatcher,
)


@dataclass(frozen=True, slots=True)
class Assignment:
    """Binds ``target_rule_ids`` to ``scope`` with an effect + enforcement.

    Defaults are shadow: ``effect=audit`` and ``enforcement=do-not-enforce``
    (rule-governance.md). ``effect_overrides`` tunes the effect per rule (an
    assignment of a rule-set overriding the set's ``default_effect``);
    ``parameters`` are CSP-neutral assignment-wide string values, and
    ``parameter_overrides`` tunes them per rule (a per-rule entry wins over the
    assignment-wide value for that key - see :meth:`parameters_for`).
    """

    id: str
    target_rule_ids: frozenset[str]
    scope: ScopeMatcher
    effect: Effect = Effect.AUDIT
    enforcement: Enforcement = Enforcement.DO_NOT_ENFORCE
    parameters: Mapping[str, str] = field(default_factory=dict)
    effect_overrides: Mapping[str, Effect] = field(default_factory=dict)
    parameter_overrides: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    provenance: Provenance | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Assignment.id MUST be non-empty")
        if not self.target_rule_ids:
            raise ValueError("Assignment.target_rule_ids MUST bind at least one rule")
        # An override for a rule the assignment does not bind is dead config
        # (a typo silently ignored). Reject it at the boundary.
        stray = (set(self.effect_overrides) | set(self.parameter_overrides)) - self.target_rule_ids
        if stray:
            raise ValueError(
                f"Assignment override targets rules not in target_rule_ids: {sorted(stray)}"
            )

    def applies_to(self, rule_id: str, ctx: ResourceContext) -> bool:
        """True when this assignment binds ``rule_id`` and its scope covers the
        resource."""
        return rule_id in self.target_rule_ids and self.scope.covers(ctx)

    def effect_for(self, rule_id: str) -> Effect:
        """The effect for ``rule_id``: the per-rule override if declared, else the
        assignment's top-level effect."""
        return self.effect_overrides.get(rule_id, self.effect)

    def parameters_for(self, rule_id: str) -> Mapping[str, str]:
        """The parameters for ``rule_id``: the assignment-wide ``parameters``
        merged with this rule's ``parameter_overrides`` (the per-rule entry wins
        per key). Always a fresh mapping - mutating it never touches the
        assignment's own ``parameters``."""
        override = self.parameter_overrides.get(rule_id)
        if not override:
            return dict(self.parameters)
        return {**self.parameters, **override}


@dataclass(frozen=True, slots=True)
class AssignmentResolution:
    """The resolved governance decision for one rule on one resource."""

    rule_id: str
    effective_effect: Effect
    enforcement: Enforcement
    parameters: Mapping[str, str]
    winning_assignment_id: str
    parameter_tie: bool
    overridden_assignment_ids: tuple[str, ...]


def _param_key(params: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(params.items()))


def resolve_assignments(
    *,
    assignments: Sequence[Assignment],
    ctx: ResourceContext,
    rule_id: str,
) -> AssignmentResolution | None:
    """Resolve the effective governance decision for ``rule_id`` on ``ctx``.

    Returns ``None`` when no assignment covers the resource for that rule (the
    rule is unenforced on that scope - governance is default-audit, not
    default-deny; an unmatched event still routes to HIL upstream, this never
    fails open). Otherwise:

    - ``effective_effect`` = the strictest effect across matching assignments
      (``deny`` > ``remediate`` > ``audit`` > ``disabled``).
    - ``enforcement`` = ``enforce`` if any assignment carrying that effect
      enforces, else ``do-not-enforce`` (an active enforce wins).
    - ``parameters`` = from the most-specific scope; ``parameter_tie`` is True
      when two equally-specific scopes disagree on parameters (escalate to HIL).
    - ``overridden_assignment_ids`` records the losers for the audit trail.
    """
    matching = [a for a in assignments if a.applies_to(rule_id, ctx)]
    if not matching:
        return None

    effective = strictest_effect([a.effect_for(rule_id) for a in matching])
    effect_carriers = [a for a in matching if a.effect_for(rule_id) is effective]
    enforcement = (
        Enforcement.ENFORCE
        if any(a.enforcement is Enforcement.ENFORCE for a in effect_carriers)
        else Enforcement.DO_NOT_ENFORCE
    )

    # Rank parameter precedence by each assignment's specificity RELATIVE to
    # ctx (the most-specific include that actually covers this resource), not
    # the binding's context-free max include level - otherwise a broad include
    # bundled with an unrelated narrow one would wrongly win.
    top_specificity = max(a.scope.covering_specificity(ctx) for a in matching)
    param_sources = [a for a in matching if a.scope.covering_specificity(ctx) == top_specificity]
    param_tie = len({_param_key(a.parameters_for(rule_id)) for a in param_sources}) > 1
    winner = param_sources[0]
    overridden = tuple(a.id for a in matching if a.id != winner.id)

    return AssignmentResolution(
        rule_id=rule_id,
        effective_effect=effective,
        enforcement=enforcement,
        parameters=winner.parameters_for(rule_id),
        winning_assignment_id=winner.id,
        parameter_tie=param_tie,
        overridden_assignment_ids=overridden,
    )


__all__ = ["Assignment", "AssignmentResolution", "resolve_assignments"]
