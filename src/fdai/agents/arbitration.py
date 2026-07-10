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
from collections.abc import Callable, Sequence
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


def weights_from_priority_curved(
    priority: tuple[str, ...],
    *,
    curve: str = "linear",
    convexity: float = 2.0,
) -> dict[str, float]:
    """Derive descending weights along a configurable curve.

    - ``linear`` reproduces :func:`weights_from_priority` exactly (the
      default, so the arbiter's default behavior does not change).
    - ``convex`` (``convexity > 1``) puts extra emphasis on the top
      priority: a higher-priority domain's weight advantage grows.
      Useful when the fork wants "resilience really is more important
      than everything else" without hard-coding it in code.
    - ``concave`` (``0 < convexity < 1``) flattens the spread so the top
      priority is not dominant. Useful when the fork wants closer-to-
      equal weights across verticals while still keeping priority-order
      tie-breaking.

    The curve is applied to a rank-normalized position ``t in [0, 1]``:
    weight = ``round(1.0 - 0.6 * t**convexity, 6)``. That preserves the
    top weight of ``1.0`` and the bottom weight of ``0.4`` used by the
    linear default, so the arbiter's HIL band and margin arithmetic stay
    calibrated regardless of curve choice. Equal-impact conflicts still
    reproduce the priority-order winner exactly.

    Both curve name and convexity are validated at call time so a
    misconfigured fork fails fast instead of silently reversing order.
    """
    n = len(priority)
    if n == 0:
        return {}
    if n == 1:
        return {priority[0]: 1.0}
    if curve == "linear":
        exponent = 1.0
    elif curve == "convex":
        if not math.isfinite(convexity) or convexity <= 1.0:
            raise ValueError(f"convex curve requires convexity > 1.0 (got {convexity!r})")
        exponent = convexity
    elif curve == "concave":
        if not math.isfinite(convexity) or not 0.0 < convexity < 1.0:
            raise ValueError(f"concave curve requires 0 < convexity < 1 (got {convexity!r})")
        exponent = convexity
    else:
        raise ValueError(f"unknown curve {curve!r} (expected 'linear', 'convex', or 'concave')")
    weights: dict[str, float] = {}
    for i, domain in enumerate(priority):
        t = i / (n - 1)
        weights[domain] = round(1.0 - 0.6 * (t**exponent), 6)
    return weights


