"""Load explicit principal-to-ActionType human approval policy."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

_REPORT_LINE_SCOPES_ENV = "FDAI_REPORT_LINE_APPROVER_SCOPES_JSON"


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


def report_line_scope_authorizer_from_environment(
    environment: Mapping[str, str],
) -> Callable[[str, str, str], bool] | None:
    """Load exact principal-to-ActionType-to-scope report-line approval policy."""

    raw = environment.get(_REPORT_LINE_SCOPES_ENV, "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_REPORT_LINE_SCOPES_ENV} MUST be valid JSON") from exc
    if not isinstance(parsed, dict) or not 1 <= len(parsed) <= 1_000:
        raise ValueError(f"{_REPORT_LINE_SCOPES_ENV} MUST be a bounded non-empty object")
    policy: dict[tuple[str, str], frozenset[str]] = {}
    for principal, actions in parsed.items():
        if (
            not isinstance(principal, str)
            or not principal.strip()
            or principal != principal.strip()
            or len(principal) > 256
            or not isinstance(actions, dict)
            or not 1 <= len(actions) <= 256
        ):
            raise ValueError(
                f"{_REPORT_LINE_SCOPES_ENV} entries MUST map exact principals "
                "to bounded ActionType objects"
            )
        normalized = principal.casefold()
        for action_type, scopes in actions.items():
            if (
                not isinstance(action_type, str)
                or not action_type
                or action_type != action_type.strip()
                or len(action_type) > 256
                or not isinstance(scopes, list)
                or not 1 <= len(scopes) <= 256
                or any(
                    not isinstance(scope, str)
                    or not scope
                    or scope != scope.strip()
                    or len(scope) > 512
                    for scope in scopes
                )
            ):
                raise ValueError(
                    f"{_REPORT_LINE_SCOPES_ENV} ActionTypes MUST map to exact bounded scopes"
                )
            key = (normalized, action_type)
            if key in policy:
                raise ValueError(f"{_REPORT_LINE_SCOPES_ENV} entries MUST be unique")
            policy[key] = frozenset(scopes)
    return lambda principal, action_type, scope_ref: (
        scope_ref in policy.get((principal.strip().casefold(), action_type), frozenset())
    )


__all__ = [
    "approver_authorizer_from_environment",
    "report_line_scope_authorizer_from_environment",
]
