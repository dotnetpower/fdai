"""Conversation working-context subsystem.

Separates the **memory of record** (lossless transcript, persisted as an
audit-log projection) from the **working context** (the bounded, per-turn
projection sent to the model). The pure composer bounds the prompt under
a token budget across three tiers - verbatim recent, hierarchical
summary, relevance retrieval - plus deterministic typed-pipeline facts,
so the prompt stays under a constant ceiling no matter how long the
session runs, while nothing is dropped from the memory of record.

Public surface:

- :func:`compose_working_context` - the pure assembly policy.
- :class:`ContextBudget` / :class:`WorkingContext` / :class:`ContextManifest`
  / :class:`TranscriptEntry` / :class:`EntryKind` / :class:`EntryRole` -
  the data model.
- :class:`TranscriptSummarizer` / :class:`TranscriptRetriever` - the
  ``async`` I/O seams, with deterministic no-LLM fakes shipped upstream.

See ``docs/roadmap/interfaces/operator-console.md`` section 6 and
``docs/roadmap/decisioning/prompt-composition.md``.
"""

from __future__ import annotations

from fdai.core.working_context.composer import compose_working_context
from fdai.core.working_context.planner import FoldPlan, plan_summarization
from fdai.core.working_context.summarizer import (
    DeterministicTruncationSummarizer,
    NoOpRetriever,
    TranscriptRetriever,
    TranscriptSummarizer,
)
from fdai.core.working_context.types import (
    ContextBudget,
    ContextManifest,
    EntryKind,
    EntryRole,
    TranscriptEntry,
    WorkingContext,
    WorkingContextError,
)

__all__ = [
    "ContextBudget",
    "ContextManifest",
    "DeterministicTruncationSummarizer",
    "EntryKind",
    "EntryRole",
    "FoldPlan",
    "NoOpRetriever",
    "TranscriptEntry",
    "TranscriptRetriever",
    "TranscriptSummarizer",
    "WorkingContext",
    "WorkingContextError",
    "compose_working_context",
    "plan_summarization",
]
