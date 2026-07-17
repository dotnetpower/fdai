"""Fault-injection seams - injector, signal probe, audit recorder.

These Protocols keep the harness portable and provably safe by default:

- :class:`FaultInjector` performs (and undoes) the perturbation. The
  upstream default :class:`ShadowFaultInjector` records intent and mutates
  nothing - so an experiment that reaches an unconfigured harness is a
  no-op, never an accidental outage.
- :class:`SignalProbe` reports whether the expected detection signal fired,
  so the harness can decide VALIDATED vs NOT_DETECTED. The default
  :class:`NoSignalProbe` reports "not observed", which only matters in
  enforce mode.
- :class:`ExperimentRecorder` receives the finished :class:`ExperimentResult`
  for the append-only audit log; the default is an in-memory sink.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from fdai.core.chaos.contract import ExperimentResult


@runtime_checkable
class FaultInjector(Protocol):
    """Inject and stop a perturbation on a target."""

    @property
    def fault_type(self) -> str:
        """The single fault type this injector understands."""
        ...

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        """Begin perturbing ``target``. MUST be undone by :meth:`stop`."""
        ...

    async def stop(self, *, target: str) -> None:
        """Undo the perturbation on ``target`` (rollback). Idempotent."""
        ...


@runtime_checkable
class SignalProbe(Protocol):
    """Report whether the expected detection signal fired during a run."""

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        """True iff ``signal`` was detected for any of ``targets``."""
        ...


@runtime_checkable
class ExperimentRecorder(Protocol):
    """Append-only audit sink for finished experiments."""

    async def record(self, result: ExperimentResult) -> None:
        """Persist one experiment result (never raises into the harness)."""
        ...


class ShadowFaultInjector:
    """Upstream default - records injection intent, perturbs nothing.

    Provably side-effect-free: it only appends to an in-memory log, so a
    shadow experiment can exercise the full harness (blast-radius, audit,
    rollback bookkeeping) without touching a real resource.
    """

    def __init__(self, *, fault_type: str = "*") -> None:
        self._fault_type = fault_type
        self.injected: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:  # noqa: ARG002
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        self.stopped.append(target)


class DetectionOnlyInjector:
    """Marker for a read-only scenario that probes without perturbation."""

    def __init__(self, *, fault_type: str) -> None:
        if not fault_type:
            raise ValueError("fault_type MUST be non-empty")
        self._fault_type = fault_type

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        raise RuntimeError("detection-only scenarios MUST NOT inject")

    async def stop(self, *, target: str) -> None:
        raise RuntimeError("detection-only scenarios MUST NOT roll back a mutation")


class NoSignalProbe:
    """Default probe - reports the signal was not observed."""

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:  # noqa: ARG002
        return False


class InMemoryExperimentRecorder:
    """Default recorder - keeps finished results in memory (test/dev)."""

    def __init__(self) -> None:
        self.results: list[ExperimentResult] = []

    async def record(self, result: ExperimentResult) -> None:
        self.results.append(result)


__all__ = [
    "DetectionOnlyInjector",
    "ExperimentRecorder",
    "FaultInjector",
    "InMemoryExperimentRecorder",
    "NoSignalProbe",
    "ShadowFaultInjector",
    "SignalProbe",
]
