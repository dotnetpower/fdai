"""Exact resource identifier parsing for verified read-investigation intent."""

from __future__ import annotations

import re

_RESOURCE_TOKEN = re.compile(r"(?<![A-Za-z0-9_.()-])[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}")
_RESOURCE_WORDS = frozenset(
    {
        "activity",
        "current",
        "customer-initiated",
        "event",
        "guest",
        "health",
        "history",
        "platform",
        "platform-initiated",
        "read-only",
        "resource",
        "shutdown",
        "state",
        "stopped",
    }
)


def resource_name_from_question(question: str) -> str | None:
    """Return one identifier-like resource name or abstain on ambiguity."""
    candidates = [
        token
        for token in _RESOURCE_TOKEN.findall(question)
        if token.casefold() not in _RESOURCE_WORDS
        and ("-" in token or any(character.isdigit() for character in token))
    ]
    unique = tuple(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


__all__ = ["resource_name_from_question"]
