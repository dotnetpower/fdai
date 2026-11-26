"""Tool catalog seam for the T2 tier.

Loads catalog-as-code tool descriptions from ``rule-catalog/prompts/tools/``,
validates them against the JSON Schema, and exposes a :class:`ToolRegistry`
Protocol. Wave 2.5-A ships the registry; Wave 2.5-B step 2a adds the
:class:`ToolExecutor` async Protocol and its default implementation. Wave
2.5-B step 2b wires the executor into the Azure OpenAI cross-check adapter.

Design references:

- ``docs/roadmap/decisioning/prompt-composition.md § Tool use subsystem``
- ``rule-catalog/prompts/tools/README.md`` - authoring contract
"""

from __future__ import annotations

from fdai.core.tools.executor import (
    DefaultToolExecutor,
    MissingProviderError,
    ProviderCallError,
    ShadowToolBlockedError,
    ToolArgumentValidationError,
    ToolExecutor,
    ToolExecutorError,
    ToolProvider,
    ToolResult,
    UnknownToolError,
)
from fdai.core.tools.registry import (
    CompositeToolRegistry,
    FileSystemToolRegistry,
    StaticToolRegistry,
    ToolRegistry,
    ToolRegistryError,
    ToolRegistryIssue,
)
from fdai.core.tools.types import (
    CapabilityGate,
    ToolArtifact,
)

__all__ = [
    "CapabilityGate",
    "CompositeToolRegistry",
    "DefaultToolExecutor",
    "FileSystemToolRegistry",
    "MissingProviderError",
    "ProviderCallError",
    "ShadowToolBlockedError",
    "StaticToolRegistry",
    "ToolArgumentValidationError",
    "ToolArtifact",
    "ToolExecutor",
    "ToolExecutorError",
    "ToolProvider",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolRegistryIssue",
    "ToolResult",
    "UnknownToolError",
]
