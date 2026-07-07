"""Profile registry + resolve algorithm."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.rule_catalog_profiles import (
    Profile,
    ProfileRegistry,
    ProfileResolutionError,
    ProfileRule,
)
from fdai.core.rule_catalog_profiles.models import ProfileMode, SeverityOverride

REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_PROFILES = REPO_ROOT / "rule-catalog" / "profiles"


# ---------------------------------------------------------------------------
# Model-level validation
# ---------------------------------------------------------------------------


def test_profile_rejects_duplicate_rule_declaration() -> None:
    with pytest.raises(ProfileResolutionError, match="declares rule"):
        Profile(
            id="p",
            title="P",
            rules=(
                ProfileRule(id="r1"),
                ProfileRule(id="r1"),
            ),
        )


def test_registry_rejects_duplicate_profile_id() -> None:
    a = Profile(id="p", title="A", rules=(ProfileRule(id="r"),))
    b = Profile(id="p", title="B", rules=(ProfileRule(id="r"),))
    with pytest.raises(ProfileResolutionError, match="duplicate profile id"):
        ProfileRegistry(profiles=[a, b])


# ---------------------------------------------------------------------------
# Resolve algorithm - simple parent + override
# ---------------------------------------------------------------------------


def test_resolve_simple_extend_chain_inherits_and_overrides() -> None:
    parent = Profile(
        id="parent",
        title="Parent",
        rules=(
            ProfileRule(id="r1", mode=ProfileMode.SHADOW, parameters={"a": 1}),
            ProfileRule(id="r2", mode=ProfileMode.SHADOW),
        ),
    )
    child = Profile(
        id="child",
        title="Child",
        rules=(ProfileRule(id="r1", mode=ProfileMode.ENFORCE, parameters={"a": 2, "b": 3}),),
        extends=("parent",),
    )
    reg = ProfileRegistry(profiles=[parent, child])
    resolved = reg.resolve("child", strict=False)
    assert resolved.id == "child"
    ids = resolved.ids()
    assert set(ids) == {"r1", "r2"}
    r1 = resolved.get("r1")
    assert r1 is not None
    assert r1.mode is ProfileMode.ENFORCE  # child override wins
    assert r1.parameters == {"a": 2, "b": 3}  # child params overlay parent
    r2 = resolved.get("r2")
    assert r2 is not None
    assert r2.mode is ProfileMode.SHADOW  # inherited unchanged


def test_resolve_flattens_ordering_deterministically() -> None:
    """Result is sorted by rule id so a diff between resolutions is byte-stable."""
    profile = Profile(
        id="p",
        title="P",
        rules=(
            ProfileRule(id="zeta"),
            ProfileRule(id="alpha"),
            ProfileRule(id="mu"),
        ),
    )
    reg = ProfileRegistry(profiles=[profile])
    ids = reg.resolve("p", strict=False).ids()
    assert ids == ("alpha", "mu", "zeta")


def test_resolve_disabled_rule_removes_it_from_child() -> None:
    parent = Profile(id="parent", title="P", rules=(ProfileRule(id="r1"),))
    child = Profile(
        id="child",
        title="C",
        rules=(ProfileRule(id="r1", disabled=True),),
        extends=("parent",),
    )
    reg = ProfileRegistry(profiles=[parent, child])
    assert reg.resolve("child", strict=False).ids() == ()


def test_resolve_profile_default_parameters_flow_to_every_rule() -> None:
    profile = Profile(
        id="p",
        title="P",
        rules=(
            ProfileRule(id="r1", parameters={"specific": True}),
            ProfileRule(id="r2"),
        ),
        parameters={"tag.mandatory": ["Environment"]},
    )
    reg = ProfileRegistry(profiles=[profile])
    resolved = reg.resolve("p", strict=False)
    r1 = resolved.get("r1")
    r2 = resolved.get("r2")
    assert r1 is not None and r2 is not None
    assert r1.parameters == {"tag.mandatory": ["Environment"], "specific": True}
    assert r2.parameters == {"tag.mandatory": ["Environment"]}


# ---------------------------------------------------------------------------
# Structural errors - cycle / unknown parent / unknown rule / downgrade
# ---------------------------------------------------------------------------


def test_resolve_rejects_cycle_in_extends() -> None:
    a = Profile(id="a", title="A", rules=(ProfileRule(id="r"),), extends=("b",))
    b = Profile(id="b", title="B", rules=(ProfileRule(id="r"),), extends=("a",))
    reg = ProfileRegistry(profiles=[a, b])
    with pytest.raises(ProfileResolutionError, match="cycle in profile extends"):
        reg.resolve("a", strict=False)


def test_resolve_rejects_unknown_parent() -> None:
    child = Profile(id="child", title="C", rules=(ProfileRule(id="r"),), extends=("ghost",))
    reg = ProfileRegistry(profiles=[child])
    with pytest.raises(ProfileResolutionError, match="unknown parent"):
        reg.resolve("child", strict=False)


def test_resolve_rejects_unknown_rule_id_when_check_enabled() -> None:
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="unknown.rule"),))
    reg = ProfileRegistry(profiles=[profile])
    with pytest.raises(ProfileResolutionError, match="unknown rule id"):
        reg.resolve("p", known_rule_ids=("real.rule",))


def test_resolve_rejects_severity_downgrade_below_floor() -> None:
    profile = Profile(
        id="p",
        title="P",
        rules=(ProfileRule(id="r", severity_override=SeverityOverride.LOW),),
    )
    reg = ProfileRegistry(profiles=[profile])
    with pytest.raises(ProfileResolutionError, match="downgrades below authored floor"):
        reg.resolve("p", rule_severity_floors={"r": SeverityOverride.HIGH}, strict=False)


def test_resolve_accepts_severity_escalation() -> None:
    profile = Profile(
        id="p",
        title="P",
        rules=(ProfileRule(id="r", severity_override=SeverityOverride.CRITICAL),),
    )
    reg = ProfileRegistry(profiles=[profile])
    resolved = reg.resolve("p", rule_severity_floors={"r": SeverityOverride.HIGH}, strict=False)
    r = resolved.get("r")
    assert r is not None
    assert r.severity_override is SeverityOverride.CRITICAL


# ---------------------------------------------------------------------------
# Loader - actual upstream profiles + overlay behavior
# ---------------------------------------------------------------------------


def test_load_upstream_ships_baseline_recommended_strict() -> None:
    reg = ProfileRegistry.from_directories(upstream=UPSTREAM_PROFILES)
    ids = {p.id for p in reg.all()}
    assert {"baseline", "recommended", "strict"}.issubset(ids)


def test_load_upstream_baseline_resolves_to_expected_size() -> None:
    reg = ProfileRegistry.from_directories(upstream=UPSTREAM_PROFILES)
    baseline = reg.resolve("baseline", strict=False)
    # Rough size check - baseline is intentionally small so a new fork can adopt it.
    assert 5 <= len(baseline.rules) <= 20


def test_load_upstream_strict_extends_recommended_extends_baseline() -> None:
    reg = ProfileRegistry.from_directories(upstream=UPSTREAM_PROFILES)
    strict = reg.resolve("strict", strict=False)
    baseline = reg.resolve("baseline", strict=False)
    recommended = reg.resolve("recommended", strict=False)
    # Every baseline rule id must appear in recommended and strict.
    assert set(baseline.ids()).issubset(set(recommended.ids()))
    assert set(recommended.ids()).issubset(set(strict.ids()))
    # Strict is strictly larger.
    assert len(strict.rules) > len(recommended.rules) or _has_enforce(strict) > _has_enforce(
        recommended
    )


def test_load_overlay_directory_wins_on_id_collision(tmp_path: Path) -> None:
    """Fork overlay replaces an upstream profile with the same id."""
    overlay_dir = tmp_path / "profiles-overrides"
    overlay_dir.mkdir()
    (overlay_dir / "baseline.yaml").write_text(
        """
