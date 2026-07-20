from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceStoreConfig,
    _refresh_from_row,
    _refresh_values,
    _source_from_row,
    _source_values,
)

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _source() -> SkillSource:
    return SkillSource(
        source_id="operations-skills",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example-org/skills",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills/example",
        authentication_audience_ref="github-app:reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3600,
        enabled=True,
    )


def test_source_row_codec_round_trips() -> None:
    columns = (
        "source_id kind location trust_tier owner allowed_path authentication_audience_ref "
        "refresh_policy refresh_interval_seconds enabled"
    ).split()
    source = _source()

    assert _source_from_row(dict(zip(columns, _source_values(source), strict=True))) == source


def test_refresh_state_row_codec_round_trips() -> None:
    columns = (
        "source_id last_refresh_at next_refresh_at last_etag last_revision error_count "
        "retry_at last_error_kind"
    ).split()
    state = SkillSourceRefreshState(
        source_id="operations-skills",
        last_refresh_at=NOW,
        next_refresh_at=NOW + timedelta(hours=1),
        last_etag='"etag-1"',
        last_revision="a" * 40,
        error_count=2,
        retry_at=NOW + timedelta(minutes=5),
        last_error_kind="rate_limited",
    )

    assert _refresh_from_row(dict(zip(columns, _refresh_values(state), strict=True))) == state


def test_config_and_refresh_state_validation() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresSkillSourceStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timezone"):
        SkillSourceRefreshState(
            source_id="operations-skills",
            last_refresh_at=datetime(2026, 7, 20, 22, 0),
        )
