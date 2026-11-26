"""Typed models mirroring ``rule-catalog/prompts/tools/schema/tool.schema.json``.

Kept dependency-free so ``core/`` remains importable without pydantic in
the request path for tool lookup. The JSON Schema at
``rule-catalog/prompts/tools/schema/tool.schema.json`` is the structural
source of truth; :mod:`fdai.core.tools.registry` runs that schema
before constructing these dataclasses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.prompts.types import PromptMode


@dataclass(frozen=True, slots=True)
class CapabilityGate:
    """When a tool is eligible to be offered to the model.

    All fields are optional. The composer AND executor apply these
    gates independently:

    - the composer skips tools whose gates are not currently satisfied
      so they never enter the prompt manifest,
    - the executor re-checks the gate at dispatch time so a stale
      manifest cannot bypass the ceiling.
    """

    requires_tier: str | None
    requires_novelty_score: str | None
    cost_budget_usd_per_call: float | None


@dataclass(frozen=True, slots=True)
class ToolArtifact:
    """One tool description loaded from the catalog.

    ``input_schema`` is stored as a plain :class:`Mapping` so the
    executor can pass it straight to a JSON Schema validator at
    dispatch time. ``output_wrapper`` MUST embed ``trusted="false"``;
    the registry enforces that when the field is populated.
    """

    id: str
    version: int
    description: str
    input_schema: Mapping[str, Any]
    capability_gate: CapabilityGate
    allowlist: Mapping[str, Any] | None
    output_wrapper: str | None
    default_mode: PromptMode
    provider: str | None
    provenance_source: str


__all__ = [
    "CapabilityGate",
    "ToolArtifact",
]
