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


def contextualize_inventory_screen_scope(
    prompt: str,
    view_context: Mapping[str, object],
) -> tuple[str, bool]:
    """Bind a current-screen inventory question to one selected resource group hint."""

    from fdai.delivery.read_api.routes.chat_resource_context import is_bounded_resource_name

    resolver = default_inventory_query_language_resolver()
    selected_scope = resolver.has(resolver.registry.scopes, "active_view", prompt) or resolver.has(
        resolver.registry.signals,
        "continuation",
        prompt,
    )
    if (
        str(view_context.get("routeId") or "").casefold() != "architecture"
        or not selected_scope
        or not is_inventory_question(prompt)
    ):
        return prompt, False
    records = view_context.get("records")
    selected = records.get("selected_resource") if isinstance(records, Mapping) else None
    resource = selected[0] if isinstance(selected, list) and len(selected) == 1 else None
    if not isinstance(resource, Mapping) or resource.get("type") != "resource-group":
        return prompt, False
    name = resource.get("name")
    if not is_bounded_resource_name(name):
        return prompt, False
    return f"{prompt} {name}", True


__all__ = [
    "SUBSCRIPTION_ROOT",
    "SUBSCRIPTION_ROOT_LIMIT",
    "contextualize_inventory_screen_scope",
    "contextualize_inventory_scope_followup",
    "requests_subscription_inventory",
]
