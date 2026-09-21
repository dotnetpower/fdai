"""Pure validation helpers for Thor verdict dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.shared.contracts.models import Autonomy


def resolved_autonomy_ceiling(verdict: Mapping[str, Any]) -> Autonomy:
    """Return the most restrictive typed ceiling carried by one verdict."""
    values: list[Autonomy] = []
    raw = verdict.get("resolved_autonomy_ceiling")
    if raw is not None:
        if not isinstance(raw, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(raw))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    operational_context = verdict.get("operational_context")
    if operational_context is not None:
        if not isinstance(operational_context, Mapping):
            return Autonomy.SHADOW_ONLY
        context_ceiling = operational_context.get("autonomy_ceiling")
        if not isinstance(context_ceiling, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(context_ceiling))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    if not values:
        return Autonomy.SHADOW_ONLY
    rank = {
        Autonomy.SHADOW_ONLY: 0,
        Autonomy.ENFORCE_HIL: 1,
        Autonomy.ENFORCE_AUTO: 2,
    }
    return min(values, key=rank.__getitem__)


def selected_action_matches(decision_case: Mapping[str, Any], action_type: str) -> bool:
    """Check that the selected bounded option names the dispatched ActionType."""
    selected = decision_case.get("selected_option_id")
    options = decision_case.get("options")
    if not isinstance(selected, str) or not isinstance(options, list):
        return False
    return any(
        isinstance(option, Mapping)
        and option.get("option_id") == selected
        and option.get("action_type") == action_type
        and isinstance(option.get("effects"), list)
        and bool(option["effects"])
        for option in options
    )


__all__ = ["resolved_autonomy_ceiling", "selected_action_matches"]
