"""Conservative prompt and request token estimation primitives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache

import tiktoken
from tiktoken.core import Encoding

_CHAT_MESSAGE_OVERHEAD = 4
_CHAT_REPLY_OVERHEAD = 3


@lru_cache(maxsize=8)
def _encoding_for_model(model: str) -> Encoding | None:
    normalized = model.casefold()
    if any(family in normalized for family in ("gpt-5", "o1", "o3", "o4")):
        return tiktoken.get_encoding("o200k_base")
    if any(family in normalized for family in ("gpt-4", "gpt-35", "gpt-3.5")):
        return tiktoken.get_encoding("cl100k_base")
    return None


def estimate_prompt_tokens(text: str, *, model: str | None = None) -> int:
    """Estimate text tokens exactly for known model families or conservatively otherwise."""

    if not text:
        return 0
    if model is not None:
        encoding = _encoding_for_model(model)
        if encoding is not None:
            return len(encoding.encode(text, disallowed_special=()))
    return len(text.encode("utf-8"))


def estimate_chat_request_tokens(
    *,
    messages: Sequence[Mapping[str, object]],
    response_format: Mapping[str, object],
    reserved_output_tokens: int,
    model: str | None = None,
) -> int:
    """Estimate the complete serialized chat request plus reserved output."""

    if model is not None:
        message_tokens = _CHAT_REPLY_OVERHEAD
        for message in messages:
            message_tokens += _CHAT_MESSAGE_OVERHEAD
            message_tokens += sum(
                estimate_prompt_tokens(str(value), model=model) for value in message.values()
            )
        format_tokens = estimate_prompt_tokens(
            json.dumps(
                response_format,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            model=model,
        )
        return message_tokens + format_tokens + reserved_output_tokens
    return estimate_serialized_request_tokens(
        {
            "messages": list(messages),
            "response_format": response_format,
        },
        reserved_output_tokens=reserved_output_tokens,
        model=model,
    )


def estimate_serialized_request_tokens(
    request: Mapping[str, object],
    *,
    reserved_output_tokens: int,
    model: str | None = None,
) -> int:
    """Estimate one finalized provider request plus reserved output."""

    encoded = json.dumps(
        request,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return estimate_prompt_tokens(encoded, model=model) + reserved_output_tokens


def fit_prompt_to_token_budget(
    text: str,
    *,
    token_budget: int,
    model: str | None = None,
) -> tuple[str, bool]:
    """Return the longest text prefix within one token budget."""

    if token_budget < 0:
        raise ValueError("token_budget MUST NOT be negative")
    if estimate_prompt_tokens(text, model=model) <= token_budget:
        return text, False
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_prompt_tokens(text[:middle], model=model) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low], True


__all__ = [
    "estimate_chat_request_tokens",
    "estimate_prompt_tokens",
    "estimate_serialized_request_tokens",
    "fit_prompt_to_token_budget",
]
