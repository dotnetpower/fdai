"""Governance assignment: binding, effect resolution, scope precedence."""

from __future__ import annotations

import pytest

from fdai.rule_catalog.schema.assignment import (
    Assignment,
    resolve_assignments,
)
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.scope import ResourceContext, Scope, ScopeLevel


def _ctx() -> ResourceContext:
    return ResourceContext(
        organization="org-1",
        account="sub-1",
        resource_group="rg-a",
        resource_id="vm-1",
        resource_type="compute",
    )


def _assign(
    *,
    id_: str,
    rules: set[str],
    scope: Scope,
    effect: Effect = Effect.AUDIT,
    enforcement: Enforcement = Enforcement.DO_NOT_ENFORCE,
    parameters: dict[str, str] | None = None,
    effect_overrides: dict[str, Effect] | None = None,
) -> Assignment:
    return Assignment(
        id=id_,
        target_rule_ids=frozenset(rules),
        scope=scope,
        effect=effect,
        enforcement=enforcement,
        parameters=parameters or {},
        effect_overrides=effect_overrides or {},
    )


_ORG = Scope(level=ScopeLevel.ORGANIZATION, id="org-1")
_RG = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
_RES = Scope(level=ScopeLevel.RESOURCE, id="vm-1")


def test_defaults_are_shadow() -> None:
    a = _assign(id_="a1", rules={"r.x"}, scope=_RG)
    assert a.effect is Effect.AUDIT
    assert a.enforcement is Enforcement.DO_NOT_ENFORCE


def test_validation() -> None:
    with pytest.raises(ValueError, match="id MUST be non-empty"):
        _assign(id_=" ", rules={"r.x"}, scope=_RG)
    with pytest.raises(ValueError, match="at least one rule"):
        Assignment(id="a", target_rule_ids=frozenset(), scope=_RG)


def test_applies_to_requires_rule_and_scope() -> None:
    a = _assign(id_="a1", rules={"r.x"}, scope=_RG)
    assert a.applies_to("r.x", _ctx())
    assert not a.applies_to("r.other", _ctx())
    other_rg = _assign(
        id_="a2", rules={"r.x"}, scope=Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-z")
    )
    assert not other_rg.applies_to("r.x", _ctx())


def test_effect_for_override() -> None:
    a = _assign(
        id_="a1",
        rules={"r.x", "r.y"},
        scope=_RG,
        effect=Effect.AUDIT,
        effect_overrides={"r.y": Effect.DENY},
    )
    assert a.effect_for("r.x") is Effect.AUDIT
    assert a.effect_for("r.y") is Effect.DENY


def test_no_match_returns_none() -> None:
    a = _assign(id_="a1", rules={"r.x"}, scope=Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-z"))
    assert resolve_assignments(assignments=[a], ctx=_ctx(), rule_id="r.x") is None
    assert resolve_assignments(assignments=[], ctx=_ctx(), rule_id="r.x") is None


def test_strictest_effect_wins_across_assignments() -> None:
    audit = _assign(id_="a-audit", rules={"r.x"}, scope=_ORG, effect=Effect.AUDIT)
    deny = _assign(id_="a-deny", rules={"r.x"}, scope=_RG, effect=Effect.DENY)
    res = resolve_assignments(assignments=[audit, deny], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.effective_effect is Effect.DENY
    assert "a-audit" in res.overridden_assignment_ids


def test_enforcement_enforce_wins_among_effect_carriers() -> None:
    shadow_deny = _assign(id_="a-shadow", rules={"r.x"}, scope=_RG, effect=Effect.DENY)
    enforce_deny = _assign(
        id_="a-enforce",
        rules={"r.x"},
        scope=_RES,
        effect=Effect.DENY,
        enforcement=Enforcement.ENFORCE,
    )
    res = resolve_assignments(assignments=[shadow_deny, enforce_deny], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.effective_effect is Effect.DENY
    assert res.enforcement is Enforcement.ENFORCE


def test_parameters_from_most_specific_scope() -> None:
    org = _assign(id_="a-org", rules={"r.x"}, scope=_ORG, parameters={"max": "10"})
    res_scope = _assign(id_="a-res", rules={"r.x"}, scope=_RES, parameters={"max": "3"})
    res = resolve_assignments(assignments=[org, res_scope], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.parameters == {"max": "3"}  # resource scope is most specific
    assert res.winning_assignment_id == "a-res"
    assert res.parameter_tie is False


def test_parameter_tie_flags_hil() -> None:
    # two equally-specific (resource-group) scopes disagreeing on parameters
    a = _assign(id_="a1", rules={"r.x"}, scope=_RG, parameters={"max": "10"})
    b = _assign(
        id_="a2",
        rules={"r.x"},
        scope=Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a"),
        parameters={"max": "5"},
    )
    res = resolve_assignments(assignments=[a, b], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.parameter_tie is True


def test_single_assignment_clean_resolution() -> None:
    a = _assign(
        id_="a1",
        rules={"r.x"},
        scope=_RG,
        effect=Effect.REMEDIATE,
        enforcement=Enforcement.ENFORCE,
        parameters={"k": "v"},
    )
    res = resolve_assignments(assignments=[a], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.effective_effect is Effect.REMEDIATE
    assert res.enforcement is Enforcement.ENFORCE
    assert res.parameters == {"k": "v"}
    assert res.overridden_assignment_ids == ()
    assert res.parameter_tie is False


def test_resolver_accepts_scope_binding() -> None:
    # an assignment scoped by a ScopeBinding resolves through the same path,
    # and its most-specific include drives specificity against a Scope org-wide
    from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeRef

    org_wide = _assign(id_="org", rules={"r.x"}, scope=_ORG, parameters={"k": "org"})
    binding = Assignment(
        id="rg-bind",
        target_rule_ids=frozenset({"r.x"}),
        scope=ScopeBinding(includes=(ScopeRef(("org-1", "sub-1", "rg-a")),)),
        parameters={"k": "rg"},
    )
    res = resolve_assignments(assignments=[org_wide, binding], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    # the resource-group binding is more specific than the org-wide scope
    assert res.winning_assignment_id == "rg-bind"
    assert res.parameters == {"k": "rg"}
    assert res.parameter_tie is False


def test_parameters_for_merges_overrides() -> None:
    a = Assignment(
        id="a1",
        target_rule_ids=frozenset({"r.x", "r.y"}),
        scope=_RG,
        parameters={"k": "base", "shared": "s"},
        parameter_overrides={"r.x": {"k": "x-specific"}},
    )
    # per-rule override wins per key; other keys keep the assignment-wide value
    assert a.parameters_for("r.x") == {"k": "x-specific", "shared": "s"}
    # a rule with no override gets the assignment-wide parameters unchanged
    assert a.parameters_for("r.y") == {"k": "base", "shared": "s"}


def test_resolver_returns_per_rule_parameters() -> None:
    a = Assignment(
        id="a1",
        target_rule_ids=frozenset({"r.x"}),
        scope=_RG,
        parameters={"k": "base"},
        parameter_overrides={"r.x": {"k": "x"}},
    )
    res = resolve_assignments(assignments=[a], ctx=_ctx(), rule_id="r.x")
    assert res is not None
    assert res.parameters == {"k": "x"}
