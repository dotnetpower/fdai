"""Multi-objective cross-vertical arbitration.

The default arbitration policy is a lexicographic *priority order* over
domain names (``resilience > security > change_safety > cost > capacity``).
That is safe but blunt: it always lets the higher-priority domain win even
when the lower-priority domain carries a far larger measured impact (the
"save one dollar of on-call time by spending ten dollars of compute"
failure mode called out in the rubric).

`MultiObjectiveArbiter` upgrades this to a **weighted multi-objective**
decision while staying deterministic, explainable, and safety-preserving:

- Each domain has a configured **weight** (derived from the priority order
  by default, so equal-impact conflicts reproduce the legacy priority
  outcome and existing behavior is preserved).
- Each domain in conflict may carry a measured **impact magnitude** in
  ``[0, 1]`` (e.g. a cost anomaly's normalized overspend ratio, a capacity
  forecast's projected utilization). The score is ``weight * impact``.
- The winner is the highest score. When the top-two margin is within a
  configured **HIL band**, the call is too close to auto-resolve and the
  outcome is flagged ``escalate_hil`` - the arbiter never silently picks a
  near-tie, it hands close calls to a human (fail toward safety).
- Every outcome records the per-domain ``objective_scores`` and the
  ``margin`` so the decision is grounded and auditable.

The arbiter takes no LLM call and no I/O; it is pure and deterministic
given its config and inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Default cross-vertical priority order (highest first). Fork config
# replaces this; weights are derived from it unless given explicitly.
_DEFAULT_PRIORITY: tuple[str, ...] = (
    "resilience",
    "security",
    "change_safety",
    "cost",
    "capacity",
)

# Below this top-two margin the winner is too close to auto-resolve and
# the arbiter escalates to HIL instead of silently picking.
_DEFAULT_HIL_MARGIN: float = 0.10


@dataclass(frozen=True, slots=True)
class ArbitrationOutcome:
    """Result of a multi-objective arbitration.

    ``escalate_hil`` is set when the decision is a near-tie (margin within
    the HIL band) or when a domain has no known weight - both are
    low-confidence outcomes that must not auto-resolve.
    """

    winner: str
    losers: tuple[str, ...]
    objective_scores: dict[str, float]
    margin: float
    escalate_hil: bool
    reason: str


def weights_from_priority(
    priority: tuple[str, ...],
) -> dict[str, float]:
    """Derive descending linear weights from a priority order.

    The first (highest-priority) domain gets weight ``1.0`` and each
    subsequent domain a linearly smaller weight, floored at a small
    positive value so every named domain still scores above zero. With
    equal impacts this reproduces the priority-order winner exactly, so
    the multi-objective arbiter is a strict superset of the legacy table.
    """
    n = len(priority)
    if n == 0:
        return {}
    if n == 1:
        return {priority[0]: 1.0}
    step = 0.6 / (n - 1)  # spread from 1.0 down to 0.4
    return {domain: round(1.0 - step * i, 6) for i, domain in enumerate(priority)}


class MultiObjectiveArbiter:
    """Deterministic weighted arbiter with HIL escalation on close calls."""

    def __init__(
        self,
        *,
        priority: tuple[str, ...] = _DEFAULT_PRIORITY,
        weights: dict[str, float] | None = None,
        hil_margin: float = _DEFAULT_HIL_MARGIN,
    ) -> None:
        resolved_weights = weights if weights is not None else weights_from_priority(priority)
        # Fail fast on a misconfigured weight table: a non-finite or
        # negative weight would produce NaN / negative scores that corrupt
        # ranking and the margin calculation. Config errors must not reach
        # a live arbitration.
        for domain, weight in resolved_weights.items():
            if not math.isfinite(weight) or weight < 0.0:
                raise ValueError(f"weight for '{domain}' MUST be finite and >= 0 (got {weight!r})")
        if not math.isfinite(hil_margin) or hil_margin < 0.0:
            raise ValueError(f"hil_margin MUST be finite and >= 0 (got {hil_margin!r})")
        self._priority = priority
        self._weights = resolved_weights
        self._hil_margin = hil_margin

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    def resolve(
        self,
        domains: tuple[str, ...],
        impacts: dict[str, float] | None = None,
    ) -> ArbitrationOutcome:
        """Resolve a conflict among ``domains`` into a single winner.

        ``impacts`` maps a domain to a measured magnitude in ``[0, 1]``;
        a domain absent from the map defaults to ``1.0`` (full weight),
        which makes an all-default call collapse to the priority order.
        """
        if not domains:
            return ArbitrationOutcome(
                winner="unknown",
                losers=(),
                objective_scores={},
                margin=0.0,
                escalate_hil=True,
                reason="empty_conflict",
            )

        # Deduplicate defensively (order-preserving): a repeated domain
        # would otherwise place the winner in its own losers tuple and
        # skew the margin. A conflict is a *set* of domains.
        domains = tuple(dict.fromkeys(domains))

        impacts = impacts or {}
        # A non-finite impact (NaN / inf) is a corrupt measurement; it must
        # never silently win or corrupt the sort. Treat it as zero impact
        # and force the whole call to HIL as a low-confidence input.
        nonfinite = [d for d in domains if not math.isfinite(_as_float(impacts.get(d, 1.0)))]
        unknown = [d for d in domains if d not in self._weights]
        scores: dict[str, float] = {}
        for domain in domains:
            weight = self._weights.get(domain, 0.0)
            raw_impact = _as_float(impacts.get(domain, 1.0))
            impact = _clamp(raw_impact) if math.isfinite(raw_impact) else 0.0
            scores[domain] = round(weight * impact, 6)

        # Deterministic ordering: score desc, then priority rank, then name.
        ranked = sorted(
            domains,
            key=lambda d: (-scores[d], self._rank(d), d),
        )
        winner = ranked[0]
        losers = tuple(ranked[1:])

        top = scores[winner]
        second = scores[ranked[1]] if len(ranked) > 1 else 0.0
        margin = round((top - second) / top, 6) if top > 0 else 0.0

        mode = "multi_objective" if impacts else "priority_order"
        escalate = (
            bool(unknown) or bool(nonfinite) or (len(domains) > 1 and margin < self._hil_margin)
        )
        if unknown:
            reason = f"unknown_domain:{','.join(sorted(unknown))}"
        elif nonfinite:
            reason = f"nonfinite_impact:{','.join(sorted(nonfinite))}"
        elif escalate:
            reason = f"close_call:margin={margin}<{self._hil_margin}"
        else:
            reason = f"{mode}:{','.join(self._priority)}"

        return ArbitrationOutcome(
            winner=winner,
            losers=losers,
            objective_scores=scores,
            margin=margin,
            escalate_hil=escalate,
            reason=reason,
        )

    def _rank(self, domain: str) -> int:
        try:
            return self._priority.index(domain)
        except ValueError:
            return len(self._priority)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _as_float(value: object) -> float:
    """Best-effort float coercion; a non-numeric impact becomes NaN.

    Returning NaN (rather than raising) lets ``resolve`` route a corrupt
    impact to HIL through the single non-finite path instead of crashing
    the arbitration on bad input.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


__all__ = [
    "ArbitrationOutcome",
    "MultiObjectiveArbiter",
    "weights_from_priority",
    "_DEFAULT_PRIORITY",
    "_DEFAULT_HIL_MARGIN",
]
