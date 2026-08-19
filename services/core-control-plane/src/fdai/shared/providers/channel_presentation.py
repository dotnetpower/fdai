"""Provider-neutral presentation rendering contract for conversation channels.

Responsibility:
    Define bounded immutable input, capability, and output records for pure
    channel presentation rendering.
Boundary:
    Renderers shape already verified facts. They do not receive credentials,
    endpoints, provider clients, acknowledgement state, or transport methods.
Authority and state:
    This contract grants no judgment, approval, mutation, or execution
    authority and owns no durable state.
Dependencies:
    Depends only on Python value types and is implemented by delivery or fork
    adapters through dependency injection.
Deployment:
    It is a shared in-process Protocol and creates no service or network
    boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

MAX_PRESENTATION_FACTS = 256
MAX_PRESENTATION_SECTIONS = 8
MAX_PRESENTATION_LIMITATIONS = 16
MAX_PRESENTATION_TEXT_CHARS = 16_000


@dataclass(frozen=True, slots=True)
class ChannelPresentationCapabilities:
    """Provider-owned rendering limits and optional interaction support."""

    profile_id: str
    max_text_chars: int
    max_serialized_bytes: int
    max_blocks: int
    max_block_text_chars: int
    max_fields: int
    max_actions: int
    supports_images: bool = False
    supports_deterministic_sparkline: bool = False
    supports_edits: bool = False
    supports_threads: bool = True
    supports_progress: bool = False

    def __post_init__(self) -> None:
        _bounded_text("profile_id", self.profile_id, 128)
        if not 256 <= self.max_text_chars <= MAX_PRESENTATION_TEXT_CHARS:
            raise ValueError("channel presentation max_text_chars is outside the bounded range")
        if not 1_024 <= self.max_serialized_bytes <= 128_000:
            raise ValueError(
                "channel presentation max_serialized_bytes is outside the bounded range"
            )
        for name, value, maximum in (
            ("max_blocks", self.max_blocks, 64),
            ("max_block_text_chars", self.max_block_text_chars, 16_000),
            ("max_fields", self.max_fields, MAX_PRESENTATION_FACTS),
            ("max_actions", self.max_actions, 16),
        ):
            if not 0 <= value <= maximum:
                raise ValueError(f"channel presentation {name} is outside the bounded range")


@dataclass(frozen=True, slots=True)
class ChannelPresentationFact:
    """One exact label/value fact copied from a validated artifact."""

    label: str
    value: str

    def __post_init__(self) -> None:
        _bounded_text("fact.label", self.label, 512)
        _bounded_text("fact.value", self.value, 1_024)


@dataclass(frozen=True, slots=True)
class ChannelPresentationSection:
    """One artifact section normalized for capability reduction."""

    kind: str
    title: str
    facts: tuple[ChannelPresentationFact, ...]
    description: str | None = None

    def __post_init__(self) -> None:
        _bounded_text("section.kind", self.kind, 64)
        _bounded_text("section.title", self.title, 512)
        if len(self.facts) > MAX_PRESENTATION_FACTS:
            raise ValueError("channel presentation section exceeds the fact bound")
        if self.description is not None:
            _bounded_text("section.description", self.description, 1_024)


@dataclass(frozen=True, slots=True)
class ChannelPresentationEnvelope:
    """Canonical channel-neutral facts and mandatory safety context."""

    canonical_text: str
    artifact_version: Literal[1, 2] | None
    sections: tuple[ChannelPresentationSection, ...]
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    authority: str
    unavailable: bool
    web_url: str | None = None
    artifact_degraded: bool = False
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _bounded_text("canonical_text", self.canonical_text, MAX_PRESENTATION_TEXT_CHARS)
        _bounded_text("authority", self.authority, 256)
        if self.execution_authority:
            raise ValueError("channel presentation MUST NOT grant execution authority")
        if len(self.sections) > MAX_PRESENTATION_SECTIONS:
            raise ValueError("channel presentation exceeds the section bound")
        if len(self.limitations) > MAX_PRESENTATION_LIMITATIONS:
            raise ValueError("channel presentation exceeds the limitation bound")
        if len(self.evidence_refs) > 16:
            raise ValueError("channel presentation exceeds the evidence-reference bound")
        for limitation in self.limitations:
            _bounded_text("limitation", limitation, 1_024)
        for evidence_ref in self.evidence_refs:
            _bounded_text("evidence_ref", evidence_ref, 1_024)
        if self.web_url is not None:
            _bounded_text("web_url", self.web_url, 2_048)


@dataclass(frozen=True, slots=True)
class ChannelPresentationPayload:
    """Pure renderer output ready for a separate transport adapter."""

    renderer_id: str
    body: Mapping[str, object]
    fallback_text: str
    degraded_to_text: bool
    omitted_visuals: int = 0

    def __post_init__(self) -> None:
        _bounded_text("renderer_id", self.renderer_id, 128)
        _bounded_text("fallback_text", self.fallback_text, MAX_PRESENTATION_TEXT_CHARS)
        if self.omitted_visuals < 0:
            raise ValueError("channel presentation omitted_visuals MUST be non-negative")


class ChannelPresentationRenderError(ValueError):
    """Mandatory presentation content cannot fit the declared capability profile."""


@runtime_checkable
class ChannelPresentationRenderer(Protocol):
    """Render a canonical envelope without transport, I/O, or authority."""

    renderer_id: str
    capabilities: ChannelPresentationCapabilities

    def render(self, envelope: ChannelPresentationEnvelope) -> ChannelPresentationPayload: ...


def _bounded_text(name: str, value: str, maximum: int) -> None:
    if not value or not value.strip() or len(value) > maximum:
        raise ValueError(f"channel presentation {name} MUST be bounded and non-empty")
    if any(ord(character) < 32 and character not in {"\n", "\t"} for character in value):
        raise ValueError(f"channel presentation {name} contains control characters")


__all__ = [
    "ChannelPresentationCapabilities",
    "ChannelPresentationEnvelope",
    "ChannelPresentationFact",
    "ChannelPresentationPayload",
    "ChannelPresentationRenderError",
    "ChannelPresentationRenderer",
    "ChannelPresentationSection",
    "MAX_PRESENTATION_FACTS",
]
