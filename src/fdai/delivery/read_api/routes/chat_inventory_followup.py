"""Deterministic scope-only follow-ups for verified inventory reads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

from fdai.delivery.read_api.routes.chat_inventory_compiler import is_inventory_question

SUBSCRIPTION_ROOT: Final = "azure-subscription"
SUBSCRIPTION_ROOT_LIMIT: Final = 1_000

_SUBSCRIPTION_FRAGMENT: Final = re.compile(
    r"\s*(?:"
    r"구독(?:\s*(?:전체|범위|단위))?(?:에서|으로|로)?|"
    r"전체\s*구독(?:\s*범위)?(?:에서|으로|로)?|"
    r"(?:in|from|across)\s+(?:the\s+)?(?:entire\s+|whole\s+)?subscription|"
    r"subscription(?:\s+(?:wide|scope))?"
    r")\s*[?!.]?\s*",
    re.IGNORECASE,
)
_SUBSCRIPTION_SCOPE: Final = re.compile(
    r"\bsubscription(?:\s+(?:wide|scope))?\b|구독",
    re.IGNORECASE,
)


def contextualize_inventory_scope_followup(
    prompt: str,
    history: Sequence[Mapping[str, str]],
) -> tuple[str, bool]:
    """Reuse only the latest user inventory intent for one scope-only fragment."""

    if _SUBSCRIPTION_FRAGMENT.fullmatch(prompt) is None:
        return prompt, False
    for turn in reversed(history):
        if turn.get("role") not in {"user", "operator"}:
            continue
        prior_prompt = str(turn.get("content") or "").strip()
        if not prior_prompt or not is_inventory_question(prior_prompt):
            return prompt, False
        return f"{prior_prompt} 구독 전체에서", True
    return prompt, False


def requests_subscription_inventory(prompt: str) -> bool:
    """Return whether an inventory prompt explicitly requests subscription scope."""

    return _SUBSCRIPTION_SCOPE.search(prompt) is not None


__all__ = [
    "SUBSCRIPTION_ROOT",
    "SUBSCRIPTION_ROOT_LIMIT",
    "contextualize_inventory_scope_followup",
    "requests_subscription_inventory",
]
