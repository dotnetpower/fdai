"""Off-path dialogue-state shadow for one Core semantic turn.

Core keeps only the newest adaptive-history window verbatim. The shadow accounts for the older
prior turns as a T0 ``DialogueState`` and logs content-free counts. It never changes the active
turn: a failure is logged and ignored, and no model (T1 or T2) is called.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fdai_service_contracts.dialogue_state import (
    DialogueRole,
    DialogueState,
    DialogueTurn,
    compact_dialogue,
)
from fdai_service_contracts.semantic_turn import SemanticPriorTurn

_LOGGER = logging.getLogger(__name__)
ADAPTIVE_HISTORY_WINDOW = 8
"""Verbatim history window of the adaptive conversation path."""


@dataclass(frozen=True, slots=True)
class DialogueStateShadow:
    """Compute the candidate state beside the active truncation."""

    keep_recent: int = ADAPTIVE_HISTORY_WINDOW

    def observe(
        self, *, session_id: str, prior_turns: Sequence[SemanticPriorTurn]
    ) -> DialogueState | None:
        """Return the candidate state; ``None`` when nothing is compacted or it failed."""

        try:
            state = compact_dialogue(
                [
                    DialogueTurn(
                        turn_id=f"{session_id}:prior:{index}",
                        role=DialogueRole(turn.role),
                        content=turn.content,
                    )
                    for index, turn in enumerate(prior_turns)
                ],
                keep_recent=self.keep_recent,
                fallback_reason="t1_unconfigured",
            )
        except ValueError:
            _LOGGER.warning("dialogue_state_shadow_failed", exc_info=True)
            return None
        if not state.compacted_turn_ids:
            return None
        _LOGGER.info(
            "dialogue_state_shadow",
            extra={
                "tier": state.tier,
                "source_turns": state.source_turn_count,
                "compacted_turns": len(state.compacted_turn_ids),
                "kept_turns": len(state.kept_turn_ids),
                "fallback_reason": state.fallback_reason,
            },
        )
        return state


__all__ = ["ADAPTIVE_HISTORY_WINDOW", "DialogueStateShadow"]
