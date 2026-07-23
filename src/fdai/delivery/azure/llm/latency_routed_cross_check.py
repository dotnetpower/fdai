"""Latency-routed T2 primary proposer (invariant-safe, opt-in).

Wraps N same-publisher :class:`~fdai.core.quality_gate.gate.CrossCheckModel`
deployments of the ``t2.reasoner.primary`` slot and routes each
``propose`` to the fastest by rolling p50 - mirroring the narrator's
``LatencyRoutedChatBackend`` selection policy.

Why this is safe for the quality gate: every wrapped candidate shares one
publisher (enforced upstream by
:func:`~fdai.rule_catalog.schema.llm_resolver.collect_primary_candidates`),
so routing among them NEVER changes the primary's *publisher*. The
mixed-model cross-check therefore still runs a distinct primary-vs-secondary
pair. See docs/roadmap/architecture/llm-strategy.md
(section "T2 Primary Latency Pool") for the full design review.

Determinism / audit: every routed call logs the chosen deployment
(``t2_primary_router.pick``) so a judge-only replay can reconstruct which
deployment produced the proposal even though the live pick varies with
measured p50.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from ....core.quality_gate.gate import CrossCheckModel, QualityCandidate
from ....shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)

_LOG = logging.getLogger(__name__)

# Same rolling-window shape as the narrator router - small windows react
# quickly to a slowing deployment without thrashing on a single sample.
_WINDOW_SIZE: Final[int] = 8
_WARMUP_SAMPLES: Final[int] = 2
_FAILURE_PENALTY_MS: Final[int] = 30_000


class ModelFailureKind(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


class ModelPoolUnavailableError(RuntimeError):
    """Every same-publisher primary is inside a bounded cooldown."""


@dataclass(frozen=True, slots=True)
class ModelHealthTransition:
    model_role: str
    deployment: str
    status: str
    failure_kind: ModelFailureKind | None
    failure_count: int
    cooldown_seconds: int
    recorded_at: datetime
    reason: str = ""


class ModelHealthTransitionSink(Protocol):
    async def append(self, transition: ModelHealthTransition) -> None: ...


class InMemoryModelHealthTransitionSink:
    def __init__(self) -> None:
        self.transitions: list[ModelHealthTransition] = []

    async def append(self, transition: ModelHealthTransition) -> None:
        self.transitions.append(transition)


class _NoopModelHealthTransitionSink:
    async def append(self, transition: ModelHealthTransition) -> None:
        del transition


_COOLDOWN_SECONDS: Final[dict[ModelFailureKind, int]] = {
    ModelFailureKind.AUTH: 300,
    ModelFailureKind.RATE_LIMIT: 60,
    ModelFailureKind.OVERLOADED: 30,
    ModelFailureKind.TIMEOUT: 30,
    ModelFailureKind.TRANSPORT: 30,
    ModelFailureKind.UNKNOWN: 30,
}


class LatencyRoutedCrossCheckModel:
    """Route each ``propose`` to the fastest of N same-publisher primaries.

    Selection policy (identical in spirit to the narrator router):

    - **Warm-up**: any candidate with fewer than :data:`_WARMUP_SAMPLES`
      effective samples (recorded + in-flight) is picked first, tie-broken
      by name so the pick is deterministic for tests and audit. Every
      candidate is measured on real traffic before it can be de-selected.
    - **Steady state**: pick the lowest rolling-p50 candidate; ties broken
      by in-flight count then name.

    On an exception the router records a large penalty and tries each remaining
    same-publisher candidate at most once. If every candidate fails, the final
    error is re-raised and the quality gate degrades to human review.
    """

    def __init__(
        self,
        *,
        candidates: list[tuple[str, CrossCheckModel]],
        clock: Callable[[], float] = time.monotonic,
        transition_sink: ModelHealthTransitionSink | None = None,
        model_role: str = "t2.reasoner.primary",
        recorded_at: Callable[[], datetime] | None = None,
        routing_transition_sink: RoutingTransitionSink | None = None,
    ) -> None:
        if len(candidates) < 2:
            raise ValueError("LatencyRoutedCrossCheckModel requires >= 2 candidates")
        names = [n for n, _ in candidates]
        if len(set(names)) != len(names):
            raise ValueError("LatencyRoutedCrossCheckModel candidate names MUST be unique")
        if not model_role:
            raise ValueError("model health role MUST be non-empty")
        self._candidates: Final[list[tuple[str, CrossCheckModel]]] = list(candidates)
        self._samples: Final[dict[str, deque[int]]] = {
            name: deque(maxlen=_WINDOW_SIZE) for name, _ in candidates
        }
        self._in_flight: Final[dict[str, int]] = {name: 0 for name, _ in candidates}
        self._failure_count: Final[dict[str, int]] = {name: 0 for name, _ in candidates}
        self._failure_kind: Final[dict[str, ModelFailureKind | None]] = {
            name: None for name, _ in candidates
        }
        self._cooldown_until: Final[dict[str, float]] = {name: 0.0 for name, _ in candidates}
        self._clock = clock
        self._transition_sink = transition_sink or _NoopModelHealthTransitionSink()
        self._model_role = model_role
        self._recorded_at = recorded_at or (lambda: datetime.now(tz=UTC))
        self._routing_transition_sink = routing_transition_sink or default_transition_emitter()

    # ------------------------------------------------------------------ public
    def current_pick_name(self) -> str:
        """Which candidate would serve the NEXT call (peek, no state change)."""
        name, _ = self._pick()
        return name

    def stats(self) -> list[dict[str, Any]]:
        """Snapshot of per-candidate rolling p50 + sample counts (JSON-safe)."""
        return [
            {
                "deployment": name,
                "p50_ms": _p50(self._samples[name]),
                "samples": len(self._samples[name]),
                "failure_count": self._failure_count[name],
                "last_failure_kind": _failure_kind_value(self._failure_kind[name]),
                "cooldown_remaining_seconds": max(
                    0,
                    int(self._cooldown_until[name] - self._clock()),
                ),
            }
            for name, _ in self._candidates
        ]

    def startup_candidates(self) -> tuple[CrossCheckModel, ...]:
        """Expose every bound candidate for startup proof without deployment metadata."""
        return tuple(model for _, model in self._candidates)

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        """Try same-publisher candidates in bounded latency order."""
        attempted: set[str] = set()
        last_error: Exception | None = None
        while len(attempted) < len(self._candidates):
            try:
                name, model = self._pick(exclude=attempted)
            except ModelPoolUnavailableError as cooldown_error:
                if last_error is not None:
                    raise last_error from cooldown_error
                raise
            self._in_flight[name] += 1
            started = time.monotonic()
            try:
                result = await model.propose(candidate)
            except Exception as exc:
                attempted.add(name)
                last_error = exc
                self._samples[name].append(_FAILURE_PENALTY_MS)
                await self._record_failure(name, exc)
                _LOG.warning(
                    "t2_primary_router.candidate_failed",
                    extra={"candidate": name, "action_type": candidate.action_type},
                )
                continue
            finally:
                self._in_flight[name] = max(0, self._in_flight[name] - 1)
            self._samples[name].append(int((time.monotonic() - started) * 1000))
            was_unhealthy = self._failure_count[name] > 0
            self._failure_count[name] = 0
            self._failure_kind[name] = None
            self._cooldown_until[name] = 0.0
            if was_unhealthy:
                await self._emit_transition(
                    ModelHealthTransition(
                        model_role=self._model_role,
                        deployment=name,
                        status="recovered",
                        failure_kind=None,
                        failure_count=0,
                        cooldown_seconds=0,
                        recorded_at=self._recorded_at(),
                    )
                )
            await self._emit_transition(
                ModelHealthTransition(
                    model_role=self._model_role,
                    deployment=name,
                    status="selected",
                    failure_kind=None,
                    failure_count=0,
                    cooldown_seconds=0,
                    recorded_at=self._recorded_at(),
                    reason=(
                        f"failover_after_{len(attempted)}_candidate_failure"
                        if attempted
                        else "latency_route"
                    ),
                )
            )
            _LOG.info(
                "t2_primary_router.pick",
                extra={
                    "chose": name,
                    "action_type": candidate.action_type,
                    "failover_count": len(attempted),
                },
            )
            return result
        if last_error is not None:
            raise last_error
        raise RuntimeError("T2 primary router exhausted candidates")

    # ----------------------------------------------------------------- internal
    def _effective_sample_count(self, name: str) -> int:
        return len(self._samples[name]) + self._in_flight[name]

    def _pick(self, *, exclude: set[str] | None = None) -> tuple[str, CrossCheckModel]:
        excluded = exclude or set()
        now = self._clock()
        available = [
            candidate
            for candidate in self._candidates
            if candidate[0] not in excluded and self._cooldown_until[candidate[0]] <= now
        ]
        if not available:
            raise ModelPoolUnavailableError("T2 primary model pool is cooling down")
        cold = [
            (name, model)
            for name, model in available
            if self._effective_sample_count(name) < _WARMUP_SAMPLES
        ]
        if cold:
            cold.sort(key=lambda x: (self._effective_sample_count(x[0]), x[0]))
            return cold[0]
        return min(
            available,
            key=lambda x: (
                _p50(self._samples[x[0]]),
                self._in_flight[x[0]],
                x[0],
            ),
        )

    async def _record_failure(self, name: str, error: Exception) -> None:
        kind = classify_model_failure(error)
        self._failure_count[name] += 1
        self._failure_kind[name] = kind
        multiplier = min(self._failure_count[name], 3)
        cooldown_seconds = _COOLDOWN_SECONDS[kind] * multiplier
        self._cooldown_until[name] = self._clock() + cooldown_seconds
        await self._emit_transition(
            ModelHealthTransition(
                model_role=self._model_role,
                deployment=name,
                status="unhealthy",
                failure_kind=kind,
                failure_count=self._failure_count[name],
                cooldown_seconds=cooldown_seconds,
                recorded_at=self._recorded_at(),
            )
        )

    async def _emit_transition(self, transition: ModelHealthTransition) -> None:
        outcome = "failed" if transition.status == "unhealthy" else transition.status
        emit_transition_safely(
            self._routing_transition_sink,
            RoutingTransition(
                domain="model",
                name="health" if transition.status != "selected" else "selection",
                outcome=outcome,
                attributes={
                    "model_role": transition.model_role,
                    "deployment": transition.deployment,
                    "reason_code": transition.reason or "none",
                },
            ),
        )
        try:
            await self._transition_sink.append(transition)
        except Exception:
            _LOG.error(
                "model_health_transition_persist_failed",
                extra={
                    "model_role": transition.model_role,
                    "deployment": transition.deployment,
                    "status": transition.status,
                },
                exc_info=True,
            )


def _p50(samples: deque[int]) -> float:
    """Median of a small deque; ``inf`` for empty so warm-up sorts last."""
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 == 1 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _failure_kind_value(kind: ModelFailureKind | None) -> str | None:
    return kind.value if kind is not None else None


def classify_model_failure(error: Exception) -> ModelFailureKind:
    """Classify without exposing provider error text in router state."""
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return ModelFailureKind.AUTH
    if status == 429:
        return ModelFailureKind.RATE_LIMIT
    if status in {502, 503, 529}:
        return ModelFailureKind.OVERLOADED
    if status in {408, 504} or isinstance(error, TimeoutError):
        return ModelFailureKind.TIMEOUT
    if isinstance(error, ConnectionError):
        return ModelFailureKind.TRANSPORT
    return ModelFailureKind.UNKNOWN


__all__ = [
    "InMemoryModelHealthTransitionSink",
    "LatencyRoutedCrossCheckModel",
    "ModelFailureKind",
    "ModelHealthTransition",
    "ModelHealthTransitionSink",
    "ModelPoolUnavailableError",
    "classify_model_failure",
]
