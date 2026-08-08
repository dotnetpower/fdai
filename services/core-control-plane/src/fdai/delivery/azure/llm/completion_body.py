"""Model-family-specific chat completion request fields."""

from __future__ import annotations

import re
from typing import Any

_COMPLETION_TOKEN_FAMILY = re.compile(r"(?:^|-)(?:gpt-5|o1|o3|o4)(?:[.-]|$)")


def completion_body_params(
    model_family_or_deployment: str,
    *,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Return token and temperature fields accepted by the model family."""

    normalized = model_family_or_deployment.strip().lower()
    if _COMPLETION_TOKEN_FAMILY.search(normalized):
        return {"max_completion_tokens": max_tokens}
    return {"temperature": temperature, "max_tokens": max_tokens}


__all__ = ["completion_body_params"]
