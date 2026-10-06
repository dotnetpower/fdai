"""Attach the bound environment context to question-form model payloads.

Only the question form and its blind constraint reader receive the context. A name that
the provider-input redactor would rewrite, or whose decoding reveals a secret or an exact
identifier, is withheld and counted, because a verbatim call holds on any redaction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fdai.core.conversation.semantic_environment_context import (
    current_environment_context,
    safe_environment_context,
)
from fdai.delivery.azure.llm.input_detection import secret_spans
from fdai.delivery.azure.llm.model_trace import (
    ModelInputMinimizationError,
    prepare_model_messages,
)

ENVIRONMENT_CALLS = frozenset({"semantic-question-form", "semantic-constraint-extraction"})


def with_environment(
    name: str,
    payload: Mapping[str, Any],
    *,
    hides: Callable[[str], bool],
) -> Mapping[str, Any]:
    """Return ``payload`` with the safe environment context for an eligible call."""

    if name not in ENVIRONMENT_CALLS:
        return payload
    environment = safe_environment_context(
        current_environment_context(),
        unsafe=lambda text: bool(secret_spans(text)) or hides(text) or _redacted(text),
    )
    return payload if environment is None else {**payload, "environment": environment}


def _redacted(text: str) -> bool:
    if not text:
        return False
    try:
        prepared = prepare_model_messages(({"role": "user", "content": text},))
    except ModelInputMinimizationError:
        return True
    return prepared.receipt.redaction_replacement_count > 0


__all__ = ["ENVIRONMENT_CALLS", "with_environment"]
