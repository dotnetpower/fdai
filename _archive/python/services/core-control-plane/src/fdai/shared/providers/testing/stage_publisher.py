"""In-memory :class:`StagePublisher` fakes for tests + debugger sessions.

Two shipped implementations:

- :class:`RecordingStagePublisher` - collects every emitted event into a
  list, exposing it via :attr:`events` so a test can assert exactly which
  stage transitions a pipeline emitted (order, count, detail).
- :class:`SnapshotStagePublisher` - same collector, but with helpers
  like :meth:`by_stage` and :meth:`last` that make common assertions
  concise.

The upstream :class:`~fdai.shared.providers.stage_publisher.NullStagePublisher`
is the discard implementation and lives with the Protocol; anything that
records or replays lives here so tests are the only consumer.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai.shared.providers.stage_publisher import (
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)


class RecordingStagePublisher(StagePublisher):
    """Async-safe collector of :class:`StageEvent` for tests.

    The publisher never raises and never blocks; ``emit`` simply appends
    to an internal list. Read the list via :attr:`events`.
    """

    def __init__(self) -> None:
        self._events: list[StageEvent] = []

    async def emit(self, event: StageEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> Sequence[StageEvent]:
        """Read-only view of every event emitted so far, in call order."""
        return tuple(self._events)

    def clear(self) -> None:
        """Reset the collector - useful between phases of one test."""
        self._events.clear()

    # -- convenience helpers used by test assertions -----------------------

    def by_stage(self, stage: StageName) -> Sequence[StageEvent]:
        """Return every event for ``stage`` in call order."""
        return tuple(e for e in self._events if e.stage is stage)

    def by_phase(self, phase: StagePhase) -> Sequence[StageEvent]:
        """Return every event whose phase is ``phase`` in call order."""
        return tuple(e for e in self._events if e.phase is phase)

    def last(self) -> StageEvent | None:
        """Return the most recently emitted event, or ``None`` if empty."""
        return self._events[-1] if self._events else None


__all__ = ["RecordingStagePublisher"]
