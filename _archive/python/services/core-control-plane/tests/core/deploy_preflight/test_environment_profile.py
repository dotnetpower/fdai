"""Wave P.4 - DeploymentEnvironmentProfile cache."""

from __future__ import annotations

import pytest
from fdai.core.deploy_preflight import (
    DeploymentEnvironmentProfile,
    DeploymentEnvironmentProfileCache,
    apply_inventory_delta,
    build_profile,
)

# ---------------------------------------------------------------------------
# Profile dataclass invariants
# ---------------------------------------------------------------------------


def test_build_profile_sorts_and_dedupes_rule_ids() -> None:
    p = build_profile(
        scope="rg/example",
        rule_ids=["r-2", "r-1", "r-2"],
        resource_type_counts={"compute.vm": 3},
        captured_at="2026-07-07T00:00:00Z",
    )
    assert p.rule_ids == ("r-1", "r-2")


def test_direct_construction_rejects_unsorted_rule_ids() -> None:
    with pytest.raises(ValueError, match="sorted"):
        DeploymentEnvironmentProfile(
            scope="s",
            rule_ids=("r-2", "r-1"),
            resource_type_counts={},
            captured_at="t",
        )


def test_empty_scope_rejected() -> None:
    with pytest.raises(ValueError, match="scope"):
        build_profile(
            scope="",
            rule_ids=(),
            resource_type_counts={},
            captured_at="t",
        )


def test_empty_captured_at_rejected() -> None:
    with pytest.raises(ValueError, match="captured_at"):
        build_profile(
            scope="s",
            rule_ids=(),
            resource_type_counts={},
            captured_at="",
        )


def test_negative_resource_type_count_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        build_profile(
            scope="s",
            rule_ids=(),
            resource_type_counts={"compute.vm": -1},
            captured_at="t",
        )


def test_profile_serialization() -> None:
    p = build_profile(
        scope="rg/example",
        rule_ids=["r-1"],
        resource_type_counts={"compute.vm": 2},
        captured_at="2026-07-07T00:00:00Z",
        metadata={"tenant": "example"},
    )
    got = p.to_dict()
    assert got["scope"] == "rg/example"
    assert got["rule_ids"] == ["r-1"]
    assert got["resource_type_counts"] == {"compute.vm": 2}
    assert got["metadata"] == {"tenant": "example"}


def test_with_rule_ids_returns_a_fresh_profile() -> None:
    p = build_profile(
        scope="s",
        rule_ids=("r-1",),
        resource_type_counts={"vm": 1},
        captured_at="t-1",
    )
    p2 = p.with_rule_ids(["r-2", "r-1"], captured_at="t-2")
    assert p2.rule_ids == ("r-1", "r-2")
    assert p2.captured_at == "t-2"
    # Original untouched (frozen dataclass).
    assert p.rule_ids == ("r-1",)


def test_two_profiles_from_same_inputs_are_equal() -> None:
    a = build_profile(
        scope="s",
        rule_ids=("r-1", "r-2"),
        resource_type_counts={"vm": 1},
        captured_at="t",
    )
    b = build_profile(
        scope="s",
        rule_ids=("r-2", "r-1"),  # unordered input
        resource_type_counts={"vm": 1},
        captured_at="t",
    )
    assert a == b


# ---------------------------------------------------------------------------
# Cache write / read
# ---------------------------------------------------------------------------


def _profile(scope: str, captured_at: str = "2026-07-07T00:00:00Z") -> DeploymentEnvironmentProfile:
    return build_profile(
        scope=scope,
        rule_ids=("r-1",),
        resource_type_counts={"vm": 1},
        captured_at=captured_at,
    )


def test_cache_upsert_and_get() -> None:
    cache = DeploymentEnvironmentProfileCache()
    p = _profile("s")
    cache.upsert(p)
    assert cache.get("s") == p


