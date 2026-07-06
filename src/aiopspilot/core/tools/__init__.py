"""Tool catalog seam for the T2 tier.

Loads catalog-as-code tool descriptions from ``rule-catalog/prompts/tools/``,
validates them against the JSON Schema, and exposes a :class:`ToolRegistry`
Protocol. Wave 2.5-A ships the registry; Wave 2.5-B step 2a adds the
:class:`ToolExecutor` async Protocol and its default implementation. Wave
2.5-B step 2b wires the executor into the Azure OpenAI cross-check adapter.

Design references:

- ``docs/roadmap/prompt-composition.md § Tool use subsystem``
- ``rule-catalog/prompts/tools/README.md`` - authoring contract
"""

from __future__ import annotations

from aiopspilot.core.tools.executor import (
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
from aiopspilot.core.tools.registry import (
    FileSystemToolRegistry,
    ToolRegistry,
    ToolRegistryError,
    ToolRegistryIssue,
)
from aiopspilot.core.tools.types import (
    CapabilityGate,
    ToolArtifact,
)

__all__ = [
    "CapabilityGate",
    "DefaultToolExecutor",
    "FileSystemToolRegistry",
    "MissingProviderError",
    "ProviderCallError",
    "ShadowToolBlockedError",
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
