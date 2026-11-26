"""Shared measured metadata for conversation model calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.prompts.types import PromptReplayManifest


@dataclass(frozen=True, slots=True)
class ConversationModelObservation:
    """Measured provider metadata for one authority-free model call."""

    model: str
    usage: Mapping[str, int] | None
    trace_call: Mapping[str, object]
    prompt_replay_manifest: PromptReplayManifest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("conversation model observation requires a non-empty model name")
        if self.usage is not None and any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.usage.values()
        ):
            raise ValueError("conversation model usage values MUST be non-negative integers")


@dataclass(frozen=True, slots=True)
class ConversationModelResponse:
    """One raw proposal paired with its already-issued provider observation."""

    proposal: Mapping[str, object]
    observation: ConversationModelObservation


__all__ = ["ConversationModelObservation", "ConversationModelResponse"]
