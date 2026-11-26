"""Scheduled refresh orchestration with durable ETag and retry state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceRefreshPolicy,
    SkillSourceStore,
)
from fdai.core.supply_chain.skill_quarantine import (
    SkillSourceRefreshState,
    SkillSourceRefreshStateStore,
)
from fdai.core.supply_chain.skill_source_pipeline import SkillSourceRefreshResult
from fdai.shared.providers.skill_source import (
    SkillSourceAdapter,
    SkillSourceRateLimitError,
)

_BASE_BACKOFF_SECONDS = 300
_MAX_BACKOFF_SECONDS = 21_600
_CLAIM_SECONDS = 300


class SkillSourceAdapterFactory(Protocol):
    def __call__(self, source: SkillSource) -> SkillSourceAdapter: ...


class SkillSourceRefresher(Protocol):
    async def refresh(
        self,
        source: SkillSource,
        adapter: SkillSourceAdapter,
        *,
        fetched_at: datetime,
        prior_etag: str | None = None,
        prior_installed_digest: str | None = None,
    ) -> SkillSourceRefreshResult: ...


@dataclass(frozen=True, slots=True)
class SkillSourceRefreshAttempt:
    source_id: str
    status: str
    candidate_id: str | None = None
    retry_at: datetime | None = None


class SkillSourceRefreshOrchestrator:
    def __init__(
        self,
        *,
        sources: SkillSourceStore,
        states: SkillSourceRefreshStateStore,
        refresher: SkillSourceRefresher,
        adapter_factory: SkillSourceAdapterFactory,
    ) -> None:
        self._sources = sources
        self._states = states
        self._refresher = refresher
        self._adapter_factory = adapter_factory

    async def run_due(self, *, now: datetime) -> tuple[SkillSourceRefreshAttempt, ...]:
        if now.tzinfo is None:
            raise ValueError("skill source refresh time MUST include timezone")
        attempts: list[SkillSourceRefreshAttempt] = []
        for source in await self._sources.list(enabled_only=True):
            if source.refresh_policy is not SkillSourceRefreshPolicy.SCHEDULED:
                continue
            state = await self._states.claim(
                source_id=source.source_id,
                now=now,
                hold_until=now + timedelta(seconds=_CLAIM_SECONDS),
            )
            if state is None:
                continue
            attempts.append(await self._refresh_source(source, state=state, now=now))
        return tuple(attempts)

    async def _refresh_source(
        self,
        source: SkillSource,
        *,
        state: SkillSourceRefreshState | None,
        now: datetime,
    ) -> SkillSourceRefreshAttempt:
        previous = state or SkillSourceRefreshState(source_id=source.source_id)
        try:
            result = await self._refresher.refresh(
                source,
                self._adapter_factory(source),
                fetched_at=now,
                prior_etag=previous.last_etag,
            )
        except SkillSourceRateLimitError as exc:
            retry_at = exc.retry_at
            if retry_at is None or retry_at <= now:
                retry_at = now + _backoff(previous.error_count)
            await self._states.put(
                _failed_state(previous, retry_at=retry_at, error_kind="rate_limited")
            )
            return SkillSourceRefreshAttempt(
                source_id=source.source_id,
                status="rate_limited",
                retry_at=retry_at,
            )
        except Exception as exc:  # noqa: BLE001 - persist a bounded retry for adapter failures
            retry_at = now + _backoff(previous.error_count)
            await self._states.put(
                _failed_state(
                    previous,
                    retry_at=retry_at,
                    error_kind=type(exc).__name__[:128],
                )
            )
            return SkillSourceRefreshAttempt(
                source_id=source.source_id,
                status="failed",
                retry_at=retry_at,
            )
        artifact = result.artifact
        await self._states.put(
            SkillSourceRefreshState(
                source_id=source.source_id,
                last_refresh_at=now,
                next_refresh_at=now + timedelta(seconds=source.refresh_interval_seconds),
                last_etag=result.etag or previous.last_etag,
                last_revision=(
                    artifact.source_revision if artifact is not None else previous.last_revision
                ),
            )
        )
        return SkillSourceRefreshAttempt(
            source_id=source.source_id,
            status="not_modified" if result.not_modified else "refreshed",
            candidate_id=(result.candidate.candidate_id if result.candidate is not None else None),
        )


def _backoff(error_count: int) -> timedelta:
    seconds = min(_BASE_BACKOFF_SECONDS * (2 ** min(error_count, 6)), _MAX_BACKOFF_SECONDS)
    return timedelta(seconds=seconds)


def _failed_state(
    previous: SkillSourceRefreshState,
    *,
    retry_at: datetime,
    error_kind: str,
) -> SkillSourceRefreshState:
    return SkillSourceRefreshState(
        source_id=previous.source_id,
        last_refresh_at=previous.last_refresh_at,
        next_refresh_at=previous.next_refresh_at,
        last_etag=previous.last_etag,
        last_revision=previous.last_revision,
        error_count=previous.error_count + 1,
        retry_at=retry_at,
        last_error_kind=error_kind,
    )


__all__ = [
    "SkillSourceAdapterFactory",
    "SkillSourceRefreshAttempt",
    "SkillSourceRefreshOrchestrator",
    "SkillSourceRefresher",
]
