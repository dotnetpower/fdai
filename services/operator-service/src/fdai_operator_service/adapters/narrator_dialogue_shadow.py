"""Shadow dialogue-state compaction for the service-local narrator.

The state is computed beside the existing history truncation and never changes the model request.
Only content-free counts reach the response receipt; the full state is retained in the
principal-scoped snapshot store when one is configured. A storage failure is logged and ignored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.dialogue_state import (
    DialogueRole,
    DialogueState,
    DialogueTurn,
    compact_dialogue,
)

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.postgres_dialogue_snapshot import DialogueSnapshotStoreError

_LOGGER = logging.getLogger(__name__)
_MAX_CONVERSATION_ID_CHARS = 256


class DialogueSnapshotWriter(Protocol):
    """Append a derived snapshot; ``False`` means a duplicate or nothing compacted."""

    async def append(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        state: DialogueState,
        recorded_at: datetime,
    ) -> bool: ...


def shadow_dialogue_state(history: Sequence[tuple[str, str]], *, kept: int) -> DialogueState:
    """Account for every history turn the request does not carry verbatim (T0, no T1 binding)."""

    turns = [
        DialogueTurn(turn_id=f"history:{index}", role=DialogueRole(role), content=content)
        for index, (role, content) in enumerate(history)
    ]
    return compact_dialogue(turns, keep_recent=kept, fallback_reason="t1_unconfigured")


def dialogue_shadow_receipt(state: DialogueState) -> JsonObject:
    """Return counts and digests only; no turn text or anchor value."""

    return {
        "mode": "shadow",
        "tier": state.tier,
        "source_turns": state.source_turn_count,
        "compacted_turns": len(state.compacted_turn_ids),
        "kept_turns": len(state.kept_turn_ids),
        "compacted_digest": state.compacted_digest,
        "fallback_reason": state.fallback_reason,
    }


async def retain_dialogue_shadow(
    writer: DialogueSnapshotWriter | None,
    *,
    principal_id: str,
    conversation_id: object,
    state: DialogueState,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Best-effort retention that never fails or alters the narrator turn."""

    if (
        writer is None
        or not state.compacted_turn_ids
        or not isinstance(conversation_id, str)
        or not 1 <= len(conversation_id.strip()) <= _MAX_CONVERSATION_ID_CHARS
    ):
        return
    try:
        await writer.append(
            principal_id=principal_id,
            conversation_id=conversation_id.strip(),
            state=state,
            recorded_at=clock(),
        )
    except DialogueSnapshotStoreError:
        _LOGGER.warning("dialogue_snapshot_retention_failed", exc_info=True)


__all__ = [
    "DialogueSnapshotWriter",
    "dialogue_shadow_receipt",
    "retain_dialogue_shadow",
    "shadow_dialogue_state",
]
