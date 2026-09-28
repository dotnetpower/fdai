"""Composable prompt catalog for the T2 tier and quality gate.

The subsystem stores prompt fragments as **catalog-as-code**: YAML files
under ``rule-catalog/prompts/`` are the source of truth, and this
package loads / validates / indexes them. ``core/`` receives resolved
:class:`ComposedPrompt` values through the composition root; adapters
under ``delivery/`` never open the YAML directly.

Wave 1 shipped the base layer and a file-system registry. Wave 2 adds
the :class:`PromptComposer` :class:`~typing.Protocol` and its default
implementation, plus task-pack support in the registry. Later waves
add tool manifests, operator memory, and the debate orchestrator; their
seams are documented in ``docs/roadmap/decisioning/prompt-composition.md``.

Design references:

- ``docs/roadmap/decisioning/prompt-composition.md`` - full evolving-prompt design
- ``docs/roadmap/architecture/llm-strategy.md`` - quality gate that consumes T2 output
- ``rule-catalog/prompts/README.md`` - catalog layout and file contract
"""

from __future__ import annotations

from fdai.core.prompts.assembly import PromptAssembler
from fdai.core.prompts.budget import (
    estimate_chat_request_tokens,
    estimate_prompt_tokens,
    estimate_serialized_request_tokens,
)
from fdai.core.prompts.composer import (
    DefaultPromptComposer,
    PromptComposer,
)
from fdai.core.prompts.profile_evaluation import (
    PromptProfileComparison,
    compare_prompt_profiles,
)
from fdai.core.prompts.profiles import (
    PromptArtifactRef,
    PromptBudgetExceededError,
    PromptProfile,
    PromptProfileMode,
    PromptRequestBudgetExceededError,
    PromptSelection,
    compose_static_selection,
)
from fdai.core.prompts.registry import (
    FileSystemPromptRegistry,
    LegacyPromptRegistry,
    PromptRegistry,
    PromptRegistryError,
    PromptRegistryIssue,
    resolve_prompt_selection,
)
from fdai.core.prompts.types import (
    AblatedLayerRef,
    ComposedPrompt,
    LayerRef,
    PromptAblationProfile,
    PromptAblationProfileName,
    PromptArtifact,
    PromptAssemblyMode,
    PromptAssemblyReceipt,
    PromptLayer,
    PromptMode,
    PromptProfileEvidence,
    PromptReplayManifest,
    SkillBundleMemberReplayRecord,
    SkillBundleReplayRecord,
    SkillDisclosureRequest,
    SkillReplayRecord,
    SkillSelectionStatus,
)

__all__ = [
    "AblatedLayerRef",
    "ComposedPrompt",
    "compose_static_selection",
    "DefaultPromptComposer",
    "FileSystemPromptRegistry",
    "LayerRef",
    "LegacyPromptRegistry",
    "PromptReplayManifest",
    "PromptArtifact",
    "PromptAblationProfile",
    "PromptAblationProfileName",
    "PromptArtifactRef",
    "PromptAssembler",
    "PromptAssemblyMode",
    "PromptAssemblyReceipt",
    "PromptBudgetExceededError",
    "PromptProfileComparison",
    "PromptComposer",
    "PromptLayer",
    "PromptMode",
    "PromptProfile",
    "PromptProfileMode",
    "PromptRequestBudgetExceededError",
    "PromptProfileEvidence",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptRegistryIssue",
    "PromptSelection",
    "resolve_prompt_selection",
    "compare_prompt_profiles",
    "estimate_prompt_tokens",
    "estimate_serialized_request_tokens",
    "estimate_chat_request_tokens",
    "SkillDisclosureRequest",
    "SkillBundleMemberReplayRecord",
    "SkillBundleReplayRecord",
    "SkillReplayRecord",
    "SkillSelectionStatus",
]
