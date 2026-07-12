"""context_bridge - project a conversation session into a working context.

The memory of record for the operator console is
:class:`~fdai.core.conversation.session.ConversationSession` (its
``turns`` are the lossless, audit-projected transcript). The model,
however, must receive the *bounded* working context assembled by
:func:`~fdai.core.working_context.composer.compose_working_context`.

This module is the connecting tissue: it maps session ``Turn`` records
into :class:`~fdai.core.working_context.types.TranscriptEntry` verbatim
entries, folds in any deterministic typed-pipeline facts, retrieved
snippets, and rolling summaries the caller already produced, and returns
a :class:`~fdai.core.working_context.types.WorkingContext`. It is a pure
function (the token estimate is injected at the boundary), so it is
testable and auditable on its own, exactly like the composer it wraps.

Trust boundary: operator utterances, assistant replies, and tool output
are external / model-generated -> ``trusted=False`` (the delivery adapter
wraps them as data). Only ``typed_facts`` supplied by the caller - audit
entries, T0 verdicts projected from the typed pipeline - are ``trusted``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fdai.core.conversation.session import ConversationSession, TurnDirection
from fdai.core.working_context.composer import compose_working_context
from fdai.core.working_context.types import (
    ContextBudget,
    EntryKind,
    EntryRole,
    TranscriptEntry,
    WorkingContext,
)

_DIRECTION_ROLE: dict[TurnDirection, EntryRole] = {
    "inbound": EntryRole.OPERATOR,
    "outbound": EntryRole.ASSISTANT,
    "tool_call": EntryRole.TOOL,
    "tool_result": EntryRole.TOOL,
    "system": EntryRole.SYSTEM,
}


def _default_estimator(text: str) -> int:
    return max(1, len(text) // 4)


def session_to_working_context(
    *,
    session: ConversationSession,
    budget: ContextBudget,
    typed_facts: Sequence[TranscriptEntry] = (),
    retrieved: Sequence[TranscriptEntry] = (),
    summaries: Sequence[TranscriptEntry] = (),
    pinned_ids: frozenset[str] = frozenset(),
    token_estimator: Callable[[str], int] = _default_estimator,
) -> WorkingContext:
    """Assemble the bounded working context for the next model turn.

    ``session.turns`` become verbatim entries (newest last). ``typed_facts``
    / ``retrieved`` / ``summaries`` are the other three tiers the caller
    prepared (from the typed pipeline, the retriever seam, and the
    summarizer seam respectively). ``pinned_ids`` marks turns that must
    always be included (operator constraints, unresolved decisions).

    The verbatim ``sequence`` is the turn's index in the session, so the
    composer keeps newest-first selection and oldest-first prompt order.
    """

    verbatim: list[TranscriptEntry] = []
    for index, turn in enumerate(session.turns):
        text = turn.content
        if not text:
            continue
        verbatim.append(
            TranscriptEntry(
                entry_id=turn.turn_id,
                role=_DIRECTION_ROLE.get(turn.direction, EntryRole.SYSTEM),
                kind=EntryKind.VERBATIM,
                text=text,
                tokens=token_estimator(text),
                sequence=index,
                pinned=turn.turn_id in pinned_ids,
                trusted=False,
            )
        )

    entries = [*verbatim, *typed_facts, *retrieved, *summaries]
    return compose_working_context(budget=budget, entries=entries)


__all__ = ["session_to_working_context"]
