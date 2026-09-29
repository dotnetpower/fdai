"""Off-path context-selection shadow comparison for one Core semantic turn."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from fdai.core.conversation.context_bridge import assemble_turn_context
from fdai.core.conversation.session import ConversationSession, Principal, Turn
from fdai.core.working_context.governance import ContextSelectionPolicyAuthority
from fdai.core.working_context.shadow import ContextSelectionShadowRunner
from fdai.core.working_context.types import ContextBudget

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticContextShadow:
    """Schedule a candidate context-selection comparison without changing the active turn.

    The active selection this assembles is discarded: the semantic runtime keeps its own context
    path, so the only effect is the bounded, off-path comparison that the composed runner persists.
    A failure is logged and never fails or alters the turn.
    """

    authority: ContextSelectionPolicyAuthority
    runner: ContextSelectionShadowRunner
    budget: ContextBudget = field(default_factory=ContextBudget)

    async def schedule(
        self,
        *,
        session_id: str,
        principal: Principal,
        utterance: str,
        prior_turns: Sequence[Turn],
    ) -> None:
        session = ConversationSession(
            session_id=session_id,
            principal=principal,
            channel_id="semantic-turn",
        )
        for turn in prior_turns:
            session.append(turn)
        try:
            await assemble_turn_context(
                session=session,
                utterance=utterance,
                budget=self.budget,
                policy_authority=self.authority,
                shadow_runner=self.runner,
            )
        except Exception:  # noqa: BLE001 - shadow evidence must not affect the active turn
            _LOGGER.warning("context_selection_shadow_schedule_failed", exc_info=True)


def build_semantic_context_shadow(
    authority: ContextSelectionPolicyAuthority | None,
    runner: ContextSelectionShadowRunner | None,
) -> SemanticContextShadow | None:
    """Return the shadow only when composition bound both the authority and the runner."""
    if authority is None or runner is None:
        return None
    return SemanticContextShadow(authority=authority, runner=runner)


__all__ = ["SemanticContextShadow", "build_semantic_context_shadow"]
