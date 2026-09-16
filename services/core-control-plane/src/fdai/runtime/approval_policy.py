"""Load explicit principal-to-ActionType human approval policy."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping


def approver_authorizer_from_environment(
    environment: Mapping[str, str],
) -> Callable[[str, str], bool] | None:
    """Load the shared explicit principal-to-ActionType approval policy."""

    raw = environment.get("FDAI_PANTHEON_APPROVER_ACTIONS_JSON", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON MUST be valid JSON") from exc
    if not isinstance(parsed, dict) or len(parsed) > 1_000:
        raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON MUST be a bounded object")
    policy: dict[str, frozenset[str]] = {}
    for principal, actions in parsed.items():
        if (
            not isinstance(principal, str)
            or not principal.strip()
            or len(principal) > 256
            or not isinstance(actions, list)
            or not actions
            or len(actions) > 256
            or any(
                not isinstance(action, str) or not action.strip() or len(action) > 256
                for action in actions
            )
        ):
            raise ValueError(
                "FDAI_PANTHEON_APPROVER_ACTIONS_JSON entries MUST map bounded principals "
                "to non-empty bounded ActionType arrays"
            )
        normalized = principal.strip().casefold()
        if normalized in policy:
            raise ValueError("FDAI_PANTHEON_APPROVER_ACTIONS_JSON principals MUST be unique")
        policy[normalized] = frozenset(action.strip() for action in actions)

    return lambda principal, action_type: (
        action_type in policy.get(principal.strip().casefold(), frozenset())
    )


__all__ = ["approver_authorizer_from_environment"]
