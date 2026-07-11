"""ChangeEvidenceGatherer - RCA change-correlation evidence (P1-5 PR-A).

Proves the wiring the issue asks for:

- A synthetic deploy shortly before an incident surfaces as a CHANGE
  citation with a non-zero correlation score.
- A deploy far outside the window does NOT surface (cannot be a cause).
- No feed binding / a feed outage yields no citations (fail-safe abstain),
  never a raise.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.rca.change_evidence import ChangeEvidenceGatherer
from fdai.core.rca.contract import CitationKind
from fdai.shared.providers.change_feed import (
    ChangeFeedError,
    ChangeRecord,
)

_INCIDENT_AT = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)


class _StaticFeed:
    def __init__(self, changes: Sequence[ChangeRecord]) -> None:
        self._changes = tuple(changes)
        self.calls: list[tuple[datetime, datetime, str | None]] = []

    async def recent(
        self, *, since: datetime, until: datetime, resource_hint: str | None = None
    ) -> Sequence[ChangeRecord]:
        self.calls.append((since, until, resource_hint))
        return self._changes


class _ErrorFeed:
    async def recent(
        self, *, since: datetime, until: datetime, resource_hint: str | None = None
    ) -> Sequence[ChangeRecord]:
        raise ChangeFeedError("upstream down")


def _deploy(change_id: str, at: datetime, hints: tuple[str, ...] = ()) -> ChangeRecord:
    return ChangeRecord(
        change_id=change_id,
        at=at,
        source="github",
        ref="abc123",
        summary="deploy to prod",
        resource_hints=hints,
    )


@pytest.mark.asyncio
async def test_recent_deploy_surfaces_as_change_citation() -> None:
    feed = _StaticFeed([_deploy("gh-1", _INCIDENT_AT - timedelta(minutes=5))])
    gatherer = ChangeEvidenceGatherer(feed=feed, window=timedelta(hours=1))

    citations = await gatherer.gather(incident_at=_INCIDENT_AT)

    assert len(citations) == 1
    assert citations[0].kind is CitationKind.CHANGE
    assert citations[0].ref == "change:gh-1"
    # queried the window [incident - 1h, incident]
    since, until, _ = feed.calls[0]
    assert until == _INCIDENT_AT
    assert since == _INCIDENT_AT - timedelta(hours=1)


@pytest.mark.asyncio
async def test_recent_deploy_has_non_zero_score() -> None:
    feed = _StaticFeed([_deploy("gh-1", _INCIDENT_AT - timedelta(minutes=5))])
    gatherer = ChangeEvidenceGatherer(feed=feed, window=timedelta(hours=1))

    correlations = await gatherer.gather_correlations(incident_at=_INCIDENT_AT)

    assert len(correlations) == 1
    assert correlations[0].score > 0.0


@pytest.mark.asyncio
async def test_deploy_outside_window_does_not_surface() -> None:
    # 3h before, window is 1h -> cannot be a cause.
    feed = _StaticFeed([_deploy("gh-old", _INCIDENT_AT - timedelta(hours=3))])
    gatherer = ChangeEvidenceGatherer(feed=feed, window=timedelta(hours=1))

    citations = await gatherer.gather(incident_at=_INCIDENT_AT)

    assert citations == ()


@pytest.mark.asyncio
async def test_deploy_after_incident_does_not_surface() -> None:
    feed = _StaticFeed([_deploy("gh-after", _INCIDENT_AT + timedelta(minutes=5))])
    gatherer = ChangeEvidenceGatherer(feed=feed, window=timedelta(hours=1))

    citations = await gatherer.gather(incident_at=_INCIDENT_AT)

    assert citations == ()


@pytest.mark.asyncio
async def test_resource_overlap_ranks_higher() -> None:
    feed = _StaticFeed(
        [
            _deploy("gh-overlap", _INCIDENT_AT - timedelta(minutes=30), hints=("vm-a",)),
            _deploy("gh-plain", _INCIDENT_AT - timedelta(minutes=20)),
        ]
    )
    gatherer = ChangeEvidenceGatherer(feed=feed, window=timedelta(hours=1))

    correlations = await gatherer.gather_correlations(
        incident_at=_INCIDENT_AT, incident_resources=("vm-a",)
    )

    # overlap change wins despite being slightly older
    assert correlations[0].change.change_id == "gh-overlap"
    assert correlations[0].resource_overlap == ("vm-a",)


@pytest.mark.asyncio
async def test_min_score_filters_weak_correlations() -> None:
    feed = _StaticFeed(
        [_deploy("gh-weak", _INCIDENT_AT - timedelta(minutes=59))]  # near window edge
    )
    gatherer = ChangeEvidenceGatherer(
        feed=feed, window=timedelta(hours=1), min_score=0.5
    )

    citations = await gatherer.gather(incident_at=_INCIDENT_AT)

    assert citations == ()


@pytest.mark.asyncio
async def test_max_citations_caps_output() -> None:
    changes = [
        _deploy(f"gh-{i}", _INCIDENT_AT - timedelta(minutes=i + 1)) for i in range(10)
    ]
    feed = _StaticFeed(changes)
    gatherer = ChangeEvidenceGatherer(
        feed=feed, window=timedelta(hours=1), max_citations=3
    )

    citations = await gatherer.gather(incident_at=_INCIDENT_AT)

    assert len(citations) == 3


@pytest.mark.asyncio
async def test_no_feed_binding_yields_no_citations() -> None:
    gatherer = ChangeEvidenceGatherer(feed=None)
    citations = await gatherer.gather(incident_at=_INCIDENT_AT)
    assert citations == ()


@pytest.mark.asyncio
async def test_feed_outage_is_fail_safe() -> None:
    gatherer = ChangeEvidenceGatherer(feed=_ErrorFeed())
    citations = await gatherer.gather(incident_at=_INCIDENT_AT)
    assert citations == ()
    correlations = await gatherer.gather_correlations(incident_at=_INCIDENT_AT)
    assert correlations == ()


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        ChangeEvidenceGatherer(window=timedelta(0))
    with pytest.raises(ValueError):
        ChangeEvidenceGatherer(min_score=1.5)
    with pytest.raises(ValueError):
        ChangeEvidenceGatherer(max_citations=0)
