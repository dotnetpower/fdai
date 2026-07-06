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
seams are documented in ``docs/roadmap/prompt-composition.md``.

Design references:

- ``docs/roadmap/prompt-composition.md`` - full evolving-prompt design
- ``docs/roadmap/llm-strategy.md`` - quality gate that consumes T2 output
- ``rule-catalog/prompts/README.md`` - catalog layout and file contract
"""

from __future__ import annotations

from aiopspilot.core.prompts.composer import (
    DefaultPromptComposer,
    PromptComposer,
)
from aiopspilot.core.prompts.registry import (
    FileSystemPromptRegistry,
    PromptRegistry,
    PromptRegistryError,
    PromptRegistryIssue,
)
from aiopspilot.core.prompts.types import (
    ComposedPrompt,
    LayerRef,
    PromptArtifact,
    PromptLayer,
    PromptMode,
)

__all__ = [
    "ComposedPrompt",
    "DefaultPromptComposer",
    "FileSystemPromptRegistry",
    "LayerRef",
    "PromptArtifact",
    "PromptComposer",
    "PromptLayer",
    "PromptMode",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptRegistryIssue",
]
