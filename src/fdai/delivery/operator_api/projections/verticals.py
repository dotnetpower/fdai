"""Classify audit action kinds into Overview verticals.

This pure projection helper owns only the shared deterministic mapping. It
reads no state, registers no route, and grants no policy, approval, or
execution authority.
"""

from fdai.core.verticals.cost_governance.finops import FinOpsActionKind

_FINOPS_KINDS: frozenset[str] = frozenset(kind.value for kind in FinOpsActionKind)
_COST_HINTS: tuple[str, ...] = ("right_size", "shutdown", "orphan", "cost", "idle", "spot")
_RESILIENCE_HINTS: tuple[str, ...] = (
    "backup",
    "failover",
    "zone",
    "snapshot",
    "dr",
    "restore",
    "replica",
    "recovery",
    "rollback",
)


def audit_vertical(action_kind: str) -> str:
    """Map an audit action kind onto resilience, change safety, or cost."""
    normalized = action_kind.lower()
    hint_key = normalized.replace("-", "_")
    if normalized in _FINOPS_KINDS or any(hint in hint_key for hint in _COST_HINTS):
        return "cost"
    if any(hint in hint_key for hint in _RESILIENCE_HINTS):
        return "resilience"
    return "change_safety"


__all__ = ["audit_vertical"]
