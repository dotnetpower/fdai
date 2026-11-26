"""Learning bindings for Pantheon startup."""

from __future__ import annotations

from typing import cast

from fdai.agents import Norns, PantheonRuntime
from fdai.core.learning import RuleHintSubmitter
from fdai.core.readiness import DiscoveryActivationReport
from fdai.runtime.discovery_activation import DiscoveryActivationRuntime
from fdai.runtime.post_turn_review import PostTurnReviewRuntime


async def bind_post_turn_learning(
    *,
    pantheon_runtime: PantheonRuntime,
    post_turn_review: PostTurnReviewRuntime,
    discovery_activation: DiscoveryActivationRuntime,
) -> DiscoveryActivationReport | None:
    """Bind post-turn rule hints behind the current discovery activation decision."""

    norns = pantheon_runtime.agents.get("Norns")
    if norns is None:
        return None
    norns_agent = cast(Norns, norns)
    post_turn_review.bind_rule_hints(cast(RuleHintSubmitter, norns))
    norns_agent.bind_candidate_publication_gate(discovery_activation.is_enabled)
    discovery_activation.bind_shadow_decision_count(
        lambda: sum(pantheon_runtime.shadow_decisions.values())
    )
    return await discovery_activation.evaluate()


__all__ = ["bind_post_turn_learning"]
