"""Model-family-specific chat completion request fields."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.delivery.azure.llm.request_target import ModelRequestTarget

_COMPLETION_TOKEN_FAMILY = re.compile(r"(?:^|-)(?:gpt-5|o1|o3|o4)(?:[.-]|$)")


def completion_body_params(
    model_family_or_deployment: str,
    *,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Return token and temperature fields accepted by the model family.

    A reasoning family counts hidden reasoning against its completion tokens, so a caller
    that needs a short structured answer may bound that reasoning with ``reasoning_effort``.
    """

    normalized = model_family_or_deployment.strip().lower()
    if _COMPLETION_TOKEN_FAMILY.search(normalized):
        body: dict[str, Any] = {"max_completion_tokens": max_tokens}
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        return body
    return {"temperature": temperature, "max_tokens": max_tokens}


def target_body_params(
    target: ModelRequestTarget,
    *,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Return the fields for one request target, choosing by its resolved family first.

    A target without an endpoint binding is named after its capability, so only its family
    says whether the model bounds output with completion tokens.
    """

    return completion_body_params(
        target.model_family or target.deployment,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )


def uses_completion_token_budget(model_family_or_deployment: str) -> bool:
    """Return whether a family bounds output with completion tokens that include reasoning."""

    return bool(_COMPLETION_TOKEN_FAMILY.search(model_family_or_deployment.strip().lower()))


__all__ = ["completion_body_params", "target_body_params", "uses_completion_token_budget"]
