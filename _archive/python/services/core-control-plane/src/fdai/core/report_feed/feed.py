"""Report feed aggregator + source seam (SRE-agent slide 22).

:class:`ReportFeed` collects :class:`ReportSignal` values from multiple
registered :class:`SignalSource` implementations over a time window, sorts
them (severity first, then most-recent), and optionally filters by
:class:`ReportCategory` for the Workload vs Security report. Fail-closed: a
source that raises is skipped and recorded in ``source_errors`` - one bad
source never drops the whole feed. Read-only throughout.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.core.report_feed.models import (
    ReportCategory,
    ReportFeedResult,
    ReportSignal,
    severity_rank,
)

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class SignalSource(Protocol):
    """A named producer of report signals over a time window."""

    @property
    def name(self) -> str:
        """Stable identifier for logs / error attribution."""
        ...

    async def signals(self, *, since: datetime, until: datetime) -> Sequence[ReportSignal]:
        """Return the signals this source observed in ``[since, until]``."""
        ...


class StaticSignalSource:
    """In-memory source over a fixed signal list (test / dev default)."""

    def __init__(self, name: str, signals: Sequence[ReportSignal]) -> None:
        self._name = name
        self._signals = tuple(signals)

    @property
    def name(self) -> str:
        return self._name

    async def signals(self, *, since: datetime, until: datetime) -> Sequence[ReportSignal]:
        return tuple(s for s in self._signals if since <= s.occurred_at <= until)


class ReportFeed:
    """Aggregate report signals from registered sources."""

    __slots__ = ("_sources",)

    def __init__(self, sources: Sequence[SignalSource] = ()) -> None:
        self._sources: list[SignalSource] = list(sources)

    def register(self, source: SignalSource) -> None:
        self._sources.append(source)

    async def collect(
        self,
        *,
        since: datetime,
        until: datetime,
        category: ReportCategory | None = None,
    ) -> ReportFeedResult:
        collected: list[ReportSignal] = []
        errors: list[tuple[str, str]] = []
        for source in self._sources:
            try:
                found = await source.signals(since=since, until=until)
            except Exception as exc:  # noqa: BLE001 - isolate one bad source
                errors.append((source.name, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning("report_feed_source_failed", extra={"source": source.name})
                continue
            collected.extend(found)

        if category is not None:
            collected = [s for s in collected if s.category is category]

        # Severity first (critical -> low), then most-recent, then id for stability.
        collected.sort(
            key=lambda s: (severity_rank(s.severity), _neg_ts(s.occurred_at), s.signal_id)
        )
        return ReportFeedResult(signals=tuple(collected), source_errors=tuple(errors))


def _neg_ts(at: datetime) -> float:
    """Negative epoch so a descending (most-recent-first) sort is ascending."""
    return -at.timestamp()


__all__ = [
    "ReportFeed",
    "SignalSource",
    "StaticSignalSource",
]
