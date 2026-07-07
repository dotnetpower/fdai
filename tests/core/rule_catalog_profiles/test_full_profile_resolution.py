"""End-to-end profile resolution across the whole shipped catalog.

This test complements
``tests/rule_catalog/pipeline/test_full_catalog_validation.py`` (which
checks that every YAML file is schema-valid and every rule id is
unique) by proving the *combined* invariant:

    every profile in ``rule-catalog/profiles/`` MUST resolve
    (``strict=True``) against the ids in
    ``rule-catalog/{catalog,collected}/**`` with no dangling
    references and no cycles in the ``extends`` graph.

Without this test a fork could ship a profile that lists a rule id
which no longer exists (or was never imported), and the failure would
only surface at runtime the first time an operator loaded that
profile. This test drags that failure to CI.

The test is O(profiles + rules) - measured ~2 s on the current
catalog (265 profiles, ~8500 rules).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.core.rule_catalog_profiles import (
    ProfileRegistry,
    ProfileResolutionError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = REPO_ROOT / "rule-catalog" / "profiles"
CATALOG_DIRS = [
    REPO_ROOT / "rule-catalog" / "catalog",
    REPO_ROOT / "rule-catalog" / "collected",
]


@pytest.fixture(scope="module")
def known_rule_ids() -> frozenset[str]:
    """The union of every rule id shipped in this repo (catalog + collected)."""
    ids: set[str] = set()
    for root in CATALOG_DIRS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "id" in data:
                ids.add(str(data["id"]))
    assert len(ids) >= 1000, f"expected thousands of rule ids; got {len(ids)}"
    return frozenset(ids)


@pytest.fixture(scope="module")
def registry() -> ProfileRegistry:
    return ProfileRegistry.from_directories(upstream=PROFILES_DIR)


def test_every_shipped_profile_resolves_strict(
    registry: ProfileRegistry,
    known_rule_ids: frozenset[str],
) -> None:
    """Every profile MUST resolve with strict=True.

    Failures are collected and reported together so a maintainer sees
    every broken profile at once, not one-by-one across CI runs.
    """
    failures: list[str] = []
    checked = 0
    for profile in registry.all():
        try:
            registry.resolve(profile.id, known_rule_ids=known_rule_ids)
        except ProfileResolutionError as exc:
            failures.append(f"{profile.id}: {exc}")
            if len(failures) >= 20:
                failures.append(f"... (stopped after {len(failures)} failures)")
                break
        checked += 1
    assert not failures, f"{len(failures)} profile(s) failed to resolve strict:\n" + "\n".join(
        failures
    )
    assert checked >= 100, f"expected 100+ profiles; only walked {checked}"


def test_every_extends_reference_points_to_a_known_profile(
    registry: ProfileRegistry,
) -> None:
    """`extends` is resolved lazily inside `resolve`; this test locks
    the invariant separately so a profile with a bad ``extends`` fails
    even before any caller asks for a resolution."""
    known = {p.id for p in registry.all()}
    missing: list[str] = []
    for profile in registry.all():
        for parent in profile.extends:
            if parent not in known:
                missing.append(f"{profile.id} extends unknown profile {parent!r}")
    assert not missing, "dangling profile extends:\n" + "\n".join(missing)
