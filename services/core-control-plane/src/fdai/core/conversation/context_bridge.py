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
from dataclasses import replace

from fdai.core.conversation.session import ConversationSession, TurnDirection
from fdai.core.operator_memory.types import MemoryCategory, OperatorMemoryEntry
from fdai.core.working_context.composer import (
    compose_working_context,
    context_selection_input,
)
from fdai.core.working_context.governance import ContextSelectionPolicyAuthority
from fdai.core.working_context.shadow import ContextSelectionShadowRunner
from fdai.core.working_context.summarizer import TranscriptRetriever
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

# Operator-memory categories that are hard constraints: they are pinned so
# the composer always includes them regardless of budget or recency. A
# forbidden-action note ("never auto-restart this cluster") losing to budget
# pressure would be a safety regression, so it is never a drop candidate.
_ALWAYS_PINNED_CATEGORIES: frozenset[MemoryCategory] = frozenset({MemoryCategory.FORBIDDEN_ACTION})


def _default_estimator(text: str) -> int:
    return max(1, len(text) // 4)


def _session_verbatim_entries(
    session: ConversationSession,
    *,
    pinned_ids: frozenset[str],
    token_estimator: Callable[[str], int],
) -> list[TranscriptEntry]:
    """Map non-empty session turns to verbatim entries (sequence = index)."""

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
    return verbatim


def session_to_working_context(
    *,
    session: ConversationSession,
    budget: ContextBudget,
    typed_facts: Sequence[TranscriptEntry] = (),
    retrieved: Sequence[TranscriptEntry] = (),
    summaries: Sequence[TranscriptEntry] = (),
    pinned_ids: frozenset[str] = frozenset(),
    token_estimator: Callable[[str], int] = _default_estimator,
    policy_authority: ContextSelectionPolicyAuthority | None = None,
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

    verbatim = _session_verbatim_entries(
        session, pinned_ids=pinned_ids, token_estimator=token_estimator
    )
    entries = [*verbatim, *typed_facts, *retrieved, *summaries]
    if policy_authority is None:
        return compose_working_context(budget=budget, entries=entries)
    return policy_authority.select(context_selection_input(budget=budget, entries=entries))


async def assemble_turn_context(
    *,
    session: ConversationSession,
    utterance: str,
    budget: ContextBudget,
    operator_memory: Sequence[OperatorMemoryEntry] = (),
    existing_summaries: Sequence[TranscriptEntry] = (),
    retriever: TranscriptRetriever | None = None,
    retrieval_k: int = 5,
    pinned_ids: frozenset[str] = frozenset(),
    token_estimator: Callable[[str], int] = _default_estimator,
    policy_authority: ContextSelectionPolicyAuthority | None = None,
    shadow_runner: ContextSelectionShadowRunner | None = None,
) -> WorkingContext:
    """End-to-end working-context assembly for one conversation turn.

    Ties every tier together: session turns become verbatim entries,
    ``operator_memory`` becomes trusted typed facts, the ``retriever`` seam
    (when wired) pulls older turns relevant to ``utterance`` back into the
    retrieval tier, and ``existing_summaries`` (from prior orchestrator
    folds) fill the summary tier. The composer then bounds the whole thing
    under ``budget``.

    Retrieval candidates are the session's verbatim turns re-tagged as
    ``RETRIEVED``; the composer deduplicates by entry id, so a turn that
    still fits the verbatim window is counted once (verbatim), while a turn
    that fell outside it can return via the retrieval tier when it is
    relevant. With ``retriever=None`` this reduces to
    :func:`session_to_working_context` plus operator memory.
    """

    verbatim = _session_verbatim_entries(
        session, pinned_ids=pinned_ids, token_estimator=token_estimator
    )
    typed_facts = operator_memory_to_entries(operator_memory, token_estimator=token_estimator)

    retrieved: tuple[TranscriptEntry, ...] = ()
    if retriever is not None and utterance.strip() and verbatim:
        candidates = tuple(replace(e, kind=EntryKind.RETRIEVED) for e in verbatim)
        retrieved = tuple(
            await retriever.retrieve(utterance=utterance, candidates=candidates, k=retrieval_k)
        )

    entries = [*verbatim, *typed_facts, *retrieved, *existing_summaries]
    selection_input = context_selection_input(budget=budget, entries=entries)
    if policy_authority is None:
        context = compose_working_context(budget=budget, entries=entries)
    else:
        context = policy_authority.select(selection_input)
    if shadow_runner is not None:
        if policy_authority is None:
            raise ValueError("shadow_runner requires policy_authority")
        shadow_runner.schedule(selection_input=selection_input, baseline=context)
    return context


def operator_memory_to_entries(
    memory_entries: Sequence[OperatorMemoryEntry],
    *,
    token_estimator: Callable[[str], int] = _default_estimator,
) -> tuple[TranscriptEntry, ...]:
    """Project HIL-approved operator memory into trusted typed-fact entries.

    Operator memory (preferences, override notes, forbidden actions, runbook
    hints) is second-approver-verified standing knowledge, so it enters the
    working context as ``trusted`` ``TYPED_FACT`` background - never a
    summary candidate and never an untrusted layer. Feed the result to
    :func:`session_to_working_context` as ``typed_facts``.

    ``FORBIDDEN_ACTION`` entries are ``pinned`` so the composer always
    includes them; a safety constraint must not lose to budget pressure.
    The ``sequence`` is negative (older than any session turn) so memory
    reads as background, and decreases with input order so a caller that
    passes newest-first keeps the freshest note highest in the tier.
    """

    out: list[TranscriptEntry] = []
    for offset, memory in enumerate(memory_entries):
        text = (
            f"[{memory.category.value}@{memory.scope_kind.value}:{memory.scope_ref}] {memory.body}"
        )
        out.append(
            TranscriptEntry(
                entry_id=f"opmem-{memory.id}",
                role=EntryRole.SYSTEM,
                kind=EntryKind.TYPED_FACT,
                text=text,
                tokens=token_estimator(text),
                sequence=-1 - offset,
                pinned=memory.category in _ALWAYS_PINNED_CATEGORIES,
                trusted=True,
                metadata={
                    "scope_ref": memory.scope_ref,
                    "category": memory.category.value,
                },
            )
        )
    return tuple(out)


__all__ = [
    "assemble_turn_context",
    "operator_memory_to_entries",
    "session_to_working_context",
]
