"""Governance effect + enforcement: precedence and transition validation."""

from __future__ import annotations

import pytest

from fdai.rule_catalog.schema.effect import (
    Effect,
    EffectTransitionError,
    Enforcement,
    default_effect,
    default_enforcement,
    is_enforce_activation,
    is_enforce_promotion,
    is_enforce_tier,
    strictest_effect,
    validate_effect_transition,
)


def test_defaults_are_shadow() -> None:
    assert default_effect() is Effect.AUDIT
    assert default_enforcement() is Enforcement.DO_NOT_ENFORCE


def test_strictest_effect_ordering() -> None:
    # deny > remediate > audit > disabled
    assert strictest_effect([Effect.AUDIT, Effect.DENY]) is Effect.DENY
    assert strictest_effect([Effect.AUDIT, Effect.REMEDIATE]) is Effect.REMEDIATE
    assert strictest_effect([Effect.DISABLED, Effect.AUDIT]) is Effect.AUDIT
    assert strictest_effect([Effect.REMEDIATE, Effect.DENY]) is Effect.DENY
    assert strictest_effect([Effect.DISABLED]) is Effect.DISABLED


def test_strictest_effect_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one effect"):
        strictest_effect([])


def test_is_enforce_promotion() -> None:
    assert is_enforce_promotion(Effect.AUDIT, Effect.DENY) is True
    assert is_enforce_promotion(Effect.AUDIT, Effect.REMEDIATE) is True
    assert is_enforce_promotion(Effect.DISABLED, Effect.AUDIT) is False
    assert is_enforce_promotion(Effect.DENY, Effect.AUDIT) is False


def test_noop_transition_always_allowed() -> None:
    for e in Effect:
        validate_effect_transition(from_effect=e, to_effect=e)  # no raise


def test_standard_transitions_allowed() -> None:
    validate_effect_transition(from_effect=Effect.DISABLED, to_effect=Effect.AUDIT)
    validate_effect_transition(from_effect=Effect.AUDIT, to_effect=Effect.DISABLED)
    validate_effect_transition(from_effect=Effect.DENY, to_effect=Effect.DISABLED)
    validate_effect_transition(from_effect=Effect.REMEDIATE, to_effect=Effect.DISABLED)


def test_demotion_always_allowed() -> None:
    # deny/remediate -> audit never needs the promotion gate (fail toward safety)
    validate_effect_transition(from_effect=Effect.DENY, to_effect=Effect.AUDIT)
    validate_effect_transition(from_effect=Effect.REMEDIATE, to_effect=Effect.AUDIT)


def test_promotion_requires_approval() -> None:
    for target in (Effect.DENY, Effect.REMEDIATE):
        with pytest.raises(EffectTransitionError, match="enforce-promotion approval"):
            validate_effect_transition(from_effect=Effect.AUDIT, to_effect=target)
        # with approval it is allowed
        validate_effect_transition(
            from_effect=Effect.AUDIT, to_effect=target, promotion_approved=True
        )


def test_disallowed_transitions_rejected() -> None:
    # cannot jump straight from disabled to an enforce effect
    with pytest.raises(EffectTransitionError, match="not allowed"):
        validate_effect_transition(from_effect=Effect.DISABLED, to_effect=Effect.DENY)
    # cannot switch deny <-> remediate directly (must demote to audit first)
    with pytest.raises(EffectTransitionError, match="not allowed"):
        validate_effect_transition(from_effect=Effect.DENY, to_effect=Effect.REMEDIATE)
    with pytest.raises(EffectTransitionError, match="not allowed"):
        validate_effect_transition(from_effect=Effect.REMEDIATE, to_effect=Effect.DENY)
    # cannot go disabled -> remediate directly
    with pytest.raises(EffectTransitionError, match="not allowed"):
        validate_effect_transition(from_effect=Effect.DISABLED, to_effect=Effect.REMEDIATE)


def test_is_enforce_tier() -> None:
    assert is_enforce_tier(Effect.DENY)
    assert is_enforce_tier(Effect.REMEDIATE)
    assert not is_enforce_tier(Effect.AUDIT)
    assert not is_enforce_tier(Effect.DISABLED)


def test_is_enforce_activation() -> None:
    assert is_enforce_activation(Enforcement.DO_NOT_ENFORCE, Enforcement.ENFORCE)
    # not an activation the other way, or when already enforcing / staying shadow
    assert not is_enforce_activation(Enforcement.ENFORCE, Enforcement.DO_NOT_ENFORCE)
    assert not is_enforce_activation(Enforcement.ENFORCE, Enforcement.ENFORCE)
    assert not is_enforce_activation(Enforcement.DO_NOT_ENFORCE, Enforcement.DO_NOT_ENFORCE)

