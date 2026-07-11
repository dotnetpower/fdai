"""Cross-cutting invariants for the governance schema (hardening round 3).

Explicit invariant sweeps (no external property-testing dependency) that lock
the behaviour of the hardened scope / assignment / transition primitives so a
regression is caught early.
"""

from __future__ import annotations

import itertools

from fdai.rule_catalog.schema.assignment import Assignment, resolve_assignments
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.governance_catalog import GovernanceCatalog
from fdai.rule_catalog.schema.governance_transitions import validate_catalog_transition
from fdai.rule_catalog.schema.rule_set import RuleSet, RuleSetMember, assignment_from_rule_set
from fdai.rule_catalog.schema.scope import (
    ResourceContext,
    Scope,
    ScopeBinding,
    ScopeLevel,
    ScopeRef,
)

_SEGMENTS = ("org-1", "sub-1", "rg-a", "vm-1")


def _ctx(**over: str) -> ResourceContext:
    base = {
        "organization": "org-1",
        "account": "sub-1",
        "resource_group": "rg-a",
        "resource_id": "vm-1",
        "resource_type": "compute",
    }
    base.update(over)
    return ResourceContext(**base)  # type: ignore[arg-type]


# ---- ScopeRef invariants --------------------------------------------------


def test_scope_ref_parse_render_round_trip_all_depths() -> None:
    for depth in range(1, len(ScopeLevel) + 1):
        ref = ScopeRef(_SEGMENTS[:depth])
        assert ScopeRef.parse(ref.render()) == ref
        assert ref.level is ScopeLevel(depth - 1)


def test_scope_ref_covers_is_monotonic_up_the_chain() -> None:
    # an ancestor address covers every resource its descendant address covers
    descendant = ScopeRef(("org-1", "sub-1", "rg-a"))
    ancestor = ScopeRef(("org-1", "sub-1"))
    contexts = [
        _ctx(),
        _ctx(resource_group="rg-b"),
        _ctx(account="sub-2"),
        _ctx(organization="org-2"),
    ]
    for ctx in contexts:
        if descendant.covers(ctx):
            assert ancestor.covers(ctx)
    # and the ancestor is genuinely broader (covers something the child does not)
    assert ancestor.covers(_ctx(resource_group="rg-z"))
    assert not descendant.covers(_ctx(resource_group="rg-z"))


def test_single_include_binding_matches_scope_ref() -> None:
    ref = ScopeRef(("org-1", "sub-1"))
    binding = ScopeBinding(includes=(ref,))
    for ctx in (_ctx(), _ctx(account="sub-2"), _ctx(organization="org-9")):
        assert binding.covers(ctx) == ref.covers(ctx)


# ---- resolve_assignments invariants ---------------------------------------


def _cover_all() -> Scope:
    return Scope(level=ScopeLevel.ORGANIZATION, id="org-1")


def test_effective_effect_is_order_independent() -> None:
    # strictest effect wins regardless of assignment ordering
    a_audit = Assignment(id="a", target_rule_ids=frozenset({"r"}), scope=_cover_all())
    a_deny = Assignment(
        id="b", target_rule_ids=frozenset({"r"}), scope=_cover_all(), effect=Effect.DENY
    )
    a_rem = Assignment(
        id="c", target_rule_ids=frozenset({"r"}), scope=_cover_all(), effect=Effect.REMEDIATE
    )
    trio = [a_audit, a_deny, a_rem]
    effects = set()
    for perm in itertools.permutations(trio):
        res = resolve_assignments(assignments=list(perm), ctx=_ctx(), rule_id="r")
        assert res is not None
        effects.add(res.effective_effect)
    assert effects == {Effect.DENY}  # deny is strictest, always wins


def test_enforcement_never_enforces_without_a_carrier() -> None:
    # shadow safety: enforce only when an assignment carrying the winning effect
    # is itself enforcing
    shadow_deny = Assignment(
        id="a",
        target_rule_ids=frozenset({"r"}),
        scope=_cover_all(),
        effect=Effect.DENY,
        enforcement=Enforcement.DO_NOT_ENFORCE,
    )
    res = resolve_assignments(assignments=[shadow_deny], ctx=_ctx(), rule_id="r")
    assert res is not None
    assert res.enforcement is Enforcement.DO_NOT_ENFORCE


def test_parameter_tie_implies_conflicting_sources() -> None:
    a = Assignment(
        id="a", target_rule_ids=frozenset({"r"}), scope=_cover_all(), parameters={"k": "1"}
    )
    b = Assignment(
        id="b", target_rule_ids=frozenset({"r"}), scope=_cover_all(), parameters={"k": "2"}
    )
    res = resolve_assignments(assignments=[a, b], ctx=_ctx(), rule_id="r")
    assert res is not None
    assert res.parameter_tie is True  # same specificity, different params


# ---- transition invariants over rule-set-bound assignments ----------------


def test_rule_set_binding_enforce_default_needs_promotion() -> None:
    # a new rule-set-bound assignment whose member defaults to deny must be
    # approved as a promotion (validated across the expanded per-rule effects)
    rs = RuleSet(
        id="rs",
        version="1.0.0",
        members=(RuleSetMember(rule_id="r.deny", version="1.0.0", default_effect=Effect.DENY),),
    )
    binding = assignment_from_rule_set(
        rs, id="a", scope=ScopeBinding(includes=(ScopeRef(("org-1",)),))
    )
    curr = GovernanceCatalog(assignments=(binding,))
    issues = validate_catalog_transition(previous=GovernanceCatalog(), current=curr)
    assert any(i.rule_id == "r.deny" for i in issues)
    ok = validate_catalog_transition(
        previous=GovernanceCatalog(), current=curr, promotions_approved=frozenset({"a"})
    )
    assert ok == []


# ---- enforcement-activation invariants ------------------------------------


def _one(effect: Effect, enf: Enforcement) -> GovernanceCatalog:
    return GovernanceCatalog(
        assignments=(
            Assignment(
                id="a",
                target_rule_ids=frozenset({"r"}),
                scope=_cover_all(),
                effect=effect,
                enforcement=enf,
            ),
        )
    )


def test_enforce_activation_always_gated_for_enforce_tier() -> None:
    # for every enforce-tier effect, activating enforcement without approval is
    # always flagged, and approval always clears it
    for effect in (Effect.DENY, Effect.REMEDIATE):
        prev = _one(effect, Enforcement.DO_NOT_ENFORCE)
        curr = _one(effect, Enforcement.ENFORCE)
        flagged = validate_catalog_transition(previous=prev, current=curr)
        assert any(i.rule_id == "*" for i in flagged)
        cleared = validate_catalog_transition(
            previous=prev, current=curr, promotions_approved=frozenset({"a"})
        )
        assert cleared == []


def test_enforce_activation_never_gated_for_inert_effects() -> None:
    # audit / disabled never act, so an enforcement flip is orthogonal + ungated
    for effect in (Effect.AUDIT, Effect.DISABLED):
        prev = _one(effect, Enforcement.DO_NOT_ENFORCE)
        curr = _one(effect, Enforcement.ENFORCE)
        assert validate_catalog_transition(previous=prev, current=curr) == []


def test_strictest_effect_is_order_and_duplicate_independent() -> None:
    from fdai.rule_catalog.schema.effect import strictest_effect

    pool = [Effect.DISABLED, Effect.AUDIT, Effect.REMEDIATE, Effect.DENY, Effect.DENY]
    for perm in itertools.permutations(pool[:4]):
        assert strictest_effect(list(perm)) is Effect.DENY
    assert strictest_effect([Effect.AUDIT, Effect.AUDIT]) is Effect.AUDIT