class MultiObjectiveArbiter:
    """Deterministic weighted arbiter with HIL escalation on close calls."""

    def __init__(
        self,
        *,
        priority: tuple[str, ...] = _DEFAULT_PRIORITY,
        weights: dict[str, float] | None = None,
        weight_fn: Callable[[tuple[str, ...]], dict[str, float]] | None = None,
        hil_margin: float = _DEFAULT_HIL_MARGIN,
    ) -> None:
        # Config resolution: explicit ``weights`` wins (static override),
        # then a ``weight_fn`` (pluggable curve or fork-supplied learner
        # output that must still be a pure function of ``priority``), then
        # the linear default. Passing both is a config error - the intent
        # is ambiguous.
        if weights is not None and weight_fn is not None:
            raise ValueError("pass either 'weights' or 'weight_fn', not both")
        if weights is not None:
            resolved_weights = weights
        elif weight_fn is not None:
            resolved_weights = weight_fn(priority)
            if not isinstance(resolved_weights, dict):
                raise ValueError(
                    "weight_fn must return a dict[str, float] "
                    f"(got {type(resolved_weights).__name__})"
                )
        else:
            resolved_weights = weights_from_priority(priority)
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
        *,
        history: Sequence[RecentDecision] | None = None,
        policy: TemporalPolicy | None = None,
    ) -> ArbitrationOutcome:
        """Resolve a conflict among ``domains`` into a single winner.

        ``impacts`` maps a domain to a measured magnitude in ``[0, 1]``;
        a domain absent from the map defaults to ``1.0`` (full weight),
        which makes an all-default call collapse to the priority order.

        ``history`` + ``policy`` are optional; when both are supplied the
        policy adjusts the base weights *for this call only* before
        scoring. The arbiter re-validates the adjusted weights and still
        enforces HIL escalation on close margins, unknown domains, and
        non-finite impacts - a temporal policy MUST NOT weaken safety.
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

        # Apply the temporal policy (if any) at the boundary, then treat
        # the returned dict exactly the same as a static weights config.
        effective_weights = self._weights
        temporal_note = ""
        if policy is not None:
            adjusted = policy.adjust(
                base_weights=dict(self._weights),
                domains=domains,
                history=tuple(history or ()),
            )
            effective_weights = _validate_adjusted_weights(adjusted, policy_name=policy.name)
            if effective_weights != self._weights:
                temporal_note = f"|policy={policy.name}"

        impacts = impacts or {}
        # A non-finite impact (NaN / inf) is a corrupt measurement; it must
        # never silently win or corrupt the sort. Treat it as zero impact
        # and force the whole call to HIL as a low-confidence input.
        nonfinite = [d for d in domains if not math.isfinite(_as_float(impacts.get(d, 1.0)))]
        unknown = [d for d in domains if d not in effective_weights]
        scores: dict[str, float] = {}
        for domain in domains:
            weight = effective_weights.get(domain, 0.0)
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
            reason = f"close_call:margin={margin}<{self._hil_margin}{temporal_note}"
        else:
            reason = f"{mode}:{','.join(self._priority)}{temporal_note}"

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


# ---------------------------------------------------------------------------
# Temporal / stateful fairness (issue #4)
# ---------------------------------------------------------------------------
#
# The base ``MultiObjectiveArbiter.resolve`` is pure and stateless: it
# decides each conflict in isolation. That is safe, but it has two known
# failure modes on repeated conflicts:
#
# - **No temporal fairness** - if the same two domains conflict on the
#   same resource over and over, the higher-scoring domain wins every
#   round. There is no notion of "cost yielded last three times, so nudge
#   the weight toward capacity this round."
# - **No hysteresis / anti-flapping** - alternating signals can drive
#   opposite decisions on consecutive rounds with no damping, so a
#   marginal fluctuation flips the arbiter back and forth.
#
# A ``TemporalPolicy`` is a pure function of ``(base_weights, domains,
# history)`` that returns adjusted weights *before* the arbiter scores.
# The policy sees only what the caller passes; it never reads from
# storage. That keeps the arbiter deterministic (same history + same
# inputs -> same decision) and replayable (history is sourced from the
# append-only audit log, not from in-memory state that breaks scale-to-
# zero). The policy MUST NOT weaken the HIL safety net: the arbiter still
# escalates on close margins, unknown domains, and non-finite impacts
# even after adjustment.


@dataclass(frozen=True, slots=True)
class RecentDecision:
    """One replayable record of a past arbitration on a resource.

    Sourced from the append-only audit log by a ``DecisionHistory``
    seam. Carries only what a temporal policy needs to reason about;
    scores / margins are intentionally omitted so history stays cheap
    to load and cannot leak sensitive per-signal detail.
    """

    winner: str
    losers: tuple[str, ...]
    resource_id: str = ""
    at: float = 0.0  # unix timestamp; ordering only, absolute value unused


class TemporalPolicy:
    """Adjusts base weights given a bounded window of recent decisions.

    Concrete policies subclass and override :meth:`adjust`. The method
    MUST be pure (no I/O, no wall-clock reads) and MUST return a
    non-empty dict of ``{domain: weight}`` where every weight is finite
    and non-negative - the arbiter re-validates and rejects a malformed
    return value at call time, so a buggy policy cannot corrupt scoring.
    """

    name: str = "temporal_policy"

    def adjust(
        self,
        *,
        base_weights: dict[str, float],
        domains: tuple[str, ...],
        history: Sequence[RecentDecision],
    ) -> dict[str, float]:
        raise NotImplementedError


class AlternatingFairnessPolicy(TemporalPolicy):
    """Nudge weight toward a domain that has lost too many rounds in a row.

    Counts the current *winning streak* for the top-scoring candidate in
    ``domains`` on the same resource, looking only at the most recent
    contiguous suffix of decisions whose **winner AND at least one
    loser** are both in today's conflict set. A past ``cost vs
    resilience`` win does not count toward a cost streak in a
    ``cost vs capacity`` conflict - that would confuse global fairness
    with pair fairness, and issue #4 is about pair fairness.

    Once the streak reaches ``streak_threshold``, every other domain in
    the conflict gets a ``boost`` added to its weight; the perpetual
    winner's weight is unchanged. That reduces the score gap so the
    losing side has a chance to win the next round, without flipping the
    outcome silently on the very first repeat. Streak resets as soon as
    a different domain wins.

    The boost is bounded (``0 < boost <= 1.0``) so a fork cannot
    accidentally configure a runaway override; combined with the
    ``[0, 1]`` impact range and the priority-based base weights (top =
    ``1.0``), this keeps adjusted weights inside a sane band and
    preserves the HIL band arithmetic.
    """

    name = "alternating_fairness"

    def __init__(self, *, streak_threshold: int = 3, boost: float = 0.15) -> None:
        if streak_threshold < 2:
            raise ValueError(f"streak_threshold MUST be >= 2 (got {streak_threshold!r})")
        if not math.isfinite(boost) or boost <= 0:
            raise ValueError(f"boost MUST be finite and > 0 (got {boost!r})")
        if boost > 1.0:
            raise ValueError(
                f"boost MUST be <= 1.0 to keep adjusted weights within a sane "
                f"band; a larger override should raise the base weights instead "
                f"(got {boost!r})"
            )
        self._threshold = streak_threshold
        self._boost = boost

    def adjust(
        self,
        *,
        base_weights: dict[str, float],
        domains: tuple[str, ...],
        history: Sequence[RecentDecision],
    ) -> dict[str, float]:
        domain_set = set(domains)
        # Only count history entries where the past conflict overlaps the
        # current one on both sides - winner in domains AND at least one
        # loser in domains. Winner-only overlap would fold unrelated
        # arbitrations (e.g. cost vs resilience) into a cost streak
        # against capacity, which is a semantic drift from issue #4.
        relevant = [
            d
            for d in reversed(history)
            if d.winner in domain_set and any(loser in domain_set for loser in d.losers)
        ]
        if not relevant:
            return dict(base_weights)
        top = relevant[0].winner
        streak = 0
        for record in relevant:
            if record.winner == top:
                streak += 1
            else:
                break
        if streak < self._threshold:
            return dict(base_weights)
        adjusted = dict(base_weights)
        for domain in domains:
            if domain == top:
                continue
            current = adjusted.get(domain, 0.0)
            adjusted[domain] = current + self._boost
        return adjusted


class HysteresisPolicy(TemporalPolicy):
    """Dampen rapid oscillation by rewarding the incumbent winner.

    A conflict that flip-flops between two domains within the last
    ``window`` decisions is a flapping signal, not a stable preference.
    When the current conflict's domains match the flapping pair and the
    most recent winner appears in ``domains``, add ``bonus`` to its
    weight so a marginal input on the opposite side does not
    immediately flip the outcome again. A stable, one-sided run of
    winners is not flapping and receives no bonus.

    Pair-relevance matches :class:`AlternatingFairnessPolicy`: a past
    decision only counts when its winner AND at least one loser are in
    today's ``domains``. ``bonus`` is bounded (``0 < bonus <= 1.0``) so
    a fork cannot accidentally silence one side of the conflict.
    """

    name = "hysteresis"

    def __init__(self, *, window: int = 5, bonus: float = 0.10) -> None:
        if window < 2:
            raise ValueError(f"window MUST be >= 2 (got {window!r})")
        if not math.isfinite(bonus) or bonus <= 0:
            raise ValueError(f"bonus MUST be finite and > 0 (got {bonus!r})")
        if bonus > 1.0:
            raise ValueError(
                f"bonus MUST be <= 1.0 to keep adjusted weights within a sane band (got {bonus!r})"
            )
        self._window = window
        self._bonus = bonus

    def adjust(
        self,
        *,
        base_weights: dict[str, float],
        domains: tuple[str, ...],
        history: Sequence[RecentDecision],
    ) -> dict[str, float]:
        domain_set = set(domains)
        relevant = [
            d
            for d in reversed(history)
            if d.winner in domain_set and any(loser in domain_set for loser in d.losers)
        ][: self._window]
        if len(relevant) < 2:
            return dict(base_weights)
        winners_in_window = {d.winner for d in relevant}
        # Flapping only when the window has seen at least two distinct
        # winners from the current conflict set. A one-sided streak (all
        # cost) is handled by AlternatingFairnessPolicy, not here.
        if len(winners_in_window) < 2:
            return dict(base_weights)
        last_winner = relevant[0].winner
        adjusted = dict(base_weights)
        adjusted[last_winner] = adjusted.get(last_winner, 0.0) + self._bonus
        return adjusted


def _validate_adjusted_weights(adjusted: object, *, policy_name: str) -> dict[str, float]:
    """Fail-fast validation of a policy's return value.

    A buggy policy MUST NOT corrupt scoring: a non-dict, non-finite, or
    negative weight fails the arbitration at the boundary, which the
    caller treats as a HIL escalation (fail toward safety).
    """
    if not isinstance(adjusted, dict) or not adjusted:
        raise ValueError(
            f"temporal policy {policy_name!r} MUST return a non-empty dict "
            f"of {{domain: weight}} (got {type(adjusted).__name__})"
        )
    for domain, weight in adjusted.items():
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(
                f"temporal policy {policy_name!r} returned invalid weight "
                f"for '{domain}' (got {weight!r})"
            )
    return dict(adjusted)


__all__ = [
    "ArbitrationOutcome",
    "MultiObjectiveArbiter",
    "weights_from_priority",
    "weights_from_priority_curved",
    "RecentDecision",
    "TemporalPolicy",
    "AlternatingFairnessPolicy",
    "HysteresisPolicy",
    "_DEFAULT_PRIORITY",
    "_DEFAULT_HIL_MARGIN",
]
