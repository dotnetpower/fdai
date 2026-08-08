"""Ground contextual intent arguments in current and prior conversation text."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.conversation.session import Turn


def contextual_arguments_grounded(
    arguments: Mapping[str, Any],
    *,
    utterance: str,
    prior_turns: Sequence[Turn],
) -> bool:
    """Return true when every non-empty scalar argument occurs in conversation text."""

    source = _normalize(" ".join((*(turn.content for turn in prior_turns), utterance)))
    return all(
        normalized in source
        for value in _leaf_values(arguments)
        if (normalized := _normalize(str(value)))
    )


def _leaf_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        return tuple(leaf for nested in value.values() for leaf in _leaf_values(nested))
    if isinstance(value, (list, tuple)):
        return tuple(leaf for nested in value for leaf in _leaf_values(nested))
    if value is None:
        return ()
    return (value,)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(part for part in re.split(r"[^\w]+", normalized) if part)


__all__ = ["contextual_arguments_grounded"]
