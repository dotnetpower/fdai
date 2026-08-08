"""Stage-transition publisher - the seam every pipeline stage uses to
announce its progress.

The control-plane processes an event through a small number of stages
(``ingest -> route -> verify -> gate -> execute -> audit``). Only the
executor and a handful of vertical detectors currently persist anything,
and they persist **terminal audit rows** only. Nothing tells an
observer "we are entering the risk gate now" or "the T2 verifier is
running its second cross-check". That gap is why the live console
cannot show real-time progress today.

This module introduces the missing seam. Any pipeline stage that wants
to be observable takes a :class:`StagePublisher` in its constructor and
calls :meth:`StagePublisher.emit` on begin / done / failed (and
optionally intermediate progress). Default binding is
:class:`NullStagePublisher` so no existing behaviour changes; a dev /
prod composition binds an adapter (SSE sink, Kafka topic, ...) as
needed.

Design notes
------------

- **Fire-and-forget.** ``emit`` awaits an asynchronous fan-out but never
  blocks the pipeline on a slow subscriber. Backpressure lives in the
  adapter (bounded queue + drop on full, or Kafka batching), not in the
  producer.
- **No autonomy authority.** A stage publisher describes what a stage
  did; it never grants execution eligibility. The verifier + risk gate
  remain the sole authorities on that decision.
- **Structured, machine-parseable.** Every emit carries the
  ``event_id`` and ``correlation_id`` from the driving event so the
  live view, the audit log, and any downstream trace can be joined.
- **Never carries secrets.** Detail is JSON-serializable strings /
  numbers / booleans; if a stage needs to reference a resource, it
  passes the abstract resource id or role - never a connection string,
  token, or subscription id.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class StageName(StrEnum):
    """Which pipeline stage is emitting.

    New stages MUST be added here first so downstream consumers (live
    view legend, dashboards, docs) stay in sync. Adding a stage is a
    documented change - see ``docs/roadmap/rules-and-detection/observability-and-detection.md``.
    """

    INGEST = "ingest"
    ROUTE = "route"
    VERIFY = "verify"
    GATE = "gate"
    EXECUTE = "execute"
    AUDIT = "audit"


class StagePhase(StrEnum):
    """Where within one stage's lifecycle the emit is happening."""

    BEGIN = "begin"
    """Entering the stage; work is starting."""

    PROGRESS = "progress"
    """Optional intermediate signal (e.g. "verifier check 2 of 3 passed").
    A stage MAY skip this and go straight from BEGIN to DONE / FAILED."""

    DONE = "done"
    """Stage finished successfully."""

    FAILED = "failed"
    """Stage failed. ``StageEvent.error`` carries a short reason (never a
    stack trace, never a secret)."""


class ObservationSource(StrEnum):
    """Provenance of a stage observation, not an execution attestation."""

    UNKNOWN = "unknown"
    SYNTHETIC_DEV = "synthetic-dev"
    REPLAY = "replay"
    RUNTIME_OBSERVED = "runtime-observed"


@dataclass(frozen=True, slots=True)
class StageEvent:
    """One stage-transition record.

    Fields are the join keys the live view + audit share. Any additional
    stage-specific information goes into ``detail`` as a JSON-friendly
    mapping.
    """

    event_id: str
    """Stable id of the driving event (idempotency key). Same value the
    audit log uses so live tiles link back to their audit rows."""

    correlation_id: str
    """Correlation id spanning ingest -> execute -> audit for one
    logical incident. May equal ``event_id`` for one-shot events."""

    stage: StageName
    phase: StagePhase
    source: ObservationSource = ObservationSource.UNKNOWN

    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    """Emission timestamp (server clock, timezone-aware UTC)."""

    detail: Mapping[str, Any] = field(default_factory=dict)
    """Stage-specific fields. MUST be JSON-serializable. Examples:
    ``{"tier": "t0"}``, ``{"rule": "storage.public-blob.deny"}``,
    ``{"verifier_pass": ["schema", "policy"], "verifier_fail": []}``."""

    error: str | None = None
    """Non-empty only when :attr:`phase` == :attr:`StagePhase.FAILED`.
    Short, human-readable reason. MUST NOT contain a stack trace or a
    secret."""

    def __post_init__(self) -> None:
        if (self.phase is StagePhase.FAILED) != (self.error is not None):
            raise ValueError(
                "StageEvent.error MUST be set iff phase == FAILED "
                f"(phase={self.phase!r}, error={self.error!r})"
            )
        if self.ts.tzinfo is None:
            raise ValueError("StageEvent.ts MUST be timezone-aware (tzinfo required)")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (used by adapters that
        serialize to SSE / Kafka wire)."""
        out: dict[str, Any] = {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "stage": self.stage.value,
            "phase": self.phase.value,
            "source": self.source.value,
            "ts": _iso(self.ts),
        }
        if self.detail:
            out["detail"] = dict(self.detail)
        if self.error is not None:
            out["error"] = self.error
        return out


@runtime_checkable
class StagePublisher(Protocol):
    """Emit :class:`StageEvent` records from a pipeline stage.

    Implementations MUST be async-safe and MUST NOT raise on a slow /
    disconnected downstream - a stage that fails to emit its progress
    is still expected to complete its work.
    """

    async def emit(self, event: StageEvent) -> None: ...


class NullStagePublisher:
    """Default publisher - discards every event.

    This is the upstream default so wiring a :class:`StagePublisher`
    into a stage is fully backward-compatible: no observer, no side
    effect. A composition root or a fork binds a real publisher
    (SSE, Kafka relay) when it wants live visibility.
    """

    async def emit(self, event: StageEvent) -> None:  # noqa: D401 - trivial
        return None


def _iso(ts: datetime) -> str:
    # Millisecond-precision ISO-8601 with a trailing ``Z``. Same format
    # the audit log + live console use so timestamps compare directly.
    # Convert to UTC first: ``StageEvent`` only validates that ``ts`` is
    # aware (any offset), so stamping a literal ``Z`` onto the raw
    # wall-clock components of a non-UTC datetime would misreport the
    # instant on the wire.
    ts = ts.astimezone(UTC)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


__all__ = [
    "NullStagePublisher",
    "ObservationSource",
    "StageEvent",
    "StageName",
    "StagePhase",
    "StagePublisher",
]
