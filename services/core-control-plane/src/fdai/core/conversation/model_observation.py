"""Shared measured metadata for conversation model calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationModelObservation:
    """Measured provider metadata for one authority-free model call."""

    model: str
    usage: Mapping[str, int] | None
    trace_call: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConversationModelResponse:
    """One raw proposal paired with its already-issued provider observation."""

    proposal: Mapping[str, object]
    observation: ConversationModelObservation


__all__ = ["ConversationModelObservation", "ConversationModelResponse"]
