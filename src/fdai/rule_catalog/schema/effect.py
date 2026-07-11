"""Governance effect + enforcement - the safety dial for an assignment.

An FDAI rule is inert until an **assignment** binds it to a **scope** with an
**effect** (rule-governance.md "Model"). This module is the foundational layer:
the `Effect` and `Enforcement` enums, the strictest-effect precedence used to
resolve conflicting assignments, and the allowed effect/enforcement transition
table CI enforces. The `Scope`, `Assignment`, and `RuleSet` artifacts build on
these types.

Pure and I/O-free: every function is a deterministic decision over the enums so
the CI gate and the loader share one source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Effect(StrEnum):
    """What happens on a violation (rule-governance.md "Effects (Mode)").

    Maps onto the shadow -> enforce lifecycle, not just a label.
    """

    DISABLED = "disabled"
    """Rule/assignment is off - inert."""

    AUDIT = "audit"
    """Judge and log only, no change - equivalent to shadow mode (safe default)."""

    DENY = "deny"
    """Block the non-compliant change at the PR/admission gate - enforce (gated)."""

    REMEDIATE = "remediate"
    """Generate an auto-remediation PR (never auto-merged; via risk gate/HIL) - enforce (gated)."""


class Enforcement(StrEnum):
    """Whether to act at all - orthogonal to :class:`Effect`.

    Mirrors Azure Policy's ``enforcementMode``. ``do-not-enforce`` runs the
    check what-if only and is the mechanism behind ``audit`` / shadow; promotion
    flips it to ``enforce`` under the promotion gate.
    """

    ENFORCE = "enforce"
    DO_NOT_ENFORCE = "do-not-enforce"


# Strictness ordering for conflict resolution: deny > remediate > audit >
# disabled (rule-governance.md "Scope precedence"). Higher wins.
_STRICTNESS: dict[Effect, int] = {
    Effect.DISABLED: 0,
    Effect.AUDIT: 1,
    Effect.REMEDIATE: 2,
    Effect.DENY: 3,
}

# The enforce tier - effects that actually gate/mutate and therefore require the
# separate enforce-promotion approval to reach from a shadow (audit) state.
_ENFORCE_EFFECTS: frozenset[Effect] = frozenset({Effect.DENY, Effect.REMEDIATE})

# Allowed effect transitions (rule-governance.md transition table). Any pair not
# listed here is rejected in CI. Same-state is always a no-op and allowed.
_ALLOWED_TRANSITIONS: dict[Effect, frozenset[Effect]] = {
    Effect.DISABLED: frozenset({Effect.AUDIT}),
    Effect.AUDIT: frozenset({Effect.DENY, Effect.REMEDIATE, Effect.DISABLED}),
    Effect.DENY: frozenset({Effect.AUDIT, Effect.DISABLED}),
    Effect.REMEDIATE: frozenset({Effect.AUDIT, Effect.DISABLED}),
}


class EffectTransitionError(ValueError):
    """Raised when an effect transition is not allowed, or requires the
    enforce-promotion approval that was not granted."""


def default_effect() -> Effect:
    """New assignments default to ``audit`` (shadow)."""
    return Effect.AUDIT


def default_enforcement() -> Enforcement:
    """New assignments default to ``do-not-enforce`` (shadow)."""
    return Enforcement.DO_NOT_ENFORCE


def strictest_effect(effects: Iterable[Effect]) -> Effect:
    """Return the strictest effect (``deny`` > ``remediate`` > ``audit`` >
    ``disabled``) among conflicting assignments on the same rule+scope.

    Raises :class:`ValueError` on an empty input - a conflict resolution over no
    effects is a caller bug, not a silent ``disabled``.
    """
    ordered = sorted(effects, key=lambda e: _STRICTNESS[e], reverse=True)
    if not ordered:
        raise ValueError("strictest_effect requires at least one effect")
    return ordered[0]


def is_enforce_promotion(from_effect: Effect, to_effect: Effect) -> bool:
    """True when the transition raises a shadow (``audit``) assignment to an
    enforce effect (``deny`` / ``remediate``) - the transition that needs the
    separate enforce-promotion approval."""
    return from_effect is Effect.AUDIT and to_effect in _ENFORCE_EFFECTS


def is_enforce_tier(effect: Effect) -> bool:
    """True when ``effect`` actually gates / mutates (``deny`` / ``remediate``),
    as opposed to the inert ``audit`` / ``disabled`` states."""
    return effect in _ENFORCE_EFFECTS


def is_enforce_activation(from_enforcement: Enforcement, to_enforcement: Enforcement) -> bool:
    """True when the enforcement flag flips ``do-not-enforce`` -> ``enforce`` -
    the go-live moment that takes an enforce-tier effect out of shadow. Gated by
    the same enforce-promotion approval as raising the effect, so a two-step
    ``deny(shadow) -> deny(enforce)`` cannot reach production without review."""
    return from_enforcement is Enforcement.DO_NOT_ENFORCE and to_enforcement is Enforcement.ENFORCE


def validate_effect_transition(
    *,
    from_effect: Effect,
    to_effect: Effect,
    promotion_approved: bool = False,
) -> None:
    """Validate one effect transition against the governance transition table.

    A no-op (same state) is always allowed. Demotion toward ``audit`` /
    ``disabled`` is always allowed (fail toward safety). Raising to an enforce
    effect requires ``promotion_approved=True``. Any transition not in the table
    raises :class:`EffectTransitionError`.
    """
    if from_effect is to_effect:
        return
    allowed = _ALLOWED_TRANSITIONS.get(from_effect, frozenset())
    if to_effect not in allowed:
        raise EffectTransitionError(
            f"effect transition {from_effect.value!r} -> {to_effect.value!r} is not allowed "
            "(rule-governance.md transition table)"
        )
    if is_enforce_promotion(from_effect, to_effect) and not promotion_approved:
        raise EffectTransitionError(
            f"transition {from_effect.value!r} -> {to_effect.value!r} raises autonomy to enforce "
            "and requires the separate enforce-promotion approval"
        )


__all__ = [
    "Effect",
    "EffectTransitionError",
    "Enforcement",
    "default_effect",
    "default_enforcement",
    "is_enforce_activation",
    "is_enforce_promotion",
    "is_enforce_tier",
    "strictest_effect",
    "validate_effect_transition",
]
