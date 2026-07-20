from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState
from fdai.core.supply_chain.skill_source_pipeline import SkillSourceRefreshResult
from fdai.core.supply_chain.skill_source_refresh import SkillSourceRefreshOrchestrator
from fdai.shared.providers.skill_source import SkillSourceRateLimitError

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


class Sources:
    async def list(self, *, enabled_only: bool = False):  # type: ignore[no-untyped-def]
        assert enabled_only is True
        return (_source(),)


class States:
    def __init__(self, state: SkillSourceRefreshState | None = None) -> None:
        self.state = state

    async def get(self, _source_id: str) -> SkillSourceRefreshState | None:
        return self.state

    async def put(self, state: SkillSourceRefreshState) -> SkillSourceRefreshState:
        self.state = state
        return state

    async def claim(
        self, *, source_id: str, now: datetime, hold_until: datetime
    ) -> SkillSourceRefreshState | None:
        current = self.state
        due = current is None or (
            current.retry_at <= now
            if current.retry_at is not None
            else current.next_refresh_at is None or current.next_refresh_at <= now
        )
        if not due:
            return None
        self.state = SkillSourceRefreshState(
            source_id=source_id,
            last_refresh_at=current.last_refresh_at if current is not None else None,
            next_refresh_at=hold_until,
            last_etag=current.last_etag if current is not None else None,
            last_revision=current.last_revision if current is not None else None,
            error_count=current.error_count if current is not None else 0,
            retry_at=None,
            last_error_kind=current.last_error_kind if current is not None else None,
        )
        return self.state


class Refresher:
    def __init__(self, result: SkillSourceRefreshResult | Exception) -> None:
        self.result = result
        self.etags: list[str | None] = []

    async def refresh(self, _source, _adapter, **kwargs):  # type: ignore[no-untyped-def]
        self.etags.append(kwargs.get("prior_etag"))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _orchestrator(states: States, refresher: Refresher) -> SkillSourceRefreshOrchestrator:
    return SkillSourceRefreshOrchestrator(
        sources=Sources(),  # type: ignore[arg-type]
        states=states,
        refresher=refresher,
        adapter_factory=lambda _source: object(),  # type: ignore[arg-type,return-value]
    )


async def test_not_modified_reuses_etag_and_schedules_next_interval() -> None:
    states = States(
        SkillSourceRefreshState(
            source_id="operations-skills",
            last_etag='"v1"',
            next_refresh_at=NOW,
        )
    )
    refresher = Refresher(SkillSourceRefreshResult(None, None, '"v1"', not_modified=True))

    attempts = await _orchestrator(states, refresher).run_due(now=NOW)

    assert attempts[0].status == "not_modified"
    assert refresher.etags == ['"v1"']
    assert states.state is not None
    assert states.state.last_etag == '"v1"'
    assert states.state.next_refresh_at == NOW + timedelta(hours=1)
    assert states.state.error_count == 0


async def test_future_refresh_is_not_run() -> None:
    states = States(
        SkillSourceRefreshState(
            source_id="operations-skills",
            next_refresh_at=NOW + timedelta(minutes=1),
        )
    )
    refresher = Refresher(SkillSourceRefreshResult(None, None, None, not_modified=True))

    assert await _orchestrator(states, refresher).run_due(now=NOW) == ()
    assert refresher.etags == []


async def test_rate_limit_uses_server_retry_time_and_preserves_etag() -> None:
    retry_at = NOW + timedelta(minutes=17)
    states = States(
        SkillSourceRefreshState(
            source_id="operations-skills",
            last_etag='"v1"',
            error_count=1,
        )
    )
    refresher = Refresher(SkillSourceRateLimitError(retry_at=retry_at))

    attempts = await _orchestrator(states, refresher).run_due(now=NOW)

    assert attempts[0].status == "rate_limited"
    assert attempts[0].retry_at == retry_at
    assert states.state is not None
    assert states.state.error_count == 2
    assert states.state.last_etag == '"v1"'
    assert states.state.last_error_kind == "rate_limited"
