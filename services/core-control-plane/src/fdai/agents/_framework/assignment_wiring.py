"""Bind independent assignment responsibilities to the existing named agents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.agents._framework.assignment_workflow import (
    AssignmentCheck,
    AssignmentClock,
    AssignmentIamRead,
    AssignmentMaterializer,
    assignment_clock,
)
from fdai.agents._framework.base import Agent
from fdai.agents.forseti import Forseti
from fdai.agents.muninn import Muninn
from fdai.agents.var import Var


@dataclass(frozen=True, slots=True)
class AssignmentWorkflowBindings:
    """Pass only each agent's capability; no peer handles or mutable coordination state."""

    validate: AssignmentCheck
    review: AssignmentCheck
    materializer: AssignmentMaterializer
    clock: AssignmentClock = assignment_clock
    iam_reader: AssignmentIamRead | None = None


def bind_assignment_workflow(
    agents: Mapping[str, Agent], bindings: AssignmentWorkflowBindings | None
) -> None:
    """Bind before normal declared subscriptions; absent services remain explicit holds."""
    if bindings is None:
        return
    forseti, var, muninn = agents["Forseti"], agents["Var"], agents["Muninn"]
    if (
        not isinstance(forseti, Forseti)
        or not isinstance(var, Var)
        or not isinstance(muninn, Muninn)
    ):
        raise TypeError("assignment workflow requires the canonical judge, approver, and memory")
    forseti.bind_assignment_check(bindings.validate, clock=bindings.clock)
    if bindings.iam_reader is not None:
        forseti.bind_assignment_iam_reader(bindings.iam_reader)
    var.bind_assignment_check(bindings.review, clock=bindings.clock)
    muninn.bind_assignment_materializer(bindings.materializer, clock=bindings.clock)


__all__ = ["AssignmentWorkflowBindings", "bind_assignment_workflow"]
