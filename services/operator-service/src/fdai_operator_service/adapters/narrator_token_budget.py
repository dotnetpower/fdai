"""Model-aware token accounting for the independent service-local narrator."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import tiktoken
from tiktoken.core import Encoding

_MESSAGE_OVERHEAD = 4
_REPLY_OVERHEAD = 3


@dataclass(frozen=True, slots=True)
class NarratorContextReceipt:
    """Content-free accounting for one narrator request context selection."""

    request_token_estimate: int
    request_token_budget: int
    reserved_output_tokens: int
    source_history_items: int
    included_history_items: int
    omitted_history_items: int
    shortened_history_items: int
    context_shortened: bool


@lru_cache(maxsize=8)
def _encoding(model: str) -> Encoding | None:
    normalized = model.casefold()
    if any(family in normalized for family in ("gpt-5", "o1", "o3", "o4")):
        return tiktoken.get_encoding("o200k_base")
    if any(family in normalized for family in ("gpt-4", "gpt-35", "gpt-3.5")):
        return tiktoken.get_encoding("cl100k_base")
    return None


def text_tokens(text: str, *, model: str) -> int:
    """Return the token count for one model-family text value."""

    encoding = _encoding(model)
    if encoding is None:
        return len(text.encode("utf-8"))
    return len(encoding.encode(text, disallowed_special=()))


def chat_request_tokens(
    messages: Sequence[Mapping[str, Any]],
    *,
    model: str,
    reserved_output_tokens: int,
) -> int:
    """Estimate one chat request including message framing and reserved output."""

    total = _REPLY_OVERHEAD + reserved_output_tokens
    for message in messages:
        total += _MESSAGE_OVERHEAD
        total += sum(text_tokens(str(value), model=model) for value in message.values())
    return total


def fit_text(text: str, *, model: str, token_budget: int) -> tuple[str, bool]:
    """Return the longest prefix that fits an exact model token budget."""

    if token_budget < 1:
        return "", bool(text)
    encoding = _encoding(model)
    if encoding is not None:
        tokens = encoding.encode(text, disallowed_special=())
        if len(tokens) <= token_budget:
            return text, False
        return encoding.decode(tokens[:token_budget]), True
    if len(text.encode("utf-8")) <= token_budget:
        return text, False
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(text[:middle].encode("utf-8")) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low], True


def bounded_json(value: object, *, model: str, token_budget: int) -> tuple[str, bool]:
    """Serialize deterministic JSON and fit it without changing the source value."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return fit_text(encoded, model=model, token_budget=token_budget)


__all__ = [
    "NarratorContextReceipt",
    "bounded_json",
    "chat_request_tokens",
    "fit_text",
    "text_tokens",
]
