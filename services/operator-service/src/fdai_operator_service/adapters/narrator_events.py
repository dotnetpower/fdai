"""Finite canonical event stream returned by the service-local narrator."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fdai_operator_service.families.conversation.contracts import StreamEvent


class NarratorEventIterator(AsyncIterator[StreamEvent]):
    """Expose one already materialized narrator turn as a closeable async stream."""

    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> NarratorEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite local narrator stream."""


__all__ = ["NarratorEventIterator"]
