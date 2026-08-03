from __future__ import annotations

from typing import cast

from fdai.agents._framework.factory import configured_forseti
from fdai.agents.forseti import Forseti
from fdai.core.operational_planning import SpecialistPlanningCoordinator


def test_configured_forseti_preserves_baseline_instance() -> None:
    assert (
        configured_forseti(
            rbac=None,
            action_semantics=None,
            operational_context=None,
            operational_planner=None,
            change_assessor=None,
        )
        is None
    )


def test_configured_forseti_accepts_planning_binding() -> None:
    planner = cast(SpecialistPlanningCoordinator, object())

    agent = configured_forseti(
        rbac=None,
        action_semantics=None,
        operational_context=None,
        operational_planner=planner,
        change_assessor=None,
    )

    assert isinstance(agent, Forseti)
