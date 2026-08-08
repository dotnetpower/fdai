"""Type primitives for the conversation working-context subsystem.

The design separates two things the console and the agent conversational
port used to conflate:

- **Memory of record** - the *lossless* transcript of every turn in a
  session, persisted as an audit-log projection (``console.turn``) or an
  ``agent_transcript`` row. Nothing is ever dropped here; it grows
  ``O(L)`` in the session length and is the source of truth for replay.
- **Working context** - the *bounded* projection that is actually sent to
  the model on a given turn. It is re-assembled every turn under a token
  budget from three tiers (verbatim recent, hierarchical summary,
  relevance retrieval) so the prompt stays under a constant ceiling no
  matter how long the session runs.

This module is data-only (frozen dataclasses + ``StrEnum``); the pure
assembly policy lives in :mod:`fdai.core.working_context.composer` and
the I/O seams (summarize, retrieve) in
:mod:`fdai.core.working_context.summarizer` /
:mod:`fdai.core.working_context.retriever`.

Design reference:
- ``docs/roadmap/interfaces/operator-console.md`` section 6 (Session model + memory).
- ``docs/roadmap/decisioning/prompt-composition.md`` (Operator Memory layer).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class EntryKind(StrEnum):
    """Which tier an entry belongs to inside the working context.

    ``VERBATIM`` is an original transcript turn kept word-for-word.
    ``SUMMARY`` is a rolling hierarchical summary that folds a span of
    older turns (``level`` >= 1). ``RETRIEVED`` is a relevance-selected
    snippet pulled back in because it matches the current utterance even
    though it fell outside the verbatim window. ``TYPED_FACT`` is a
    deterministic, no-LLM fact projected from the typed pipeline
    (an audit entry, a T0 verdict) - it is trusted context, never a
    summary candidate.
    """

    VERBATIM = "verbatim"
    SUMMARY = "summary"
    RETRIEVED = "retrieved"
    TYPED_FACT = "typed-fact"


class EntryRole(StrEnum):
    """Who authored a transcript entry.

    Mirrors the OpenAI-style chat roles the delivery adapter maps onto,
    plus ``agent`` for the agent-to-agent (A2A) conversational port.
    """

    OPERATOR = "operator"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """One unit the composer may place into the working context.

    ``entry_id`` is stable across re-composition so the audit manifest
    can name exactly which turns / summaries a prompt contained.

    ``tokens`` is the pre-estimated token cost of ``text``; the composer
    treats it as authoritative so assembly stays a pure function (the
    estimator runs at the call boundary, not inside the policy).

    ``pinned`` entries are always included regardless of budget or
    recency - operator constraints ("do not touch this RG"), unresolved
    decisions, and standing safety notes. A pinned entry that cannot fit
    is a configuration error surfaced by the composer, never silently
    dropped.

    ``trusted`` marks deterministic, internal context (typed-pipeline
    facts, audit entries) that the model may read as ground truth. Every
    external or model-generated entry (operator utterance, tool output,
    web snippet, a summary of those) is ``trusted=False`` and the
    delivery adapter wraps it in a ``trusted="false"`` envelope so the
    model treats it as data, never instructions. This is the same
    injection boundary the quality gate enforces for T2 event payloads.

    ``level`` is 0 for verbatim / typed facts and >= 1 for summaries
    (level 1 folds turns, level 2 folds level-1 summaries, ...).

    ``source_ids`` records which original entries a summary folds, so a
    summary is traceable back to the lossless memory of record.
    """

    entry_id: str
    role: EntryRole
    kind: EntryKind
    text: str
    tokens: int
    sequence: int
    pinned: bool = False
    trusted: bool = False
    level: int = 0
    relevance: float | None = None
    source_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("TranscriptEntry.entry_id MUST be non-empty")
        if self.tokens < 0:
            raise ValueError("TranscriptEntry.tokens MUST be >= 0")
        if self.level < 0:
            raise ValueError("TranscriptEntry.level MUST be >= 0")
        if self.kind is EntryKind.SUMMARY and self.level < 1:
            raise ValueError("a SUMMARY entry MUST have level >= 1")
        if self.relevance is not None and not (0.0 <= self.relevance <= 1.0):
            raise ValueError("TranscriptEntry.relevance MUST be in [0.0, 1.0] or None")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Token budget and tier split for one working-context assembly.

    The window is carved as::

        history = total_window
                  - base_reserve      # role / verifier system prompt (never trimmed)
                  - output_reserve    # completion headroom (never trimmed)
                  - tools_reserve     # tool manifest
                  - memory_reserve    # operator-memory layer

    and the remaining ``history`` budget is split across the three tiers
    by ratio. Ratios are a *target* split, not a hard partition: the
    composer lets an under-used tier's slack spill to the next tier so a
    short session still fills the window with verbatim turns rather than
    padding with summaries.

    All reserves and the window are token counts. The ratios MUST sum to
    <= 1.0 (the composer tolerates a sum below 1.0 - the remainder is
    simply unused headroom).
    """

    total_window: int = 128_000
    base_reserve: int = 2_000
    output_reserve: int = 4_096
    tools_reserve: int = 2_000
    memory_reserve: int = 2_000
    verbatim_ratio: float = 0.45
    retrieval_ratio: float = 0.25
    summary_ratio: float = 0.15
    typed_fact_ratio: float = 0.15

    def __post_init__(self) -> None:
        for name in ("total_window", "output_reserve"):
            if getattr(self, name) < 1:
                raise ValueError(f"ContextBudget.{name} MUST be >= 1")
        for name in ("base_reserve", "tools_reserve", "memory_reserve"):
            if getattr(self, name) < 0:
                raise ValueError(f"ContextBudget.{name} MUST be >= 0")
        for name in (
            "verbatim_ratio",
            "retrieval_ratio",
            "summary_ratio",
            "typed_fact_ratio",
        ):
            ratio = getattr(self, name)
            if not (0.0 <= ratio <= 1.0):
                raise ValueError(f"ContextBudget.{name} MUST be in [0.0, 1.0]")
        ratio_sum = (
            self.verbatim_ratio + self.retrieval_ratio + self.summary_ratio + self.typed_fact_ratio
        )
        if ratio_sum > 1.0 + 1e-9:
            raise ValueError("ContextBudget tier ratios MUST sum to <= 1.0")
        if self.history_budget < 1:
            reserved = (
                self.base_reserve + self.output_reserve + self.tools_reserve + self.memory_reserve
            )
            raise ValueError(
                "ContextBudget reserves exceed total_window - no room for history; "
                f"total_window={self.total_window}, reserved={reserved}"
            )

    @property
    def history_budget(self) -> int:
        """Tokens left for the transcript after fixed reserves."""

        return (
            self.total_window
            - self.base_reserve
            - self.output_reserve
            - self.tools_reserve
            - self.memory_reserve
        )


