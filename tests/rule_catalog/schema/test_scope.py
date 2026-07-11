"""Governance scope: coverage predicate, selectors, exclusions, specificity."""

from __future__ import annotations

import pytest

from fdai.rule_catalog.schema.scope import (
    ResourceContext,
    Scope,
    ScopeBinding,
    ScopeLevel,
    ScopeRef,
    ScopeSelector,
    most_specific,
    scope_specificity,
)


def _ctx(
    *,
    org: str = "org-1",
    account: str = "sub-1",
    rg: str = "rg-a",
    resource: str = "vm-1",
    rtype: str = "compute",
    tags: dict[str, str] | None = None,
) -> ResourceContext:
    return ResourceContext(
        organization=org,
        account=account,
        resource_group=rg,
        resource_id=resource,
        resource_type=rtype,
        tags=tags or {},
    )


def test_specificity_ordering() -> None:
    assert scope_specificity(Scope(level=ScopeLevel.RESOURCE, id="vm-1")) > scope_specificity(
        Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    )
    assert scope_specificity(Scope(level=ScopeLevel.ACCOUNT, id="sub-1")) > scope_specificity(
        Scope(level=ScopeLevel.ORGANIZATION, id="org-1")
    )


def test_covers_at_each_level() -> None:
    ctx = _ctx()
    assert Scope(level=ScopeLevel.ORGANIZATION, id="org-1").covers(ctx)
    assert Scope(level=ScopeLevel.ACCOUNT, id="sub-1").covers(ctx)
    assert Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a").covers(ctx)
    assert Scope(level=ScopeLevel.RESOURCE, id="vm-1").covers(ctx)


def test_covers_rejects_non_matching_id() -> None:
    ctx = _ctx()
    assert not Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-other").covers(ctx)
    assert not Scope(level=ScopeLevel.ACCOUNT, id="sub-other").covers(ctx)


def test_selector_resource_type() -> None:
    ctx = _ctx(rtype="compute")
    covering = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_types=frozenset({"compute"})),
    )
    assert covering.covers(ctx)
    non = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_types=frozenset({"storage"})),
    )
    assert not non.covers(ctx)


def test_selector_tags_and_ids_are_anded() -> None:
    ctx = _ctx(tags={"env": "prod", "team": "a"})
    # all declared tags must match
    ok = Scope(
        level=ScopeLevel.ACCOUNT,
        id="sub-1",
        selector=ScopeSelector(tags={"env": "prod"}),
    )
    assert ok.covers(ctx)
    bad = Scope(
        level=ScopeLevel.ACCOUNT,
        id="sub-1",
        selector=ScopeSelector(tags={"env": "dev"}),
    )
    assert not bad.covers(ctx)
    # resource-id allowlist
    id_ok = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_ids=frozenset({"vm-1"})),
    )
    assert id_ok.covers(ctx)
    id_bad = Scope(
        level=ScopeLevel.RESOURCE_GROUP,
        id="rg-a",
        selector=ScopeSelector(resource_ids=frozenset({"vm-2"})),
    )
    assert not id_bad.covers(ctx)


def test_empty_selector_matches_everything_in_scope() -> None:
    ctx = _ctx()
    assert Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", selector=ScopeSelector()).covers(ctx)


def test_exclusion_of_child_scope() -> None:
    ctx = _ctx(rg="rg-sandbox")
    # org-wide but exclude a sandbox resource group
    scope = Scope(
        level=ScopeLevel.ORGANIZATION,
        id="org-1",
        excludes=frozenset({"rg-sandbox"}),
    )
    assert not scope.covers(ctx)
    # a resource NOT in the excluded rg is still covered
    assert scope.covers(_ctx(rg="rg-a"))


def test_exclusion_of_specific_resource() -> None:
    scope = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", excludes=frozenset({"vm-1"}))
    assert not scope.covers(_ctx(resource="vm-1"))
    assert scope.covers(_ctx(resource="vm-2"))


def test_most_specific_unique_and_tie() -> None:
    org = Scope(level=ScopeLevel.ORGANIZATION, id="org-1")
    rg = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")
    res = Scope(level=ScopeLevel.RESOURCE, id="vm-1")
    winners = most_specific([org, rg, res])
    assert winners == (res,)  # unique most-specific
    # a genuine tie at the same level surfaces both
    rg2 = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a", selector=ScopeSelector())
    tie = most_specific([org, rg, rg2])
    assert len(tie) == 2 and rg in tie and rg2 in tie
    assert most_specific([]) == ()


