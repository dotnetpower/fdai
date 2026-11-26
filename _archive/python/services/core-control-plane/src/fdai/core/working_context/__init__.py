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

from fdai.core.working_context.composer import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    DETERMINISTIC_TIERED_POLICY_ID,
    DETERMINISTIC_TIERED_POLICY_VERSION,
    DeterministicTieredPolicy,
    compose_working_context,
    context_selection_input,
)
from fdai.core.working_context.evidence import (
    ContextSelectionEvaluation,
    ContextSelectionEvaluationStore,
    InMemoryContextSelectionEvaluationStore,
    StateStoreContextSelectionEvaluationStore,
)
from fdai.core.working_context.governance import (
    ContextPolicyEvidence,
    ContextPolicyGovernanceError,
    ContextPolicyIdentity,
    ContextPolicyRecord,
    ContextPolicySnapshot,
    ContextPolicyState,
    ContextSelectionPolicyAuthority,
)
from fdai.core.working_context.orchestrator import SummarizationOrchestrator
from fdai.core.working_context.planner import FoldPlan, plan_summarization
from fdai.core.working_context.replay import (
    ContextReplayFixture,
    ContextReplayResult,
    replay_approved_context_fixtures,
)
from fdai.core.working_context.selection import (
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextSelectionPolicy,
    ContextTrustClass,
    ModelCapabilityMetadata,
)
from fdai.core.working_context.shadow import (
    ContextSelectionShadowRunner,
    ContextShadowConfig,
    fingerprint_context_selection_input,
)
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
from fdai.core.working_context.validation import (
    ContextSelectionInvariantError,
    execute_context_selection_policy,
    validate_context_selection,
)

__all__ = [
    "ContextBudget",
    "ContextManifest",
    "ContextPolicyEvidence",
    "ContextPolicyGovernanceError",
    "ContextPolicyIdentity",
    "ContextPolicyRecord",
    "ContextPolicySnapshot",
    "ContextPolicyState",
    "ContextReplayFixture",
    "ContextReplayResult",
    "ContextSelectionInput",
    "ContextSelectionEvaluation",
    "ContextSelectionEvaluationStore",
    "ContextSelectionInvariantError",
    "ContextSelectionOutput",
    "ContextSelectionPolicy",
    "ContextSelectionPolicyAuthority",
    "ContextSelectionShadowRunner",
    "ContextShadowConfig",
    "ContextTrustClass",
    "DEFAULT_CONTEXT_SELECTION_POLICY",
    "DETERMINISTIC_TIERED_POLICY_ID",
    "DETERMINISTIC_TIERED_POLICY_VERSION",
    "DeterministicTruncationSummarizer",
    "DeterministicTieredPolicy",
    "EntryKind",
    "EntryRole",
    "FoldPlan",
    "InMemoryContextSelectionEvaluationStore",
    "ModelCapabilityMetadata",
    "NoOpRetriever",
    "SummarizationOrchestrator",
    "StateStoreContextSelectionEvaluationStore",
    "TranscriptEntry",
    "TranscriptRetriever",
    "TranscriptSummarizer",
    "WorkingContext",
    "WorkingContextError",
    "compose_working_context",
    "context_selection_input",
    "execute_context_selection_policy",
    "fingerprint_context_selection_input",
    "plan_summarization",
    "replay_approved_context_fixtures",
    "validate_context_selection",
]
