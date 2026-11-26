"""DebateRouter - decide when a T2 event routes to the debate loop.

The default T2 path is the two-model cross-check quorum documented in
:mod:`fdai.core.quality_gate.gate`. The Wave 4.5
:class:`~fdai.core.quality_gate.debate.DebateOrchestrator` is an
alternative path reserved for events where the extra Critic + Judge
round trip is worth its token cost - typically:

- The cross-check quorum **disagreed** (independent-model
  disagreement is the exact signal the debate loop is designed to
  resolve, per ``docs/roadmap/decisioning/prompt-composition.md § Debate
  orchestrator``).
- The candidate's **action_type** is explicitly opted-in to always
  debate (a fork's high-severity allowlist).

Wave 4.5 delta-2a ships only the **pure policy** - a frozen config +
a stateless function that answers "should this candidate route
through the debate orchestrator?". No live wiring into
:class:`QualityGate`; the caller decides how to act on the boolean
verdict. Wave 4.5 delta-2b will thread the router through the gate.

Design invariants
-----------------
- **Fail-closed.** When the orchestrator is not available (a fork
  that did not resolve both Critic + Judge capabilities), the router
  MUST return :attr:`DebateRoute.SKIP` - never a truthy verdict on
  an unbound orchestrator. The caller passes the availability signal
  as ``orchestrator_available``.
- **Cost-bounded.** The router MUST NOT trigger the debate when the
  config disables it (``enabled=False``) - a killswitch a fork can
  flip in an outage without a code change.
- **Deterministic.** Same inputs return the same verdict; no wall-
  clock reads, no randomness.
- **``core/``-safe.** Imports only from
  :mod:`fdai.core.quality_gate.gate` and stdlib. No
  ``delivery.*`` import, no LLM SDK.

See also
--------
- ``docs/roadmap/decisioning/prompt-composition.md`` § Wave 4.5 delta-2 - what shipped
- ``docs/roadmap/decisioning/prompt-composition.md`` § Debate orchestrator
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from fdai.core.quality_gate.gate import QualityCandidate


class DebateRoute(StrEnum):
    """Router verdict handed back to the caller.

    :attr:`DEBATE` says "spend the Critic + Judge tokens"; :attr:`SKIP`
    says "the default cross-check quorum is enough for this event".
    The router never returns a third value - unavailable orchestrator
    collapses to :attr:`SKIP`, matching the fail-closed rule.
    """

    DEBATE = "debate"
    """Route this candidate through the debate orchestrator."""

    SKIP = "skip"
    """Fall back to the default cross-check quorum path."""


@dataclass(frozen=True, slots=True)
class DebateRouterConfig:
    """Thresholds + opt-in lists the router enforces.

    ``enabled`` is the master killswitch - when ``False`` the router
    returns :attr:`DebateRoute.SKIP` unconditionally, no matter how
    the other axes look. A fork uses this to abort debate during a
    cost spike without deploying new code.

    ``on_cross_check_disagreement`` (default ``True``) is the primary
    routing signal: cross-check quorum couldn't converge, so the
    debate is the escalation path.

    ``always_for_action_types`` is a per-ActionType allowlist that
    forces debate regardless of the disagreement signal. Kept as a
    tuple so equality-friendly and cheap to snapshot into audit
    entries; empty tuple means "no forced allowlist".

    ``never_for_action_types`` is the counterpart denylist - useful
    for cheap idempotent actions (e.g. ``rule.tag-add``) where the
    Critic + Judge cost outweighs any accuracy gain. Denylist wins
    over allowlist (a defect a fork can catch at review time is
    better than a silently uncovered edge case).
    """

    enabled: bool = True
    on_cross_check_disagreement: bool = True
    always_for_action_types: tuple[str, ...] = ()
    never_for_action_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        overlap = set(self.always_for_action_types) & set(self.never_for_action_types)
        if overlap:
            raise ValueError(
                "DebateRouterConfig: always/never allowlists MUST be disjoint; "
                f"overlap={sorted(overlap)!r}"
            )


@dataclass(frozen=True, slots=True)
class DebateRoutingDecision:
    """Structured record for the audit log and the caller.

    ``reason`` names the axis that produced the verdict (e.g.
    ``"cross_check_disagreement"``, ``"never_list"``, ``"disabled"``)
    so an operator inspecting the audit trail can reconstruct the
    routing choice without re-running the policy.
    """

    route: DebateRoute
    reason: str
    action_type: str
    """The candidate's action_type at decision time, snapshotted so a
    future ActionType rename does not break the audit trail."""

    metadata: dict[str, str] = field(default_factory=dict)


_REASON_DISABLED: Final[str] = "disabled"
_REASON_ORCH_UNAVAILABLE: Final[str] = "orchestrator_unavailable"
_REASON_NEVER_LIST: Final[str] = "never_list"
_REASON_ALWAYS_LIST: Final[str] = "always_list"
_REASON_DISAGREEMENT: Final[str] = "cross_check_disagreement"
_REASON_DEFAULT_SKIP: Final[str] = "default_skip"


def decide_debate_route(
    *,
    candidate: QualityCandidate,
    cross_check_disagreed: bool,
    orchestrator_available: bool,
    config: DebateRouterConfig | None = None,
) -> DebateRoutingDecision:
    """Return the routing verdict for one T2 event.

    Precedence (top wins, short-circuit):

    1. ``orchestrator_available=False`` -> SKIP with reason
       ``orchestrator_unavailable`` (fail-closed).
    2. ``config.enabled=False`` -> SKIP with reason ``disabled``
       (killswitch).
    3. Candidate ``action_type`` in ``never_for_action_types``
       -> SKIP with reason ``never_list`` (denylist wins over
       allowlist - a defect a fork can catch at review time is
       better than a silent surprise).
    4. Candidate ``action_type`` in ``always_for_action_types``
       -> DEBATE with reason ``always_list``.
    5. ``cross_check_disagreed=True`` AND
       ``on_cross_check_disagreement=True`` -> DEBATE with reason
       ``cross_check_disagreement`` (the primary trigger).
    6. Fallback -> SKIP with reason ``default_skip``.
    """

    effective_config = config or DebateRouterConfig()
    action_type = candidate.action_type

    if not orchestrator_available:
        return DebateRoutingDecision(
            route=DebateRoute.SKIP,
            reason=_REASON_ORCH_UNAVAILABLE,
            action_type=action_type,
        )
    if not effective_config.enabled:
        return DebateRoutingDecision(
            route=DebateRoute.SKIP,
            reason=_REASON_DISABLED,
            action_type=action_type,
        )
    if action_type in effective_config.never_for_action_types:
        return DebateRoutingDecision(
            route=DebateRoute.SKIP,
            reason=_REASON_NEVER_LIST,
            action_type=action_type,
        )
    if action_type in effective_config.always_for_action_types:
        return DebateRoutingDecision(
            route=DebateRoute.DEBATE,
            reason=_REASON_ALWAYS_LIST,
            action_type=action_type,
        )
    if cross_check_disagreed and effective_config.on_cross_check_disagreement:
        return DebateRoutingDecision(
            route=DebateRoute.DEBATE,
            reason=_REASON_DISAGREEMENT,
            action_type=action_type,
        )
    return DebateRoutingDecision(
        route=DebateRoute.SKIP,
        reason=_REASON_DEFAULT_SKIP,
        action_type=action_type,
    )


__all__ = [
    "DebateRoute",
    "DebateRouterConfig",
    "DebateRoutingDecision",
    "decide_debate_route",
]
