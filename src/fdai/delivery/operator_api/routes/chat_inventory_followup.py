"""Deterministic scope-only follow-ups for verified inventory reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.delivery.operator_api.routes.chat_inventory_compiler import is_inventory_question
from fdai.delivery.operator_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)

SUBSCRIPTION_ROOT = "azure-subscription"
SUBSCRIPTION_ROOT_LIMIT = 1_000


class InventoryScreenScopeStatus(StrEnum):
    RESOLVED = "resolved"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InventoryScreenScopeResolution:
    status: InventoryScreenScopeStatus

    def to_context(self) -> dict[str, str]:
        context = {"authority": "selector_hint", "status": self.status.value}
        if self.status is InventoryScreenScopeStatus.UNAVAILABLE:
            context["reason"] = "active_view_resource_group_unavailable"
        return context


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
) -> tuple[str, InventoryScreenScopeResolution | None]:
    """Bind a current-screen inventory question to one selected resource group hint."""

    from fdai.delivery.operator_api.routes.chat_resource_context import is_bounded_resource_name

    resolver = default_inventory_query_language_resolver()
    selected_scope = resolver.has(resolver.registry.scopes, "active_view", prompt) or resolver.has(
        resolver.registry.signals,
        "continuation",
        prompt,
    )
    screen_group_intent = resolver.has(
        resolver.registry.signals,
        "active_view_resource_group",
        prompt,
    )
    if (
        str(view_context.get("routeId") or "").casefold() != "architecture"
        or not selected_scope
        or not (is_inventory_question(prompt) or screen_group_intent)
    ):
        return prompt, None
    records = view_context.get("records")
    selected = records.get("selected_resource") if isinstance(records, Mapping) else None
    resource = selected[0] if isinstance(selected, list) and len(selected) == 1 else None
    if not isinstance(resource, Mapping) or resource.get("type") != "resource-group":
        return prompt, InventoryScreenScopeResolution(InventoryScreenScopeStatus.UNAVAILABLE)
    name = resource.get("name")
    if not is_bounded_resource_name(name):
        return prompt, InventoryScreenScopeResolution(InventoryScreenScopeStatus.UNAVAILABLE)
    return (
        f"{prompt} {name}",
        InventoryScreenScopeResolution(InventoryScreenScopeStatus.RESOLVED),
    )


__all__ = [
    "SUBSCRIPTION_ROOT",
    "SUBSCRIPTION_ROOT_LIMIT",
    "InventoryScreenScopeResolution",
    "InventoryScreenScopeStatus",
    "contextualize_inventory_screen_scope",
    "contextualize_inventory_scope_followup",
    "requests_subscription_inventory",
]
