"""Concrete instance factory for the 15 pantheon agents.

Returns a mapping ``{name: Agent}``. Used by tests and by later waves
to wire concrete handlers into the bus adapter.
"""

from __future__ import annotations

from collections.abc import Callable

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.base import Agent
from fdai.agents._framework.vertical_precedence import InitialVerticalPrecedence
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.loki import Loki
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.njord import Njord
from fdai.agents.norns import Norns
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.core.impact_analysis import ChangeAssessmentService
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_planning import SpecialistPlanningCoordinator

PlanningCoordinator = SpecialistPlanningCoordinator

# Every pantheon subclass provides a zero-arg constructor that builds
# its baseline in-memory dependencies. Wave-2+ subclasses accept
# keyword overrides for real adapters; the factory here uses the
# defaults so tests can instantiate the pantheon without wiring
# backends.
_CLASSES: tuple[Callable[[], Agent], ...] = (
    lambda: Odin(vertical_precedence=InitialVerticalPrecedence()),
    Thor,
    Forseti,
    Huginn,
    Heimdall,
    Vidar,
    Var,
    Bragi,
    Saga,
    Mimir,
    Muninn,
    Norns,
    Njord,
    Freyr,
    Loki,
)


def instantiate_pantheon() -> dict[str, Agent]:
    """Instantiate all 15 pantheon agents and return them keyed by name."""
    instances: dict[str, Agent] = {}
    for construct in _CLASSES:
        agent = construct()
        instances[agent.spec.name] = agent
    return instances


def configured_forseti(
    *,
    rbac: dict[str, frozenset[str]] | None,
    action_semantics: ActionSemanticsCatalog | None,
    operational_context: OperationalContextMaterializer | None,
    operational_planner: SpecialistPlanningCoordinator | None,
    change_assessor: ChangeAssessmentService | None,
) -> Forseti | None:
    """Build Forseti only when composition supplies an optional binding."""
    if all(
        value is None
        for value in (
            rbac,
            action_semantics,
            operational_context,
            operational_planner,
            change_assessor,
        )
    ):
        return None
    return Forseti(
        rbac=rbac,
        action_semantics=action_semantics,
        operational_context=operational_context,
        operational_planner=operational_planner,
        change_assessor=change_assessor,
    )


__all__ = ["PlanningCoordinator", "configured_forseti", "instantiate_pantheon"]
