"""Self-consistency sampler - action-stability as a derived confidence.

Complements the rubric (:mod:`fdai.core.quality_gate.rubric`). Where the
rubric scores the *quality* of one answer, self-consistency measures
whether the reasoner *agrees with itself*: sample the same proposer N
times and measure how often it lands on the same normalized action. An
unstable proposer (its answer flips across samples) is a hallucination
signal - the reasoning is not robust.

The result is reduced to a single ``action_stability`` value in
``[0.0, 1.0]`` that the composition root merges into a candidate's
``confidence_signals``. Because
:attr:`~fdai.core.quality_gate.gate.QualityCandidate.aggregate_confidence`
is a mean over the signals, a low stability *lowers* the aggregate -
consistent with the subtractive posture of the whole gate. It never
grants eligibility on its own; the deterministic verifier still decides.

Cost control
------------
Sampling N times multiplies the T2 token cost, so the sampler is meant
to run in a **cascade**: the composition root invokes it only when a
cheaper signal (grounding coverage, single-shot confidence) is weak,
not on every T2 call. This module implements the measurement; the
cascade trigger is a composition concern.

Design boundaries
-----------------
- **``core/``-safe.** Imports only from ``fdai.core.quality_gate`` and
  stdlib. The proposer is the existing
  :class:`~fdai.core.quality_gate.gate.CrossCheckModel` Protocol seam,
  so a fork binds a real (temperature > 0) reasoner; the fake in
  :mod:`~fdai.core.quality_gate.testing` drives deterministic tests.
- **Deterministic reduction.** :func:`compute_stability` is a pure
  function over the sampled action types; ties break on the first-seen
  modal value so a replay is reproducible.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from fdai.core.quality_gate.gate import CrossCheckModel, QualityCandidate

STABILITY_SIGNAL_KEY = "action_stability"
"""The ``confidence_signals`` key the sampler contributes."""


@dataclass(frozen=True, slots=True)
class SelfConsistencyResult:
    """Outcome of sampling one proposer N times for one candidate."""

    sampled_action_types: tuple[str, ...]
    modal_action_type: str
    agreement_count: int
    total: int
    stability: float
    """``agreement_count / total`` - the fraction of samples that landed
    on the modal action type. ``1.0`` means the proposer never wavered;
    lower means it flipped, a hallucination signal."""

    @property
    def signal(self) -> dict[str, float]:
        """The ``confidence_signals`` fragment to merge into a candidate."""
        return {STABILITY_SIGNAL_KEY: self.stability}


def compute_stability(action_types: Sequence[str]) -> tuple[str, int, float]:
    """Reduce sampled action types to ``(modal, count, stability)``.

    ``modal`` is the most frequent action type (first-seen wins on a
    tie, for replay determinism); ``count`` is how many samples equalled
    it; ``stability`` is ``count / len(action_types)``. Raises
    :class:`ValueError` on an empty sequence - there is nothing to
    measure and a silent ``0.0`` would be indistinguishable from a real
    zero-stability result.
    """
    if not action_types:
        raise ValueError("compute_stability requires at least one sampled action type")
    counts = Counter(action_types)
    # Counter.most_common preserves insertion order on ties (Python 3.7+
    # dict ordering), so the first-seen modal value wins deterministically.
    modal, count = counts.most_common(1)[0]
    return modal, count, count / len(action_types)


class SelfConsistencySampler:
    """Sample a proposer N times and reduce to an action-stability signal."""

    def __init__(self, *, proposer: CrossCheckModel, samples: int = 3) -> None:
        if samples < 1:
            raise ValueError("samples MUST be >= 1")
        self._proposer = proposer
        self._samples = samples

    async def sample(self, candidate: QualityCandidate) -> SelfConsistencyResult:
        """Sample the proposer ``samples`` times concurrently for ``candidate``.

        Each sample is an independent read-only call, so they run
        concurrently to add one call's latency (not the sum) to the T2
        budget. The proposer is expected to run at temperature > 0 so
        the samples can diverge; a temperature-0 proposer trivially
        yields ``stability == 1.0``.

        Raises whatever the proposer raises. When one sample fails (or
        the caller cancels), the in-flight sibling samples are cancelled
        before the exception propagates, so a failed cascade-sampling
        call does not leak background tasks. The caller (the cascade
        trigger) is responsible for routing that failure to HIL.
        """
        tasks = [
            asyncio.create_task(self._proposer.propose(candidate)) for _ in range(self._samples)
        ]
        try:
            proposals = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            raise
        action_types = tuple(action_type for action_type, _params in proposals)
        modal, count, stability = compute_stability(action_types)
        return SelfConsistencyResult(
            sampled_action_types=action_types,
            modal_action_type=modal,
            agreement_count=count,
            total=len(action_types),
            stability=stability,
        )


@dataclass(frozen=True, slots=True)
class CascadeDecision:
    """Outcome of a self-consistency cascade for one candidate.

    ``should_sample`` records whether the cheap-signal gate decided the
    N-sample fan-out was worth it. ``stable`` is ``None`` when no
    sampling ran, else ``True`` when the sampled stability cleared the
    stability threshold. ``result`` carries the raw
    :class:`SelfConsistencyResult` when sampling ran.

    Consuming this as a **gate** (route ``stable is False`` to HIL) keeps
    the stability signal subtractive - unlike merging ``action_stability``
    into the mean ``confidence_signals``, where a low value can be masked
    by other high signals. See
    ``docs/roadmap/decisioning/hallucination-rubric-gate.md`` § Self-consistency.
    """

    should_sample: bool
    stable: bool | None
    result: SelfConsistencyResult | None


async def run_consistency_cascade(
    sampler: SelfConsistencySampler,
    candidate: QualityCandidate,
    *,
    aggregate_confidence: float,
    sample_threshold: float,
    stability_threshold: float,
) -> CascadeDecision:
    """Sample for consistency ONLY when the cheap signal is weak.

    Cost control (``docs/roadmap/architecture/llm-strategy.md`` § cascade): when
    ``aggregate_confidence >= sample_threshold`` the cheap signal is
    already strong, so no samples are spent and the decision is
    ``should_sample=False``. Otherwise the sampler runs and ``stable``
    reflects whether the measured stability cleared
    ``stability_threshold``. The caller routes ``stable is False`` to HIL
    (a subtractive gate), never averaging the stability into confidence.

    Raises whatever :meth:`SelfConsistencySampler.sample` raises (a
    proposer failure propagates after the in-flight siblings are
    cancelled). The caller (the cascade site) MUST treat that as a
    fail-closed signal and route to HIL, never swallow it into an
    eligible outcome. Also raises :class:`ValueError` on an out-of-range
    threshold.
    """
    if not 0.0 <= sample_threshold <= 1.0:
        raise ValueError(f"sample_threshold MUST be in [0.0, 1.0], got {sample_threshold}")
    if not 0.0 <= stability_threshold <= 1.0:
        raise ValueError(f"stability_threshold MUST be in [0.0, 1.0], got {stability_threshold}")
    if aggregate_confidence >= sample_threshold:
        return CascadeDecision(should_sample=False, stable=None, result=None)
    result = await sampler.sample(candidate)
    return CascadeDecision(
        should_sample=True,
        stable=result.stability >= stability_threshold,
        result=result,
    )


__all__ = [
    "STABILITY_SIGNAL_KEY",
    "CascadeDecision",
    "SelfConsistencyResult",
    "SelfConsistencySampler",
    "compute_stability",
    "run_consistency_cascade",
]