@dataclass(frozen=True, slots=True)
class ContextManifest:
    """Audit record of exactly what one assembly placed in the prompt.

    Written to the turn's audit entry (``context_manifest``) so any
    prompt is reconstructable from the lossless memory of record: which
    verbatim turns, which summary hashes, which retrieved snippets, how
    many tokens each tier consumed, and how many entries were dropped for
    budget.
    """

    verbatim_ids: tuple[str, ...]
    summary_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...]
    pinned_ids: tuple[str, ...]
    typed_fact_ids: tuple[str, ...]
    verbatim_tokens: int
    summary_tokens: int
    retrieved_tokens: int
    pinned_tokens: int
    typed_fact_tokens: int
    dropped_ids: tuple[str, ...]

    @property
    def total_tokens(self) -> int:
        return (
            self.verbatim_tokens
            + self.summary_tokens
            + self.retrieved_tokens
            + self.pinned_tokens
            + self.typed_fact_tokens
        )


@dataclass(frozen=True, slots=True)
class WorkingContext:
    """The bounded, ordered set of entries handed to the model this turn.

    ``entries`` is in prompt order (oldest context first, most recent
    verbatim last) so the delivery adapter can map it straight onto the
    chat ``messages`` array. ``manifest`` is the audit companion.
    """

    entries: tuple[TranscriptEntry, ...]
    manifest: ContextManifest

    @property
    def total_tokens(self) -> int:
        return self.manifest.total_tokens


class WorkingContextError(RuntimeError):
    """Raised when a pinned entry cannot fit inside the history budget.

    A pinned entry is a hard requirement (an operator safety constraint);
    silently dropping it would violate the "constraints survive
    compaction" rule, so the composer fails closed and the caller must
    widen the budget or shorten the pin.
    """


__all__ = [
    "ContextBudget",
    "ContextManifest",
    "EntryKind",
    "EntryRole",
    "TranscriptEntry",
    "WorkingContext",
    "WorkingContextError",
]
