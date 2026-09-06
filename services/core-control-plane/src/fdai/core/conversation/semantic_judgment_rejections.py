"""Stable semantic judgment rejection reasons safe for content-free telemetry."""

from __future__ import annotations

SAFE_SEMANTIC_JUDGMENT_REJECTION_REASONS = frozenset(
    {
        "ambiguous semantic judgment MUST carry one clarification",
        "primary semantic intent MUST NOT be duplicated",
        "semantic link intent MUST use query namespace",
        "semantic judgment action subject MUST match draft posture",
        "semantic judgment alternatives MUST be unique",
        "semantic judgment ambiguity MUST match its unresolved meaning",
        "semantic judgment clarification MUST be one question",
        "semantic judgment confidence MUST be finite",
        "semantic current-state intent requires a Resource target",
        "semantic direct response answer MUST be one paragraph",
        "semantic direct response answer MUST be trimmed",
        "semantic direct response answer MUST remain unambiguous and advisory",
        "semantic direct response intent MUST carry exactly one model-authored answer",
        "semantic direct response locale does not match the request",
        "semantic direct response profile digest does not match",
        "semantic judgment requested_facets MUST be unique",
        "semantic judgment secondary_intents MUST be unique",
        "semantic target source span exceeds the utterance",
        "semantic target source span does not match the utterance",
        "semantic target source span MUST be ordered",
    }
)

__all__ = ["SAFE_SEMANTIC_JUDGMENT_REJECTION_REASONS"]
