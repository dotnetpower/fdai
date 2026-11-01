"""FDAI lifecycle agent. Lifecycle I0 polls, admits, dry-runs, and reports; it never applies."""

from __future__ import annotations

from fdai_lifecycle_agent.self_upgrade_fencing import (
    ComponentKind,
    ComponentSelfUpgradeController,
    ComponentSlotFence,
    RoleFencingError,
    SchemaDowngradeError,
    SelfUpgradeTransitionRecord,
    SlotId,
    SlotRole,
    TrialContinuityViolationError,
)

__all__ = [
    "ComponentKind",
    "ComponentSelfUpgradeController",
    "ComponentSlotFence",
    "RoleFencingError",
    "SchemaDowngradeError",
    "SelfUpgradeTransitionRecord",
    "SlotId",
    "SlotRole",
    "TrialContinuityViolationError",
]
