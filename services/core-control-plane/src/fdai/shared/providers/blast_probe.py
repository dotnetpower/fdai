"""LiveBlastProbe - Axis E live-signal reader for the RiskGate.

`docs/roadmap/decisioning/execution-model.md § 4 (Axis E)` describes the
live-blast probe: at dispatch time the RiskGate calls a probe, gets
back one of ``quiet`` / ``active`` / ``overloaded``, and uses it as a
ceiling-lowering axis (never an authoriser). The Protocol below is the
CSP-neutral contract; concrete adapters (Azure Monitor KQL, Prometheus,
CloudWatch, ...) live under ``delivery/`` and MUST NOT be imported from
``core/``.

Axis-E invariants:

- **Ceiling-lowering only** - a probe result NEVER raises autonomy. If
  the probe is not configured (``live_probe_ref`` unset on the
  ActionType), the axis returns
  :attr:`ProbeVerdict.NO_OPINION` and the static ceiling wins.
- **Bounded I/O** - every probe carries a ``deadline_seconds``; a
  timeout MUST return :attr:`ProbeVerdict.ACTIVE` and set
  ``degraded=True`` so the RiskGate can force HIL rather than
  hard-stop the loop.
- **Repeat-failure escalation** - the RiskGate (not the probe) tracks
  a rolling window of degraded returns and escalates to
  :attr:`ProbeVerdict.OVERLOADED` when the window trips. That belongs
  in the risk-gate, not the probe adapter.
- **Replay-safe** - a probe MUST NOT be re-queried during audit
  replay. The result is written to the ``resolved_ceiling`` audit
  block once and read from there on replay
  (`docs/roadmap/decisioning/execution-model.md § 4.2`).

Wave M1.1 scope: this file (Protocol + result types), the fake
``NoOpBlastProbe`` under
:mod:`fdai.shared.providers.testing.blast_probe`, and unit tests.
The Azure adapter (`AzureMonitorBlastProbe`) is fork territory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ProbeVerdict(StrEnum):
    """Three-level result the RiskGate consumes.

    The strings are the same wire vocabulary the ontology uses in
    ``rule-catalog/probes/*.yaml`` (see the interpretation block on
    each probe) so no translation happens between the probe and the
    audit log.
    """

    QUIET = "quiet"
    """No unusual activity - the static ceiling wins."""

    ACTIVE = "active"
    """Elevated activity - the RiskGate MUST cap at ``enforce_hil``
    (a human approves)."""

    OVERLOADED = "overloaded"
    """Too risky right now - the RiskGate MUST cap at
    ``shadow_only`` (defer)."""

    NO_OPINION = "no_opinion"
    """The probe is not configured or has no signal. Returned when the
    ActionType has no ``live_probe_ref``; NEVER lowers autonomy."""


class BlastProbeError(RuntimeError):
    """Base class for probe failures the RiskGate surfaces to audit.

    Adapters MUST NOT raise generic exceptions past this boundary;
    they wrap the underlying substrate error so the RiskGate can
    classify without parsing.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class BlastProbeTimeoutError(BlastProbeError):
    """The probe did not return within its ``deadline_seconds``.

    The RiskGate treats a timeout as a single-shot failure and
    returns :attr:`ProbeVerdict.ACTIVE` with ``degraded=True`` from
    the axis; repeated timeouts escalate that ActionType's posture to
    ``shadow_only`` (see the doc invariant above).
    """

    def __init__(self, message: str) -> None:
        super().__init__(kind="timeout", message=message)


class BlastProbeConfigError(BlastProbeError):
    """The probe manifest is malformed (missing threshold, unknown
    aggregation, ...). Raised at composition time, not at dispatch,
    so a misconfigured probe fails startup rather than each event."""

    def __init__(self, message: str) -> None:
        super().__init__(kind="config", message=message)


@dataclass(frozen=True, slots=True)
class ProbeQuery:
    """One live-blast probe query.

    Frozen so it round-trips through the audit log unchanged. The
    ``probe_id`` matches the ``id`` field on the shipped probe YAMLs
    under ``rule-catalog/probes/``; the adapter dispatch table maps it
    to the concrete substrate call.
    """

    probe_id: str
    """Canonical probe id from ``rule-catalog/probes/<id>.yaml``."""

    target_ref: str
    """Opaque substrate identifier (ARM id, k8s ref, ...); the adapter
    interprets it. ``core/`` treats it as a correlation string."""

    deadline_seconds: float
    """Upper bound on adapter I/O. The adapter MUST raise
    :class:`BlastProbeTimeoutError` on breach."""

    def __post_init__(self) -> None:
        if not self.probe_id:
            raise ValueError("ProbeQuery.probe_id MUST be non-empty")
        if not self.target_ref:
            raise ValueError("ProbeQuery.target_ref MUST be non-empty")
        if self.deadline_seconds <= 0:
            raise ValueError("ProbeQuery.deadline_seconds MUST be > 0")


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One live-blast probe result.

    Written to the ``resolved_ceiling.live_probe_result`` audit block
    verbatim; replay reads it back without re-invoking the adapter.
    ``metrics`` is an optional evidence dictionary (bytes read,
    p95_ms, ...) preserved for audit; it MUST NOT carry secrets.
    """

    verdict: ProbeVerdict
    reason: str = ""
    """Human-readable one-line summary for audit (no secrets)."""

    degraded: bool = False
    """``True`` when the adapter returned but its result is provisional
    (e.g. partial data, retry backoff). The RiskGate MAY count degraded
    returns toward the repeat-failure escalation window."""

    metrics: Mapping[str, float] = field(default_factory=dict)
    """Optional evidence dictionary for audit. Values MUST be scalar
    floats - no nested structures, no strings that could carry a
    secret."""


@runtime_checkable
class LiveBlastProbe(Protocol):
    """Read a live signal for one target resource.

    Implementations MUST:

    - be **read-only** on the substrate; probes never mutate;
    - honour :attr:`ProbeQuery.deadline_seconds` and raise
      :class:`BlastProbeTimeoutError` on breach;
    - be **safe to call at high frequency** - the RiskGate caches
      results by ``(probe_id, target_ref)`` per the cache TTL on the
      shipped probe YAML, but the adapter itself MUST NOT rely on the
      cache for correctness;
    - be **deterministic given the same inputs and window** (or
      annotate ``degraded=True`` when the underlying data is
      provisional).
    """

    async def measure(self, query: ProbeQuery) -> ProbeResult: ...


__all__ = [
    "BlastProbeConfigError",
    "BlastProbeError",
    "BlastProbeTimeoutError",
    "LiveBlastProbe",
    "ProbeQuery",
    "ProbeResult",
    "ProbeVerdict",
]
