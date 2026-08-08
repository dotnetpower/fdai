"""In-memory reference store for forecast episode tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from fdai.core.detection.forecast_episode import (
    ForecastEpisode,
    ForecastEpisodeClosure,
    ForecastEpisodeState,
    ForecastPublicationOutboxItem,
    forecast_publication_id,
)


class InMemoryForecastEpisodeStore:
    def __init__(self) -> None:
        self.episodes: dict[UUID, ForecastEpisode] = {}
        self.closures: dict[UUID, ForecastEpisodeClosure] = {}
        self.outbox: dict[UUID, ForecastPublicationOutboxItem] = {}
        self.published: set[UUID] = set()
        self.dead_lettered: set[UUID] = set()
        self._closure_leases: dict[UUID, datetime] = {}
        self._outbox_leases: dict[UUID, datetime] = {}

    async def record(
        self,
        episode: ForecastEpisode,
        *,
        forecast_payload: dict[str, object] | None = None,
    ) -> bool:
        existing = self.episodes.get(episode.episode_id)
        if existing is not None and existing != episode:
            raise ValueError("forecast episode identity conflict")
        self.episodes.setdefault(episode.episode_id, episode)
        if existing is None and forecast_payload is not None:
            publication_id = forecast_publication_id(
                episode_id=episode.episode_id,
                topic="object.forecast",
            )
            self.outbox[publication_id] = ForecastPublicationOutboxItem(
                publication_id=publication_id,
                episode_id=episode.episode_id,
                topic="object.forecast",
                payload=forecast_payload,
                attempts=0,
            )
        return existing is None

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastEpisode, ...]:
        due: list[ForecastEpisode] = []
        for episode in sorted(
            self.episodes.values(), key=lambda item: (item.closure_due_at, str(item.episode_id))
        ):
            lease = self._closure_leases.get(episode.episode_id)
            if (
                episode.state is ForecastEpisodeState.OPEN
                and episode.closure_due_at <= now
                and (lease is None or lease <= now)
            ):
                claimed = replace(episode, revision=episode.revision + 1)
                self.episodes[episode.episode_id] = claimed
                self._closure_leases[episode.episode_id] = lease_until
                due.append(claimed)
                if len(due) == limit:
                    break
        return tuple(due)

    async def close(self, closure: ForecastEpisodeClosure) -> bool:
        episode = self.episodes[closure.episode_id]
        existing = self.closures.get(closure.episode_id)
        if existing is not None:
            return False
        if episode.state is not ForecastEpisodeState.OPEN:
            return False
        if episode.revision != closure.expected_revision:
            raise ValueError("forecast episode closure revision conflict")
        outcome_payload = closure.outcome_payload
        outbox_item: ForecastPublicationOutboxItem | None = None
        if outcome_payload is not None:
            publication_id = forecast_publication_id(
                episode_id=closure.episode_id,
                topic="object.forecast-outcome",
            )
            outbox_item = ForecastPublicationOutboxItem(
                publication_id=publication_id,
                episode_id=closure.episode_id,
                topic="object.forecast-outcome",
                payload=outcome_payload,
                attempts=0,
            )
        self.episodes[closure.episode_id] = replace(
            episode,
            state=ForecastEpisodeState.CLOSED,
            revision=episode.revision + 1,
        )
        self.closures[closure.episode_id] = closure
        self._closure_leases.pop(closure.episode_id, None)
        if outbox_item is not None:
            self.outbox.setdefault(outbox_item.publication_id, outbox_item)
        return True

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ForecastPublicationOutboxItem, ...]:
        claimed: list[ForecastPublicationOutboxItem] = []
        for publication_id, item in self.outbox.items():
            lease = self._outbox_leases.get(publication_id)
            if (
                publication_id not in self.published
                and publication_id not in self.dead_lettered
                and (lease is None or lease <= now)
            ):
                updated = item
                self._outbox_leases[publication_id] = lease_until
                claimed.append(updated)
                if len(claimed) == limit:
                    break
        return tuple(claimed)

    async def complete_publication(
        self,
        publication_id: UUID,
        *,
        published_at: datetime,
    ) -> None:
        del published_at
        self.published.add(publication_id)
        self._outbox_leases.pop(publication_id, None)

    async def release_publication(
        self,
        publication_id: UUID,
        *,
        available_at: datetime,
        error: str,
    ) -> None:
        del error
        self.outbox[publication_id] = replace(
            self.outbox[publication_id],
            attempts=self.outbox[publication_id].attempts + 1,
        )
        self._outbox_leases[publication_id] = available_at

    async def dead_letter_publication(
        self,
        publication_id: UUID,
        *,
        failed_at: datetime,
        error: str,
    ) -> None:
        del failed_at, error
        self.dead_lettered.add(publication_id)
        self._outbox_leases.pop(publication_id, None)


__all__ = ["InMemoryForecastEpisodeStore"]
