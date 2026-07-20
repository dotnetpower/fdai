from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceRegistry,
    SkillSourceTrustTier,
)


def _source() -> SkillSource:
    return SkillSource(
        source_id="operations-skills",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example-org/operations-skills",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills/approved",
        authentication_audience_ref="github-app:skills-reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3600,
    )


def test_source_registration_is_explicit_and_disabled_first() -> None:
    registry = SkillSourceRegistry().register(_source())

    assert registry.get("operations-skills").enabled is False
    assert registry.enable("operations-skills").get("operations-skills").enabled is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("location", "https://example.com/archive.zip"),
        ("allowed_path", "../skills"),
        ("allowed_path", "/skills"),
        ("allowed_path", "skills\\unsafe"),
    ),
)
def test_source_rejects_arbitrary_urls_and_unsafe_paths(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        replace(_source(), **{field: value})
