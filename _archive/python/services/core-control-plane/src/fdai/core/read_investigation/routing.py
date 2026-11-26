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
    if not isinstance(question, str) or not question.strip():
        return None
    candidates: list[str] = []
    seen_folded: set[str] = set()
    for raw_token in _RESOURCE_TOKEN.findall(question):
        token = raw_token.rstrip(".()")
        if len(token) < 2:
            continue
        folded = token.casefold()
        if folded in _RESOURCE_WORDS:
            continue
        if "-" in token or any(character.isdigit() for character in token):
            if folded not in seen_folded:
                seen_folded.add(folded)
                candidates.append(token)
    return candidates[0] if len(candidates) == 1 else None


__all__ = ["resource_name_from_question"]
