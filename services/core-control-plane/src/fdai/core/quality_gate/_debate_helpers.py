"""Optional disagreement debate routing for QualityGate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.core.quality_gate.debate import DebateOrchestrator
    from fdai.core.quality_gate.debate_router import DebateRouterConfig
    from fdai.core.quality_gate.gate import QualityCandidate


@dataclass(frozen=True, slots=True)
class DebateResolution:
    resolved: bool
    reasons: tuple[str, ...]


async def resolve_disagreement(
    *,
    candidate: QualityCandidate,
    orchestrator: DebateOrchestrator | None,
    router_config: DebateRouterConfig | None,
    first_proposer_output: tuple[str, Mapping[str, Any]] | None,
    known_rule_ids: set[str],
    retry_proposer: Callable[[QualityCandidate, str], Awaitable[tuple[str, Mapping[str, Any]]]],
) -> DebateResolution:
    if orchestrator is None or router_config is None or first_proposer_output is None:
        return DebateResolution(False, ())

    from fdai.core.quality_gate.debate import DebateVerdict
    from fdai.core.quality_gate.debate_router import DebateRoute, decide_debate_route

    router_decision = decide_debate_route(
        candidate=candidate,
        cross_check_disagreed=True,
        orchestrator_available=True,
        config=router_config,
    )
    reasons = [f"debate_route:{router_decision.route.value}:{router_decision.reason}"]
    if router_decision.route is not DebateRoute.DEBATE:
        return DebateResolution(False, tuple(reasons))
    outcome = await orchestrator.run(
        candidate=candidate,
        proposer_output=first_proposer_output,
        known_rule_ids=known_rule_ids,
        retry_proposer=retry_proposer,
    )
    reasons.append(f"debate_outcome:{outcome.verdict.value}:{outcome.reason}")
    return DebateResolution(outcome.verdict is DebateVerdict.PROCEED, tuple(reasons))
