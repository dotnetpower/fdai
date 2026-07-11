"""Typed models mirroring ``rule-catalog/prompts/schema/prompt.schema.json``.

Kept dependency-free (frozen dataclasses + StrEnum) so ``core/`` remains
importable without pydantic being on the request path for prompt lookup.
The JSON Schema at
``rule-catalog/prompts/schema/prompt.schema.json`` is the structural
source of truth; :mod:`fdai.core.prompts.registry` runs that
schema before constructing these dataclasses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class PromptLayer(StrEnum):
    """Which composition slot an artifact fills.

    See ``docs/roadmap/prompt-composition.md § Role x Layer matrix`` for
    the full catalog. Only :attr:`BASE` ships in Wave 1; the other
    values are reserved for later waves and included here so the enum
    stays stable when they arrive.
    """

    BASE = "base"
    PACK = "pack"
    CRITIC = "critic"
    JUDGE = "judge"
    RUBRIC = "rubric"
    TOOL = "tool"
    ROLE_HEADER = "role-header"
    OPERATOR_MEMORY = "operator-memory"


class PromptMode(StrEnum):
    """Shadow-vs-enforce mode declared by a prompt artifact.

    Matches the shadow-before-enforce rule in
    ``.github/instructions/coding-conventions.instructions.md``.
    """

    SHADOW = "shadow"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class PromptArtifact:
    """One resolved prompt fragment loaded from the catalog.

    ``applies_to`` is a tuple (not a list) so instances hash and can be
    memoized safely by the composer. ``provenance_source`` mirrors the
    catalog rule that every prompt fragment MUST cite its origin.
    """

    id: str
    version: int
    layer: PromptLayer
    body: str
    applies_to: tuple[str, ...]
    token_budget: int | None
    default_mode: PromptMode
    provenance_source: str

    def matches(self, capability_id: str) -> bool:
        """True when this artifact declares ``capability_id`` (or is unbound).

        An empty ``applies_to`` list means the artifact can bind to any
        capability the composer selects - the catalog schema allows
        both shapes so global helpers (formatting rules, output
        contracts) do not have to list every capability.
        """

        if not self.applies_to:
            return True
        return capability_id in self.applies_to


@dataclass(frozen=True, slots=True)
class LayerRef:
    """One layer's contribution recorded in a composed prompt's manifest.

    Emitted by the composer so every prompt run carries a traceable
    ``(id, version, layer)`` provenance chain plus a per-layer token
    estimate. Later waves feed :attr:`token_estimate` into the
    recognition-probe KPIs; Wave 2 only stores it for future gate use.
    """

    id: str
    version: int
    layer: PromptLayer
    token_estimate: int


@dataclass(frozen=True, slots=True)
class ComposedPrompt:
    """Resolved prompt handed to the delivery adapter.

    ``system_text`` is the concatenated system-role content ready for
    the model call. ``layer_manifest`` records the ordered contribution
    of each artifact (base, packs, tool manifests, operator memory,
    and in later waves debate transcripts) so the audit log can
    reconstruct exactly which fragments produced any given decision.
    ``token_estimate`` is the composer's crude per-4-characters heuristic
    that later waves replace with a model-specific tokenizer.

    ``canary_tokens`` (Wave 3 step D-2a) maps each layer id to the
    canary token the composer prepended to that layer's body. Empty
    by default so composers that do not inject canaries behave
    exactly as before; the recognition probe scans the model's
    response for these tokens to compute the "did the model actually
    read every layer?" KPI.
    """

    system_text: str
    layer_manifest: tuple[LayerRef, ...]
    token_estimate: int
    canary_tokens: Mapping[str, str] = field(default_factory=dict)


__all__ = [
    "ComposedPrompt",
    "LayerRef",
    "PromptArtifact",
    "PromptLayer",
    "PromptMode",
]
