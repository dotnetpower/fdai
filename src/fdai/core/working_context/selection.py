"""Immutable contract for bounded working-context selection policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from fdai.core.working_context.types import (
    ContextBudget,
    ContextManifest,
    TranscriptEntry,
)


class ContextTrustClass(StrEnum):
    """Trust classification fixed before a selection policy runs."""

    TRUSTED_INTERNAL = "trusted-internal"
    UNTRUSTED_EXTERNAL = "untrusted-external"


@dataclass(frozen=True, slots=True)
class ModelCapabilityMetadata:
    """Model limits relevant to selection, supplied by the caller."""

    model_id: str
    context_window: int
    supports_tools: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id MUST be non-empty")
        if self.context_window < 1:
            raise ValueError("context_window MUST be >= 1")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ContextSelectionInput:
    """Complete immutable input visible to a context-selection policy."""

    entries: tuple[TranscriptEntry, ...]
    trust_classes: Mapping[str, ContextTrustClass]
    budget: ContextBudget
    model: ModelCapabilityMetadata

    def __post_init__(self) -> None:
        known_ids = {entry.entry_id for entry in self.entries}
        supplied_ids = set(self.trust_classes)
        if known_ids != supplied_ids:
            missing = sorted(known_ids - supplied_ids)
            invented = sorted(supplied_ids - known_ids)
            raise ValueError(
                "trust_classes MUST cover exactly the input entry ids: "
                f"missing={missing}, invented={invented}"
            )
        object.__setattr__(
            self,
            "trust_classes",
            MappingProxyType(dict(self.trust_classes)),
        )


@dataclass(frozen=True, slots=True)
class ContextSelectionOutput:
    """The only decisions a selection policy may return."""

    selected_entry_ids: tuple[str, ...]
    manifest: ContextManifest


@runtime_checkable
class ContextSelectionPolicy(Protocol):
    """Pure policy that selects entry ids and emits their audit manifest."""

    @property
    def policy_id(self) -> str: ...

    @property
    def policy_version(self) -> str: ...

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput: ...


__all__ = [
    "ContextSelectionInput",
    "ContextSelectionOutput",
    "ContextSelectionPolicy",
    "ContextTrustClass",
    "ModelCapabilityMetadata",
]
