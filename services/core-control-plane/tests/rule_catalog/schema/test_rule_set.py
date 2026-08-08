"""Governance rule-set: membership, per-rule defaults, assignment derivation."""

from __future__ import annotations

import pytest
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.rule_set import (
    RuleSet,
    RuleSetMember,
    assignment_from_rule_set,
)
from fdai.rule_catalog.schema.scope import ResourceContext, Scope, ScopeLevel


def _baseline() -> RuleSet:
    return RuleSet(
        id="security-baseline",
        version="1.0.0",
        members=(
            RuleSetMember(rule_id="r.encryption", version="1.0.0", default_effect=Effect.DENY),
            RuleSetMember(rule_id="r.backup", version="2.1.0", default_effect=Effect.REMEDIATE),
            RuleSetMember(rule_id="r.tagging", version="1.0.0"),  # default audit
        ),
    )


def test_member_validation() -> None:
    with pytest.raises(ValueError, match="rule_id MUST be non-empty"):
        RuleSetMember(rule_id=" ", version="1.0.0")
    with pytest.raises(ValueError, match="version MUST be non-empty"):
        RuleSetMember(rule_id="r.x", version="")


def test_ruleset_validation() -> None:
    with pytest.raises(ValueError, match="id MUST be non-empty"):
        RuleSet(id=" ", version="1.0.0", members=(RuleSetMember(rule_id="r.x", version="1"),))
    with pytest.raises(ValueError, match="version MUST be non-empty"):
        RuleSet(id="s", version="", members=(RuleSetMember(rule_id="r.x", version="1"),))
    with pytest.raises(ValueError, match="at least one rule"):
        RuleSet(id="s", version="1.0.0", members=())
    with pytest.raises(ValueError, match="duplicate member rule"):
        RuleSet(
            id="s",
            version="1.0.0",
            members=(
                RuleSetMember(rule_id="r.x", version="1"),
                RuleSetMember(rule_id="r.x", version="2"),
            ),
        )


def test_membership_and_lookups() -> None:
    rs = _baseline()
    assert rs.rule_ids() == frozenset({"r.encryption", "r.backup", "r.tagging"})
    assert rs.default_effect_for("r.encryption") is Effect.DENY
    assert rs.default_effect_for("r.tagging") is Effect.AUDIT
    assert rs.version_for("r.backup") == "2.1.0"
    with pytest.raises(KeyError):
        rs.default_effect_for("r.absent")
    with pytest.raises(KeyError):
        rs.version_for("r.absent")


def test_assignment_from_rule_set_carries_defaults() -> None:
    rs = _baseline()
    scope = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    a = assignment_from_rule_set(rs, id="a-baseline", scope=scope)
    assert a.target_rule_ids == rs.rule_ids()
    # per-rule set defaults become the assignment's effect_for(rule)
    assert a.effect_for("r.encryption") is Effect.DENY
    assert a.effect_for("r.backup") is Effect.REMEDIATE
    assert a.effect_for("r.tagging") is Effect.AUDIT
    # the derived assignment stays shadow at the enforcement flag
    assert a.enforcement is Enforcement.DO_NOT_ENFORCE


def test_extra_override_wins_over_set_default() -> None:
    rs = _baseline()
    scope = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    a = assignment_from_rule_set(
        rs, id="a-baseline", scope=scope, extra_overrides={"r.encryption": Effect.AUDIT}
    )
    # assignment-level override relaxes the set's deny to audit for that rule
    assert a.effect_for("r.encryption") is Effect.AUDIT
    # others keep the set default
    assert a.effect_for("r.backup") is Effect.REMEDIATE


def test_derived_assignment_applies_to_members() -> None:
    rs = _baseline()
    scope = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    a = assignment_from_rule_set(rs, id="a-baseline", scope=scope)
    ctx = ResourceContext(
        organization="org-1",
        account="sub-1",
        resource_group="rg-a",
        resource_id="vm-1",
        resource_type="compute",
    )
    assert a.applies_to("r.encryption", ctx)
    assert not a.applies_to("r.not-a-member", ctx)
