"""Simulation-fidelity ledger - measure what-if predictions against reality.

The Assurance Twin and the detectors make **predictions**: a what-if says
"disabling public access on this resource changes N dependencies", a cost
advisor says "this resize saves $M/month", a forecaster says "the breach
lands in H hours". Autonomy leans on those predictions, but nothing today
measures whether they came true. An unmeasured predictor is an oracle -
exactly what the architecture forbids.

`SimulationFidelityLedger` closes that loop. It joins a **predicted**
value with the **actual** observed value (by a stable prediction id) and
accumulates per-key error statistics:

- **MAE** - mean absolute error.
- **MAPE** - mean absolute percentage error (the scale-free accuracy).
- **within-tolerance rate** - the fraction of predictions whose relative
  error was inside a configured tolerance band.

`is_reliable` turns those into a promotion signal: a predictor with
enough samples and a low-enough MAPE may stay in enforce; one that drifts
past the bar fails the check and the caller demotes it back to shadow
(the same shadow-before-enforce discipline the rest of the loop uses).

Deterministic and I/O-free (only stdlib), so it stays under the ``core/``
import rule. Matching is memory-bounded via an LRU-capped pending map so a
long-lived process cannot leak.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FidelityStat:
    """Accuracy of one predictor key over its matched predictions."""

    key: str
    samples: int
    mae: float
    mape: float
    within_tolerance_rate: float


@dataclass
class SimulationFidelityLedger:
    """Join predicted vs actual values and score per-key fidelity.

    ``tolerance`` is the relative-error band for the within-tolerance
    rate (0.2 == within 20% of actual counts as accurate).
    """

    tolerance: float = 0.2
    max_pending: int = 100_000
    # pending prediction id -> (side, value, key); key is "" for an actual.
    _pending: OrderedDict[str, tuple[str, float, str]] = field(default_factory=OrderedDict)
    _samples: dict[str, int] = field(default_factory=dict)
    _sum_abs_err: dict[str, float] = field(default_factory=dict)
    _sum_pct_err: dict[str, float] = field(default_factory=dict)
    _within: dict[str, int] = field(default_factory=dict)
    evicted: int = 0

    def __post_init__(self) -> None:
        if not 0.0 < self.tolerance <= 1.0:
            raise ValueError("tolerance MUST be in (0, 1]")
        if self.max_pending < 1:
            raise ValueError("max_pending MUST be >= 1")

    def record_prediction(self, prediction_id: str, *, key: str, predicted: float) -> None:
        """Record a prediction awaiting its actual outcome."""
        if not prediction_id:
            return
        existing = self._pending.get(prediction_id)
        if existing is not None and existing[0] == "actual":
            self._join(key, predicted=predicted, actual=existing[1])
            del self._pending[prediction_id]
            return
        self._pending[prediction_id] = ("prediction", predicted, key)
        self._pending.move_to_end(prediction_id)
        self._evict_if_needed()

    def record_actual(self, prediction_id: str, *, actual: float) -> None:
        """Record the observed outcome; joins if the prediction is pending."""
        if not prediction_id:
            return
        existing = self._pending.get(prediction_id)
        if existing is not None and existing[0] == "prediction":
            self._join(existing[2], predicted=existing[1], actual=actual)
            del self._pending[prediction_id]
            return
        self._pending[prediction_id] = ("actual", actual, "")
        self._pending.move_to_end(prediction_id)
        self._evict_if_needed()

    def _join(self, key: str, *, predicted: float, actual: float) -> None:
        if not key:
            key = "_unkeyed"
        abs_err = abs(predicted - actual)
        if actual != 0.0:
            pct_err = abs_err / abs(actual)
        else:
            pct_err = 0.0 if predicted == 0.0 else 1.0
        self._samples[key] = self._samples.get(key, 0) + 1
        self._sum_abs_err[key] = self._sum_abs_err.get(key, 0.0) + abs_err
        self._sum_pct_err[key] = self._sum_pct_err.get(key, 0.0) + pct_err
        if pct_err <= self.tolerance:
            self._within[key] = self._within.get(key, 0) + 1

    def _evict_if_needed(self) -> None:
        while len(self._pending) > self.max_pending:
            self._pending.popitem(last=False)
            self.evicted += 1

    def stat(self, key: str) -> FidelityStat | None:
        n = self._samples.get(key)
        if not n:
            return None
        return FidelityStat(
            key=key,
            samples=n,
            mae=self._sum_abs_err[key] / n,
            mape=self._sum_pct_err[key] / n,
            within_tolerance_rate=self._within.get(key, 0) / n,
        )

    def report(self) -> dict[str, FidelityStat]:
        stats: dict[str, FidelityStat] = {}
        for key in self._samples:
            stat = self.stat(key)
            if stat is not None:
                stats[key] = stat
        return stats

    def is_reliable(self, key: str, *, min_samples: int, max_mape: float) -> bool:
        """True when a predictor has enough samples and low-enough MAPE.

        A predictor below ``min_samples`` is not yet judgeable and returns
        ``False`` (fail closed - do not promote on a thin record).
        """
        stat = self.stat(key)
        if stat is None or stat.samples < min_samples:
            return False
        return stat.mape <= max_mape


__all__ = ["FidelityStat", "SimulationFidelityLedger"]
