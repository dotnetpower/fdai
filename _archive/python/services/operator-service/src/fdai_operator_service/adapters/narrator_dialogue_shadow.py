"""Shadow dialogue-state compaction for the service-local narrator.

The state is computed beside the existing history truncation and never changes the model request.
Only content-free counts reach the response receipt; the full state is retained in the
principal-scoped snapshot store when one is configured. A storage failure is logged and ignored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.dialogue_state import (
    DialogueRole,
    DialogueState,
    DialogueStateProposer,
    DialogueTurn,
    build_dialogue_state,
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


def history_dialogue_turns(history: Sequence[tuple[str, str]]) -> tuple[DialogueTurn, ...]:
    """Name each history turn by its position so the compacted range stays replayable."""

    return tuple(
        DialogueTurn(turn_id=f"history:{index}", role=DialogueRole(role), content=content)
        for index, (role, content) in enumerate(history)
    )


def shadow_dialogue_state(history: Sequence[tuple[str, str]], *, kept: int) -> DialogueState:
    """Account for every history turn the request does not carry verbatim (T0, no T1 binding)."""

    return compact_dialogue(
        history_dialogue_turns(history), keep_recent=kept, fallback_reason="t1_unconfigured"
    )


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


@dataclass(slots=True)
class DialogueStateRetention:
    """Retain shadow snapshots; run the optional T1 proposer off the answer path.

    The proposer call never delays the narrator answer: it runs in a tracked background task whose
    failure degrades to the typed T0 fallback and is never raised into the turn.
    """

    writer: DialogueSnapshotWriter | None
    proposer: DialogueStateProposer | None = None
    _tasks: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)

    async def retain(
        self,
        *,
        principal_id: str,
        conversation_id: object,
        state: DialogueState,
        turns: Sequence[DialogueTurn],
    ) -> bool:
        """Retain now, or schedule T1 first; return whether a T1 proposal was scheduled."""

        if self.writer is None or not state.compacted_turn_ids:
            return False
        if self.proposer is None:
            await retain_dialogue_shadow(
                self.writer,
                principal_id=principal_id,
                conversation_id=conversation_id,
                state=state,
            )
            return False
        task = asyncio.create_task(
            self._propose_and_retain(principal_id, conversation_id, state, tuple(turns))
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _propose_and_retain(
        self,
        principal_id: str,
        conversation_id: object,
        state: DialogueState,
        turns: tuple[DialogueTurn, ...],
    ) -> None:
        final = await build_dialogue_state(
            turns, keep_recent=len(state.kept_turn_ids), proposer=self.proposer
        )
        await retain_dialogue_shadow(
            self.writer, principal_id=principal_id, conversation_id=conversation_id, state=final
        )

    async def aclose(self) -> None:
        """Cancel in-flight proposals; derived snapshots are regenerated from retained turns."""

        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "DialogueSnapshotWriter",
    "DialogueStateRetention",
    "dialogue_shadow_receipt",
    "history_dialogue_turns",
    "retain_dialogue_shadow",
    "shadow_dialogue_state",
]
