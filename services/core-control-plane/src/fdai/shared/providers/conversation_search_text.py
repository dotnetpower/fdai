"""Pure bilingual matching and snippet helpers for conversation search adapters."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from fdai.shared.providers.conversation_search import (
    ConversationSearchMode,
    ConversationSearchSnippet,
    ConversationTextRange,
)

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ConversationTextMatch:
    rank: float
    ranges: tuple[ConversationTextRange, ...]


def match_conversation_text(
    content: str,
    query_text: str,
    mode: ConversationSearchMode,
) -> ConversationTextMatch | None:
    normalized = normalize_search_text(content)
    requested = normalize_search_text(query_text)
    query_tokens = search_tokens(requested)
    content_tokens = search_tokens(normalized)
    needles: tuple[str, ...]
    if mode is ConversationSearchMode.PHRASE:
        matched = requested in normalized
        needles = (requested,)
    elif mode is ConversationSearchMode.PREFIX:
        matched = bool(query_tokens) and all(
            any(token.startswith(prefix) for token in content_tokens) for prefix in query_tokens
        )
        needles = query_tokens
    else:
        matched = bool(query_tokens) and all(token in normalized for token in query_tokens)
        needles = query_tokens
    if not matched:
        return None
    ranges = _ranges(normalized, needles) if len(normalized) == len(content) else ()
    return ConversationTextMatch(
        rank=min(1.0, len(ranges) / max(1, len(query_tokens))),
        ranges=ranges,
    )


def build_conversation_snippet(
    content: str,
    ranges: tuple[ConversationTextRange, ...] = (),
) -> ConversationSearchSnippet:
    if len(content) <= 500:
        return ConversationSearchSnippet(text=content, highlights=ranges)
    center = ranges[0].start if ranges else 0
    start = max(0, center - 150)
    end = min(len(content), start + 500)
    start = max(0, end - 500)
    text = content[start:end]
    adjusted = tuple(
        ConversationTextRange(max(item.start, start) - start, min(item.end, end) - start)
        for item in ranges
        if item.end > start and item.start < end
    )
    return ConversationSearchSnippet(text=text, highlights=adjusted)


def normalize_search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def search_tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value))


def _ranges(
    content: str,
    needles: tuple[str, ...],
) -> tuple[ConversationTextRange, ...]:
    found: list[ConversationTextRange] = []
    for needle in needles:
        start = content.find(needle)
        if start >= 0:
            found.append(ConversationTextRange(start, start + len(needle)))
    found.sort(key=lambda item: (item.start, item.end))
    deduped: list[ConversationTextRange] = []
    for item in found:
        if deduped and item.start < deduped[-1].end:
            continue
        deduped.append(item)
    return tuple(deduped[:32])


__all__ = [
    "ConversationTextMatch",
    "build_conversation_snippet",
    "match_conversation_text",
    "normalize_search_text",
    "search_tokens",
]
