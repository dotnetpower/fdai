"""Typed models mirroring ``rule-catalog/prompts/schema/prompt.schema.json``.

Kept dependency-free (frozen dataclasses + StrEnum) so ``core/`` remains
importable without pydantic being on the request path for prompt lookup.
The JSON Schema at
``rule-catalog/prompts/schema/prompt.schema.json`` is the structural
source of truth; :mod:`fdai.core.prompts.registry` runs that
schema before constructing these dataclasses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

_MAX_AGENT_CHARS = 128
_MAX_QUERY_CHARS = 4_096
_MAX_TOOL_ID_CHARS = 128
_MAX_SKILL_NAME_CHARS = 128
_MAX_REFERENCE_PATH_CHARS = 255
_MAX_SELECTED_SKILLS = 4
_MAX_SELECTED_BUNDLES = 2
_MAX_INDEX_BUDGET_CHARS = 32 * 1_024
_MAX_BODY_BUDGET_CHARS = 4 * 64 * 1_024
_MAX_REFERENCE_BUDGET_BYTES = 256 * 1_024


class PromptLayer(StrEnum):
    """Which composition slot an artifact fills.

    See ``docs/roadmap/decisioning/prompt-composition.md § Role x Layer matrix`` for
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
    SKILL_INDEX = "skill-index"
    SKILL_BODY = "skill-body"
    SKILL_REFERENCE = "skill-reference"
    SKILL_BUNDLE = "skill-bundle"


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
class SkillDisclosureRequest:
    """Explicit, bounded request for role-safe runtime skill disclosure."""

    agent: str
    available_tools: frozenset[str]
    query: str
    selected_skill_names: tuple[str, ...] = ()
    selected_bundle_names: tuple[str, ...] = ()
    reference_selection: tuple[str, str] | None = None
    index_budget_chars: int = 8_192
    body_budget_chars: int = 64 * 1_024
    reference_budget_bytes: int = 256 * 1_024

    def __post_init__(self) -> None:
        if not isinstance(self.agent, str):
            raise ValueError("skill disclosure agent MUST be a string")
        agent = self.agent.strip()
        if not agent or len(agent) > _MAX_AGENT_CHARS:
            raise ValueError("skill disclosure agent MUST be non-empty and bounded")
        object.__setattr__(self, "agent", agent)
        if not isinstance(self.available_tools, frozenset):
            raise ValueError("skill disclosure available_tools MUST be a frozenset")
        if any(
            not isinstance(tool, str)
            or not tool
            or tool != tool.strip()
            or len(tool) > _MAX_TOOL_ID_CHARS
            for tool in self.available_tools
        ):
            raise ValueError("skill disclosure tool ids MUST be non-empty and bounded")
        if not isinstance(self.query, str):
            raise ValueError("skill disclosure query MUST be a string")
        query = " ".join(self.query.split())
        if not query or len(query) > _MAX_QUERY_CHARS:
            raise ValueError("skill disclosure query MUST be non-empty and bounded")
        object.__setattr__(self, "query", query)
        if not isinstance(self.selected_skill_names, tuple):
            raise ValueError("skill disclosure selected names MUST be a tuple")
        if len(self.selected_skill_names) > _MAX_SELECTED_SKILLS:
            raise ValueError("skill disclosure MUST NOT select more than 4 skills")
        if len(set(self.selected_skill_names)) != len(self.selected_skill_names):
            raise ValueError("skill disclosure selected names MUST NOT contain duplicates")
        if any(
            not name or name != name.strip() or len(name) > _MAX_SKILL_NAME_CHARS
            for name in self.selected_skill_names
        ):
            raise ValueError("skill disclosure selected names MUST be non-empty and bounded")
        if not isinstance(self.selected_bundle_names, tuple):
            raise ValueError("skill disclosure selected bundle names MUST be a tuple")
        if len(self.selected_bundle_names) > _MAX_SELECTED_BUNDLES:
            raise ValueError("skill disclosure MUST NOT select more than 2 bundles")
        if len(set(self.selected_bundle_names)) != len(self.selected_bundle_names):
            raise ValueError("skill disclosure selected bundle names MUST NOT contain duplicates")
        if any(
            not name or name != name.strip() or len(name) > _MAX_SKILL_NAME_CHARS
            for name in self.selected_bundle_names
        ):
            raise ValueError("skill disclosure selected bundle names MUST be non-empty and bounded")
        if self.reference_selection is not None:
            if (
                not isinstance(self.reference_selection, tuple)
                or len(self.reference_selection) != 2
                or any(not isinstance(value, str) for value in self.reference_selection)
            ):
                raise ValueError(
                    "skill disclosure reference selection MUST be one (skill_name, path) tuple"
                )
            skill_name, reference_path = self.reference_selection
            if (
                not skill_name
                or skill_name != skill_name.strip()
                or len(skill_name) > _MAX_SKILL_NAME_CHARS
                or not reference_path
                or reference_path != reference_path.strip()
                or len(reference_path) > _MAX_REFERENCE_PATH_CHARS
            ):
                raise ValueError(
                    "skill disclosure reference selection MUST be non-empty and bounded"
                )
        _validate_budget(
            "index_budget_chars",
            self.index_budget_chars,
            _MAX_INDEX_BUDGET_CHARS,
        )
        _validate_budget(
            "body_budget_chars",
            self.body_budget_chars,
            _MAX_BODY_BUDGET_CHARS,
        )
        _validate_budget(
            "reference_budget_bytes",
            self.reference_budget_bytes,
            _MAX_REFERENCE_BUDGET_BYTES,
        )