def test_scope_id_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="Scope.id MUST be non-empty"):
        Scope(level=ScopeLevel.RESOURCE, id="  ")


# ---- ScopeRef (canonical scope:// URI) ------------------------------------


def test_scope_ref_level_and_id_by_depth() -> None:
    assert ScopeRef(("org-1",)).level is ScopeLevel.ORGANIZATION
    assert ScopeRef(("org-1", "sub-1")).level is ScopeLevel.ACCOUNT
    assert ScopeRef(("org-1", "sub-1", "rg-a")).level is ScopeLevel.RESOURCE_GROUP
    ref = ScopeRef(("org-1", "sub-1", "rg-a", "vm-1"))
    assert ref.level is ScopeLevel.RESOURCE
    assert ref.id == "vm-1"


def test_scope_ref_parse_render_round_trip() -> None:
    uri = "scope://org-1/sub-1/rg-a/vm-1"
    ref = ScopeRef.parse(uri)
    assert ref.segments == ("org-1", "sub-1", "rg-a", "vm-1")
    assert ref.render() == uri


def test_scope_ref_parse_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError, match="MUST start with"):
        ScopeRef.parse("org-1/sub-1")


def test_scope_ref_parse_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="at least one segment"):
        ScopeRef.parse("scope://")


def test_scope_ref_parse_rejects_empty_segment() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ScopeRef.parse("scope://org-1//rg-a")


def test_scope_ref_rejects_too_many_segments() -> None:
    with pytest.raises(ValueError, match="1..4 segments"):
        ScopeRef(("a", "b", "c", "d", "e"))


def test_scope_ref_rejects_zero_segments() -> None:
    with pytest.raises(ValueError, match="1..4 segments"):
        ScopeRef(())


def test_scope_ref_covers_full_chain() -> None:
    ref = ScopeRef(("org-1", "sub-1", "rg-a"))
    assert ref.covers(_ctx(org="org-1", account="sub-1", rg="rg-a", resource="vm-9"))
    # a different account with the same rg id does NOT collide (stricter than Scope)
    assert not ref.covers(_ctx(org="org-1", account="sub-2", rg="rg-a"))


def test_scope_ref_to_scope_bridges_to_level_id() -> None:
    scope = ScopeRef(("org-1", "sub-1", "rg-a")).to_scope()
    assert scope.level is ScopeLevel.RESOURCE_GROUP
    assert scope.id == "rg-a"
    assert scope.covers(_ctx(rg="rg-a"))


# ---- ScopeBinding (include / exclude address lists) -----------------------


def test_scope_binding_requires_an_include() -> None:
    with pytest.raises(ValueError, match="at least one include"):
        ScopeBinding(includes=())


def test_scope_binding_covers_any_include() -> None:
    binding = ScopeBinding(
        includes=(ScopeRef(("org-1", "sub-1", "rg-a")), ScopeRef(("org-1", "sub-2"))),
    )
    assert binding.covers(_ctx(account="sub-1", rg="rg-a"))
    assert binding.covers(_ctx(account="sub-2", rg="rg-z"))  # via the account include
    assert not binding.covers(_ctx(account="sub-3", rg="rg-a"))


def test_scope_binding_exclude_wins() -> None:
    binding = ScopeBinding(
        includes=(ScopeRef(("org-1", "sub-1")),),
        excludes=(ScopeRef(("org-1", "sub-1", "sandbox")),),
    )
    assert binding.covers(_ctx(account="sub-1", rg="rg-a"))
    assert not binding.covers(_ctx(account="sub-1", rg="sandbox"))


def test_scope_binding_selector_narrows() -> None:
    binding = ScopeBinding(
        includes=(ScopeRef(("org-1", "sub-1")),),
        selector=ScopeSelector(resource_types=frozenset({"sql-database"})),
    )
    assert binding.covers(_ctx(account="sub-1", rtype="sql-database"))
    assert not binding.covers(_ctx(account="sub-1", rtype="compute"))


def test_scope_binding_specificity_is_most_specific_include() -> None:
    binding = ScopeBinding(
        includes=(ScopeRef(("org-1",)), ScopeRef(("org-1", "sub-1", "rg-a"))),
    )
    assert binding.specificity == int(ScopeLevel.RESOURCE_GROUP)
