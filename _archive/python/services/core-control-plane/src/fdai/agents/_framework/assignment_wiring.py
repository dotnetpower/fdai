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
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents.forseti import Forseti
from fdai.agents.muninn import Muninn
from fdai.agents.var import Var
from fdai.core.human_assignment.execution_ports import HumanAccessAgentBindings
from fdai.core.human_assignment.knowledge_stage import HandoverKnowledgeStage
from fdai.shared.providers.handover_semantics import (
    HandoverSemanticCompiler,
    HandoverSemanticReviewer,
)


@dataclass(frozen=True, slots=True)
class AssignmentWorkflowBindings:
    """Pass only each agent's capability; no peer handles or mutable coordination state."""

    validate: AssignmentCheck
    review: AssignmentCheck
    materializer: AssignmentMaterializer
    clock: AssignmentClock = assignment_clock
    iam_reader: AssignmentIamRead | None = None
    knowledge_stages: tuple[HandoverKnowledgeStage, ...] = ()
    semantic_compiler: HandoverSemanticCompiler | None = None
    semantic_reviewer: HandoverSemanticReviewer | None = None
    human_access: HumanAccessAgentBindings | None = None


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
    for stage in bindings.knowledge_stages:
        participant = agents.get(stage.owner)
        if not isinstance(participant, HandoverKnowledgeMixin):
            raise TypeError("handover source stage requires its canonical agent owner")
        participant.bind_handover_knowledge(stage)
    if (bindings.semantic_compiler is None) != (bindings.semantic_reviewer is None):
        raise ValueError("handover semantics requires separate compiler and reviewer bindings")
    if bindings.semantic_compiler is not None and bindings.semantic_reviewer is not None:
        learner, steward = agents["Norns"], agents["Mimir"]
        if not isinstance(learner, HandoverKnowledgeMixin) or not isinstance(
            steward, HandoverKnowledgeMixin
        ):
            raise TypeError("handover semantics requires the fixed learner and Rule steward")
        learner.bind_handover_compiler(bindings.semantic_compiler)
        steward.bind_handover_reviewer(bindings.semantic_reviewer)


__all__ = ["AssignmentWorkflowBindings", "bind_assignment_workflow"]
