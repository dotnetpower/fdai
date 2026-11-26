"""Immutable reviewed historical judgment replay source for Forseti."""

from __future__ import annotations

from fdai.agents import ForsetiHistoricalReplay


class ImmutableForsetiHistoricalReplaySource:
    """Serve one exact reviewed archive without providing action authority."""

    def __init__(self, replay: ForsetiHistoricalReplay) -> None:
        self._replay = replay

    async def read_replay(self, archive_ref: str) -> ForsetiHistoricalReplay | None:
        if archive_ref != self._replay.archive_ref:
            return None
        return self._replay


__all__ = ["ImmutableForsetiHistoricalReplaySource"]
