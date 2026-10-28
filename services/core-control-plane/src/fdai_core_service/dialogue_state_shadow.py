"""Off-path dialogue-state shadow for one Core semantic turn.

Core keeps only the newest adaptive-history window verbatim. The shadow accounts for the older
prior turns as a T0 ``DialogueState`` and logs content-free counts. When the Operator delivered its
own state, the shadow also records whether it matches Core's independent accounting. It never
changes the active turn: it calls no model (T1 or T2) and grants no authority.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fdai_service_contracts.dialogue_state import DIALOGUE_VERBATIM_WINDOW, DialogueState
from fdai_service_contracts.semantic_turn import SemanticPriorTurn, compact_prior_turns

_LOGGER = logging.getLogger(__name__)
ADAPTIVE_HISTORY_WINDOW = DIALOGUE_VERBATIM_WINDOW


@dataclass(frozen=True, slots=True)
class DialogueStateShadow:
    """Compute the candidate state beside the active truncation."""

    def observe(
        self,
        *,
        session_id: str,
        prior_turns: Sequence[SemanticPriorTurn],
        delivered: DialogueState | None = None,
    ) -> DialogueState | None:
        """Return Core's own accounting; ``None`` when nothing is compacted or it failed."""

        try:
            state = compact_prior_turns(session_id, tuple(prior_turns))
        except ValueError:
            _LOGGER.warning("dialogue_state_shadow_failed", exc_info=True)
            return None
        if state is None:
            return None
        _LOGGER.info(
            "dialogue_state_shadow",
            extra={
                "tier": state.tier,
                "source_turns": state.source_turn_count,
                "compacted_turns": len(state.compacted_turn_ids),
                "kept_turns": len(state.kept_turn_ids),
                "fallback_reason": state.fallback_reason,
                "delivered": delivered is not None,
                "delivered_matches": (
                    None
                    if delivered is None
                    else delivered.compacted_digest == state.compacted_digest
                    and delivered.compacted_turn_ids == state.compacted_turn_ids
                ),
            },
        )
        return state


__all__ = ["ADAPTIVE_HISTORY_WINDOW", "DialogueStateShadow"]