schema_version: "1.0.0"
id: baseline
title: (Fork) Custom baseline
rules:
  - id: object-storage.public-access.deny
    mode: enforce
""",
        encoding="utf-8",
    )
    reg = ProfileRegistry.from_directories(
        upstream=UPSTREAM_PROFILES,
        overlays=[overlay_dir],
    )
    baseline = reg.get("baseline")
    assert baseline is not None
    assert baseline.title == "(Fork) Custom baseline"


def test_loader_rejects_schema_violation(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        """
schema_version: "1.0.0"
id: bad
title: Bad
rules:
  - id: r
    mode: invalid_mode_value
""",
        encoding="utf-8",
    )
    with pytest.raises(ProfileResolutionError):
        ProfileRegistry.from_directories(upstream=tmp_path)


def _has_enforce(resolved) -> int:  # noqa: ANN001
    return sum(1 for r in resolved.rules if r.mode is ProfileMode.ENFORCE)


# ---------------------------------------------------------------------------
# Fail-closed default: `strict=True` (default) requires `known_rule_ids`
# ---------------------------------------------------------------------------


def test_resolve_default_strict_raises_when_known_rule_ids_missing() -> None:
    """Regression: the previous implementation silently accepted unknown
    rule ids when `known_rule_ids` was omitted; the safety-invariant
    rewrite of `resolve` forces the caller to supply the catalog's rule
    ids so a bad profile fails at load, not as a silent runtime abstain."""
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="unknown.rule"),))
    reg = ProfileRegistry(profiles=[profile])
    with pytest.raises(ProfileResolutionError, match="requires `known_rule_ids`"):
        reg.resolve("p")  # strict defaults to True; no known_rule_ids -> raise


def test_resolve_strict_true_with_known_rule_ids_still_validates() -> None:
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="known.rule"),))
    reg = ProfileRegistry(profiles=[profile])
    resolved = reg.resolve("p", known_rule_ids=("known.rule",))
    assert resolved.ids() == ("known.rule",)


def test_resolve_strict_false_explicitly_bypasses_check() -> None:
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="unknown.rule"),))
    reg = ProfileRegistry(profiles=[profile])
    # Authoring / preview tools MAY opt in explicitly.
    resolved = reg.resolve("p", strict=False)
    assert resolved.ids() == ("unknown.rule",)


# ---------------------------------------------------------------------------
# Overlay bookkeeping: forks that shadow an upstream id are reported
# ---------------------------------------------------------------------------


def test_overlay_replacements_is_empty_without_overlays() -> None:
    reg = ProfileRegistry.from_directories(upstream=UPSTREAM_PROFILES)
    assert reg.overlay_replacements() == ()


def test_overlay_replacements_reports_shadowed_upstream_ids(tmp_path: Path) -> None:
    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir()
    (overlay_dir / "baseline.yaml").write_text(
        """
schema_version: "1.0.0"
id: baseline
title: (Fork) Shadowed baseline
rules:
  - id: object-storage.public-access.deny
    mode: enforce
""",
        encoding="utf-8",
    )
    reg = ProfileRegistry.from_directories(
        upstream=UPSTREAM_PROFILES,
        overlays=[overlay_dir],
    )
    reports = reg.overlay_replacements()
    assert len(reports) == 1
    prof_id, path_str, title = reports[0]
    assert prof_id == "baseline"
    assert "baseline.yaml" in path_str
    assert title == "(Fork) Shadowed baseline"


def test_from_directories_skips_hidden_files(tmp_path: Path) -> None:
    """Editor swap files / `.git` remnants must never be loaded."""
    (tmp_path / ".not-a-profile.yaml").write_text(
        "schema_version: '1.0.0'\nid: hidden\ntitle: X\nrules: []\n",
        encoding="utf-8",
    )
    reg = ProfileRegistry.from_directories(upstream=tmp_path)
    assert reg.get("hidden") is None
    assert reg.all() == ()
