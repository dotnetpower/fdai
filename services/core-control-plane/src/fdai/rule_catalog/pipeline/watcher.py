"""SourceWatcher - cadence-driven re-fetch decision.

Pure scheduling logic. Given a :class:`SourceManifest` and the current
time, decide whether the source is due for re-collection by comparing
the previous ``SNAPSHOT.json.collected_at`` against the manifest cadence.

Reading ``SNAPSHOT.json`` is the only I/O this module performs - it
never fetches, writes, or mutates state. The CLI wrapper
(:mod:`fdai.rule_catalog.pipeline.watcher_cli`) composes the
watcher with the existing collector CLI so a Container Apps Job cron
can drive scheduled fetches without manual invocation.

Phase 2 mapping (``docs/roadmap/phases/phase-2-quality-and-t1.md``
§ Continuous Rule Update Pipeline):

    source watcher → collect/normalize → shadow eval → regression gate

This module is the *source watcher* - decide whether to poll - while
``collect_cli`` covers the *collect/normalize* stage. The pipeline
never promotes automatically; promotion stays a reviewed
catalog-as-code PR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.rule_catalog.schema.source_manifest import Cadence, SourceManifest

# Cadence → interval mapping. ``on-demand`` deliberately maps to ``None``
# - the caller never fires an on-demand source from the watcher; it
# stays manual.
_CADENCE_INTERVALS: dict[Cadence, timedelta | None] = {
    Cadence.ON_DEMAND: None,
    Cadence.DAILY: timedelta(days=1),
    Cadence.WEEKLY: timedelta(days=7),
    # "monthly" is 28 days on purpose - the watcher runs on a daily
    # cron, so a 30/31-day window would drift; 28 days keeps the
    # decision purely arithmetic and calendar-agnostic.
    Cadence.MONTHLY: timedelta(days=28),
}


class WatcherError(ValueError):
    """Raised when the watcher cannot make a decision (unknown cadence)."""


@dataclass(frozen=True, slots=True)
class SourceWatcher:
    """Cadence-aware scheduling decision for one manifest.

    ``snapshot_root`` is the directory under which the collector writes
    per-source snapshot trees (``<snapshot_root>/<source_id>/<rev>/``).
    In production that is ``rule-catalog/sources/``; tests point it at a
    tmp_path.
    """

    snapshot_root: Path

    def is_due(self, manifest: SourceManifest, *, now: datetime) -> bool:
        """Return ``True`` when ``manifest`` is due for a re-fetch at ``now``.

        - ``on-demand`` - never due; returns ``False``. Callers invoke
          the collector manually for on-demand sources.
        - ``daily`` / ``weekly`` / ``monthly`` - due when no prior
          snapshot exists OR ``now - last_collected_at >= interval``.
        - Any other cadence - raises :class:`WatcherError`. Every
          currently declared :class:`Cadence` value is mapped, so this
          branch is a defensive guard for future enum additions.
        """
        interval = self._interval_for(manifest.cadence)
        if interval is None:
            return False
        last = self._last_collected_at(manifest.id)
        if last is None:
            # First-ever collection is always due - no baseline to compare.
            return True
        # Compare in UTC. A naive ``collected_at`` (older snapshot format)
        # is normalized to UTC in ``_last_collected_at``.
        return (now - last) >= interval

    # ------------------------------------------------------------------
    # Internals - kept public-static so tests can exercise the mapping
    # directly without constructing a manifest.
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_for(cadence: Cadence) -> timedelta | None:
        try:
            return _CADENCE_INTERVALS[cadence]
        except KeyError as exc:
            raise WatcherError(f"unknown cadence: {cadence!r}") from exc

    def _last_collected_at(self, source_id: str) -> datetime | None:
        """Newest ``collected_at`` across every snapshot for ``source_id``.

        Missing directory, missing ``SNAPSHOT.json``, or malformed
        provenance all return ``None`` for that revision - the watcher
        never crashes on a partial snapshot tree.
        """
        source_dir = self.snapshot_root / source_id
        if not source_dir.is_dir():
            return None
        latest: datetime | None = None
        for revision_dir in source_dir.iterdir():
            if not revision_dir.is_dir():
                continue
            snap = revision_dir / "SNAPSHOT.json"
            if not snap.is_file():
                continue
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            ts = data.get("collected_at") if isinstance(data, dict) else None
            if not isinstance(ts, str):
                continue
            try:
                parsed = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if latest is None or parsed > latest:
                latest = parsed
        return latest


__all__ = ["SourceWatcher", "WatcherError"]