def test_cache_upsert_replaces_prior_entry() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s", captured_at="t-1"))
    cache.upsert(_profile("s", captured_at="t-2"))
    got = cache.get("s")
    assert got is not None
    assert got.captured_at == "t-2"


def test_cache_missing_key_returns_none() -> None:
    cache = DeploymentEnvironmentProfileCache()
    assert cache.get("missing") is None


def test_cache_invalidate_drops_only_matching_scope() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s-1"))
    cache.upsert(_profile("s-2"))
    assert cache.invalidate("s-1") is True
    assert cache.get("s-1") is None
    assert cache.get("s-2") is not None
    # Repeat is a no-op.
    assert cache.invalidate("s-1") is False


def test_cache_clear_drops_everything() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s-1"))
    cache.upsert(_profile("s-2"))
    cache.clear()
    assert len(cache) == 0
    assert cache.scopes() == ()


def test_cache_scopes_are_sorted() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("z"))
    cache.upsert(_profile("a"))
    cache.upsert(_profile("m"))
    assert cache.scopes() == ("a", "m", "z")


# ---------------------------------------------------------------------------
# get_fresh (TTL)
# ---------------------------------------------------------------------------


def test_get_fresh_returns_entry_when_within_ttl() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s", captured_at="2026-07-07T00:00:00Z"))
    got = cache.get_fresh(
        "s",
        now="2026-07-07T00:00:30Z",
        max_age_seconds=60,
    )
    assert got is not None


def test_get_fresh_returns_none_when_stale() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s", captured_at="2026-07-07T00:00:00Z"))
    got = cache.get_fresh(
        "s",
        now="2026-07-07T01:00:00Z",
        max_age_seconds=60,
    )
    assert got is None


def test_get_fresh_returns_none_when_missing() -> None:
    cache = DeploymentEnvironmentProfileCache()
    got = cache.get_fresh("missing", now="2026-07-07T00:00:00Z", max_age_seconds=60)
    assert got is None


def test_get_fresh_returns_none_when_timestamp_unparseable() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(
        build_profile(
            scope="s",
            rule_ids=(),
            resource_type_counts={},
            captured_at="not-a-timestamp",
        )
    )
    got = cache.get_fresh("s", now="2026-07-07T00:00:00Z", max_age_seconds=60)
    assert got is None


def test_get_fresh_returns_none_on_mixed_naive_aware_timestamps() -> None:
    # An aware captured_at compared against a naive 'now' makes the delta
    # subtraction raise TypeError (offset-naive minus offset-aware); both
    # shapes are within the documented ISO domain, so get_fresh MUST fail
    # closed to a re-probe (None) rather than propagate the error.
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s", captured_at="2026-07-07T00:00:00Z"))  # aware
    got = cache.get_fresh("s", now="2026-07-07T00:00:30", max_age_seconds=60)  # naive
    assert got is None


def test_get_fresh_rejects_negative_ttl() -> None:
    cache = DeploymentEnvironmentProfileCache()
    with pytest.raises(ValueError, match="non-negative"):
        cache.get_fresh("s", now="t", max_age_seconds=-1)


# ---------------------------------------------------------------------------
# apply_inventory_delta refresh helper
# ---------------------------------------------------------------------------


def test_apply_inventory_delta_invalidates_matching_scopes() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s-1"))
    cache.upsert(_profile("s-2"))
    cache.upsert(_profile("s-3"))

    dropped = apply_inventory_delta(cache, changed_scopes=["s-1", "s-3", "s-missing"])
    assert dropped == 2  # s-missing was not present
    assert cache.get("s-1") is None
    assert cache.get("s-2") is not None
    assert cache.get("s-3") is None


def test_apply_inventory_delta_empty_is_noop() -> None:
    cache = DeploymentEnvironmentProfileCache()
    cache.upsert(_profile("s-1"))
    assert apply_inventory_delta(cache, changed_scopes=()) == 0
    assert cache.get("s-1") is not None
