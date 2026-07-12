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
from collections.abc import Mapping
from typing import Any, Final

from ....core.quality_gate.gate import CrossCheckModel, QualityCandidate

_LOG = logging.getLogger(__name__)

# Same rolling-window shape as the narrator router - small windows react
# quickly to a slowing deployment without thrashing on a single sample.
_WINDOW_SIZE: Final[int] = 8
_WARMUP_SAMPLES: Final[int] = 2
_FAILURE_PENALTY_MS: Final[int] = 30_000


class LatencyRoutedCrossCheckModel:
    """Route each ``propose`` to the fastest of N same-publisher primaries.

    Selection policy (identical in spirit to the narrator router):

    - **Warm-up**: any candidate with fewer than :data:`_WARMUP_SAMPLES`
      effective samples (recorded + in-flight) is picked first, tie-broken
      by name so the pick is deterministic for tests and audit. Every
      candidate is measured on real traffic before it can be de-selected.
    - **Steady state**: pick the lowest rolling-p50 candidate; ties broken
      by in-flight count then name.

    On any exception the router records a large penalty sample so a broken
    candidate rotates out on the next call, then re-raises - the quality
    gate treats a failed proposer exactly as it would a single model that
    raised.
    """

    def __init__(self, *, candidates: list[tuple[str, CrossCheckModel]]) -> None:
        if len(candidates) < 2:
            raise ValueError("LatencyRoutedCrossCheckModel requires >= 2 candidates")
        names = [n for n, _ in candidates]
        if len(set(names)) != len(names):
            raise ValueError("LatencyRoutedCrossCheckModel candidate names MUST be unique")
        self._candidates: Final[list[tuple[str, CrossCheckModel]]] = list(candidates)
        self._samples: Final[dict[str, deque[int]]] = {
            name: deque(maxlen=_WINDOW_SIZE) for name, _ in candidates
        }
        self._in_flight: Final[dict[str, int]] = {name: 0 for name, _ in candidates}

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
            }
            for name, _ in self._candidates
        ]

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        """Delegate to the fastest candidate, recording latency + the pick."""
        name, model = self._pick()
        self._in_flight[name] += 1
        started = time.monotonic()
        try:
            result = await model.propose(candidate)
        except Exception:
            self._samples[name].append(_FAILURE_PENALTY_MS)
            _LOG.warning(
                "t2_primary_router.candidate_failed",
                extra={"candidate": name, "action_type": candidate.action_type},
            )
            raise
        finally:
            self._in_flight[name] = max(0, self._in_flight[name] - 1)
        self._samples[name].append(int((time.monotonic() - started) * 1000))
        # Audit breadcrumb: the deployment that produced this proposal, so a
        # judge-only replay stays deterministic despite the live p50 race.
        _LOG.info(
            "t2_primary_router.pick",
            extra={"chose": name, "action_type": candidate.action_type},
        )
        return result

    # ----------------------------------------------------------------- internal
    def _effective_sample_count(self, name: str) -> int:
        return len(self._samples[name]) + self._in_flight[name]

    def _pick(self) -> tuple[str, CrossCheckModel]:
        cold = [
            (name, model)
            for name, model in self._candidates
            if self._effective_sample_count(name) < _WARMUP_SAMPLES
        ]
        if cold:
            cold.sort(key=lambda x: (self._effective_sample_count(x[0]), x[0]))
            return cold[0]
        return min(
            self._candidates,
            key=lambda x: (
                _p50(self._samples[x[0]]),
                self._in_flight[x[0]],
                x[0],
            ),
        )


def _p50(samples: deque[int]) -> float:
    """Median of a small deque; ``inf`` for empty so warm-up sorts last."""
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 == 1 else (xs[n // 2 - 1] + xs[n // 2]) / 2


__all__ = ["LatencyRoutedCrossCheckModel"]
