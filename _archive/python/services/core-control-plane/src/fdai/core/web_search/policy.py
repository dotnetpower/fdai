"""decide_web_search - the pure policy for *when* T2 may call web search.

Web search is the last-resort tool per
``docs/roadmap/decisioning/prompt-composition.md`` section Web search policy.
That policy was prose only; this module makes it a testable,
deterministic function, mirroring
:mod:`fdai.core.quality_gate.escalation_ladder` and
:mod:`fdai.core.quality_gate.debate_router` - a frozen config plus a
stateless decision - so "when does web search run?" is answered by code
and recorded in the audit log, not asserted in a doc.

The invariants encoded here (all MUST):

- **Deny-by-default.** ``enabled`` defaults ``False`` - web search is
  opt-in per fork (the upstream provider is
  :class:`~fdai.core.web_search.provider.NoOpWebSearchProvider`).
- **T2 only.** A mini / narrator-T1 turn never searches; only a case that
  reached the reasoning tier (``is_reasoning_tier``) is eligible. This is
  the "models above the mini tier" boundary.
- **Grounding gap required.** Web search never *grounds* an action - the
  action's ``cited_rule_ids`` MUST still resolve to the rule catalog. It
  runs only when the deterministic grounding left an open gap the
  reasoner could not close from the catalog.
- **Novelty gated.** Routine cases the tiers already resolve do not pay
  for an outbound fetch; ``novelty_score`` MUST clear a threshold.
- **Budget bounded.** Per-event query and cost budgets MUST have headroom;
  overflow degrades to SKIP (and the caller to HIL), never to an
  unbounded fan-out of fetches.
- **Fail closed.** Any missing precondition returns
  :attr:`WebSearchRoute.SKIP` with a reason; the function never returns a
  third value and never grants execution eligibility (a snippet is
  untrusted data re-checked by the verifier).

Deterministic: same inputs -> same route and reason; no wall-clock, no
randomness, so an audited web-search decision replays identically.
``core/``-safe: stdlib only, no ``delivery.*`` import, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WebSearchRoute(StrEnum):
    """Policy verdict handed back to the caller.

    :attr:`SEARCH` means "the web-search tool may run for this event";
    :attr:`SKIP` means "do not search - proceed without a snippet layer,
    routing to HIL if the reasoner cannot resolve the case otherwise".
    """

    SEARCH = "search"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class WebSearchPolicyConfig:
    """Thresholds the web-search policy enforces.

    ``enabled`` is the master killswitch and defaults ``False`` so an
    upstream deployment never searches until a fork opts in.

    ``novelty_threshold`` is the minimum novelty score a case needs; below
    it the deterministic / lightweight tiers are assumed sufficient.

    ``require_grounding_gap`` (default ``True``) forces the "not a
    grounding source" rule: search only fires when grounding left an open
    gap. A fork MAY relax it, but the snippet still never satisfies
    ``cited_rule_ids``.

    ``min_query_budget`` / ``min_cost_budget_usd`` are the per-event
    headroom floors; at or below them the policy SKIPs.
    """

    enabled: bool = False
    novelty_threshold: float = 0.7
    require_grounding_gap: bool = True
    min_query_budget: int = 1
    min_cost_budget_usd: float = 0.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.novelty_threshold <= 1.0):
            raise ValueError("novelty_threshold MUST be in [0.0, 1.0]")
        if self.min_query_budget < 0:
            raise ValueError("min_query_budget MUST be >= 0")
        if self.min_cost_budget_usd < 0.0:
            raise ValueError("min_cost_budget_usd MUST be >= 0.0")


@dataclass(frozen=True, slots=True)
class WebSearchSignals:
    """Per-event inputs the policy reads.

    ``is_reasoning_tier`` is the mini boundary: ``True`` only for a T2 /
    Chat-T2 turn. ``grounding_gap`` is ``True`` when the deterministic
    grounding could not fully satisfy the case from the rule catalog.
    ``allowlist_has_web_search`` is whether the capability's tool
    allowlist names ``web.search``. ``provider_available`` is ``False``
    for the no-op provider (or an unbound fork), forcing SKIP.
    """

    is_reasoning_tier: bool
    novelty_score: float
    grounding_gap: bool
    allowlist_has_web_search: bool
    provider_available: bool
    query_budget_remaining: int
    cost_budget_remaining_usd: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.novelty_score <= 1.0):
            raise ValueError("novelty_score MUST be in [0.0, 1.0]")


@dataclass(frozen=True, slots=True)
class WebSearchDecision:
    """Structured record for the audit log and the caller."""

    route: WebSearchRoute
    reason: str

    @property
    def should_search(self) -> bool:
        return self.route is WebSearchRoute.SEARCH


def _skip(reason: str) -> WebSearchDecision:
    return WebSearchDecision(route=WebSearchRoute.SKIP, reason=reason)


def decide_web_search(
    config: WebSearchPolicyConfig,
    signals: WebSearchSignals,
) -> WebSearchDecision:
    """Decide whether the web-search tool may run for one event.

    Gates are evaluated deny-first: the earliest failing precondition
    determines the SKIP reason, so the audit log names exactly why a
    search did not run.
    """

    if not config.enabled:
        return _skip("web_search_disabled")
    if not signals.provider_available:
        return _skip("no_provider")
    if not signals.allowlist_has_web_search:
        return _skip("capability_not_allowlisted")
    if not signals.is_reasoning_tier:
        return _skip("not_reasoning_tier")
    if signals.query_budget_remaining < config.min_query_budget:
        return _skip("query_budget_exhausted")
    if signals.cost_budget_remaining_usd <= config.min_cost_budget_usd:
        return _skip("cost_budget_exhausted")
    if config.require_grounding_gap and not signals.grounding_gap:
        return _skip("grounded_no_gap")
    if signals.novelty_score < config.novelty_threshold:
        return _skip("below_novelty_threshold")
    return WebSearchDecision(
        route=WebSearchRoute.SEARCH,
        reason="novel_reasoning_tier_grounding_gap",
    )


__all__ = [
    "WebSearchDecision",
    "WebSearchPolicyConfig",
    "WebSearchRoute",
    "WebSearchSignals",
    "decide_web_search",
]
