"""Deterministic scope-only follow-ups for verified inventory reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai.delivery.read_api.routes.chat_inventory_compiler import is_inventory_question
from fdai.delivery.read_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)

SUBSCRIPTION_ROOT = "azure-subscription"
SUBSCRIPTION_ROOT_LIMIT = 1_000


def contextualize_inventory_scope_followup(
    prompt: str,
    history: Sequence[Mapping[str, str]],
) -> tuple[str, bool]:
    """Reuse only the latest user inventory intent for one scope-only fragment."""

    resolver = default_inventory_query_language_resolver()
    subscription = resolver.registry.scopes["subscription"]
    if not resolver.is_exact(prompt, subscription.terms):
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

    resolver = default_inventory_query_language_resolver()
    return resolver.has(resolver.registry.scopes, "subscription", prompt)


__all__ = [
    "SUBSCRIPTION_ROOT",
    "SUBSCRIPTION_ROOT_LIMIT",
    "contextualize_inventory_scope_followup",
    "requests_subscription_inventory",
]