class SkillSelectionStatus(StrEnum):
    """Outcome of one explicit skill body or reference selection."""

    SELECTED = "selected"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SkillReplayRecord:
    """Immutable selection and digest evidence for deterministic replay."""

    operation: str
    name: str
    version: str | None
    raw_markdown_sha256: str | None
    body_sha256: str | None
    reference_path: str | None
    reference_sha256: str | None
    status: SkillSelectionStatus
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SkillBundleMemberReplayRecord:
    name: str
    version: str
    raw_markdown_sha256: str
    body_sha256: str


@dataclass(frozen=True, slots=True)
class SkillBundleReplayRecord:
    operation: str
    name: str
    version: str | None
    manifest_sha256: str | None
    digest: str | None
    members: tuple[SkillBundleMemberReplayRecord, ...]
    status: SkillSelectionStatus
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PromptReplayManifest:
    """Prompt digest, ordered layers, and skill evidence for one proposal."""

    system_text_sha256: str
    layer_manifest: tuple[LayerRef, ...]
    token_estimate: int
    canary_tokens: tuple[tuple[str, str], ...] = ()
    skill_records: tuple[SkillReplayRecord, ...] = ()
    skill_bundle_records: tuple[SkillBundleReplayRecord, ...] = ()


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
    skill_records: tuple[SkillReplayRecord, ...] = ()
    skill_bundle_records: tuple[SkillBundleReplayRecord, ...] = ()

    def replay_manifest(self) -> PromptReplayManifest:
        """Return immutable evidence without retaining mutable adapter state."""

        return PromptReplayManifest(
            system_text_sha256=hashlib.sha256(self.system_text.encode()).hexdigest(),
            layer_manifest=self.layer_manifest,
            token_estimate=self.token_estimate,
            canary_tokens=tuple(sorted(self.canary_tokens.items())),
            skill_records=self.skill_records,
            skill_bundle_records=self.skill_bundle_records,
        )


def _validate_budget(name: str, value: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"skill disclosure {name} MUST be between 1 and {maximum}")


__all__ = [
    "ComposedPrompt",
    "LayerRef",
    "PromptReplayManifest",
    "PromptArtifact",
    "PromptLayer",
    "PromptMode",
    "SkillDisclosureRequest",
    "SkillBundleMemberReplayRecord",
    "SkillBundleReplayRecord",
    "SkillReplayRecord",
    "SkillSelectionStatus",
]
