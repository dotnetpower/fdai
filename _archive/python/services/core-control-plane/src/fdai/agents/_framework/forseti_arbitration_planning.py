"""Planning finalization helpers for Forseti arbitration."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from fdai.core.operational_planning import (
    SpecialistPlanningCoordinator,
    SpecialistPlanningProjection,
)

_LOGGER = logging.getLogger(__name__)


class PlanningFinalizationHost(Protocol):
    _operational_planner: SpecialistPlanningCoordinator | None

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


async def finalize_planning_projection(
    host: PlanningFinalizationHost,
    projection: Any,
    *,
    selected_option_id: str,
) -> tuple[Any, bool]:
    if not isinstance(projection, SpecialistPlanningProjection):
        return projection, False
    planner = host._operational_planner
    if planner is None:
        return projection, True
    try:
        return (
            await planner.finalize(
                projection,
                selected_option_id=selected_option_id,
                recorded_at=projection.case.created_at,
            ),
            False,
        )
    except Exception:  # noqa: BLE001 - incomplete finalization denies execution
        host.record_behavior("prospective_lineage:planning_failed")
        _LOGGER.warning(
            "prospective_lineage_planning_failed",
            extra={"selected_option_id": selected_option_id},
            exc_info=True,
        )
        return projection, True


__all__ = ["finalize_planning_projection"]
