"""Pure capability attenuation for task workers."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.task_worker.models import AttenuatedCapabilities

_FORBIDDEN_CAPABILITIES = frozenset(
    {
        "approve_hil",
        "create_schedule",
        "cancel_schedule",
        "activate_break_glass",
        "approve_action",
        "run_runbook",
        "simulate_change",
        "submit_action",
        "propose_action",
        "execute_action",
        "execute_shell",
        "shell",
        "arbitrary_query",
        "query_arbitrary",
        "write_memory",
        "create_memory",
        "clarify",
        "spawn_worker",
        "nested_worker",
        "delegate_worker",
    }
)


def attenuate_capabilities(
    *,
    requested: frozenset[str],
    parent_visible: frozenset[str],
    profile_allowed: frozenset[str],
    side_effect_classes: Mapping[str, str],
) -> AttenuatedCapabilities:
    """Intersect both authorities and retain read-class tools only."""
    allowed: set[str] = set()
    denied: set[str] = set()
    for tool in sorted(requested):
        if (
            tool not in parent_visible
            or tool not in profile_allowed
            or tool in _FORBIDDEN_CAPABILITIES
            or side_effect_classes.get(tool) != "read"
        ):
            denied.add(tool)
            continue
        allowed.add(tool)
    return AttenuatedCapabilities(
        allowed_tools=frozenset(allowed),
        denied_tools=tuple(sorted(denied)),
    )


def forbidden_worker_capabilities() -> frozenset[str]:
    return _FORBIDDEN_CAPABILITIES


__all__ = ["attenuate_capabilities", "forbidden_worker_capabilities"]
