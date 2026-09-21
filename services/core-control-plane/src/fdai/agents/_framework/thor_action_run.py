"""Durable ActionRun model and bounded planning-lineage codecs for Thor."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import ValidationError

from fdai.agents._framework import action_run_lineage
from fdai.agents._framework.action_run_lineage import (
    bounded_operational_context,
    optional_datetime,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_effect_verification import (
    durable_effect_verification,
    effect_verification_mapping,
    validate_effect_verification,
)
from fdai.core.operational_context.test_context_dispatch import TestContextDispatchBinding
from fdai.core.operational_planning import KineticActionProposal
from fdai.core.operational_planning.prospective_lineage import ProspectiveLineage
from fdai.shared.contracts.models import Autonomy


@dataclass
class ActionRun:
    correlation_id: str
    action_type: str
    resource_id: str | None
    state: ActionRunState
    verdict: str
    action_id: str | None = None
    idempotency_key: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    shadow_mode: bool = False
    resolved_autonomy_ceiling: Autonomy = Autonomy.SHADOW_ONLY
    quorum_required: int = 1
    outcome: str | None = None
    initiator_principal: str | None = None
    rollback_contract: str = "state_forward_only"
    rollback_ref: str | None = None
    decision_case: dict[str, Any] | None = None
    operational_context: dict[str, Any] | None = None
    test_context_guard: TestContextDispatchBinding | None = None
    workflow_action: dict[str, Any] | None = None
    kinetic_proposal: dict[str, Any] | None = None
    prospective_lineage: dict[str, Any] | None = None
    execution_audit_receipt: str | None = None
    effect_verification_ref: str | None = None
    execution_closure_ref: str | None = None
    effect_verified_at: datetime | None = None
    approval_expires_at: datetime | None = None
    terminal_published: bool = False
    resource_claimed: bool = False
    history: list[ActionRunState] = field(default_factory=list)

    def __post_init__(self) -> None:
        action_run_lineage.validate_action_run_lineage(self.action_id, self.workflow_action)
        if not self.idempotency_key:
            self.idempotency_key = self.correlation_id
        validate_effect_verification(
            self.effect_verification_ref,
            self.execution_closure_ref,
            self.effect_verified_at,
        )

    def transition(self, new_state: ActionRunState) -> None:
        self.history.append(self.state)
        self.state = new_state

    def to_dict(self) -> dict[str, Any]:
        """Serialize for a durable :class:`ActionRunStore` backend."""
        return {
            "correlation_id": self.correlation_id,
            "action_type": self.action_type,
            "resource_id": self.resource_id,
            "state": self.state.value,
            "verdict": self.verdict,
            "action_id": self.action_id,
            "idempotency_key": self.idempotency_key,
            "params": deepcopy(self.params),
            "shadow_mode": self.shadow_mode,
            "resolved_autonomy_ceiling": self.resolved_autonomy_ceiling.value,
            "quorum_required": self.quorum_required,
            "outcome": self.outcome,
            "initiator_principal": self.initiator_principal,
            "rollback_contract": self.rollback_contract,
            "rollback_ref": self.rollback_ref,
            "decision_case": self.decision_case,
            "operational_context": deepcopy(self.operational_context),
            **(
                {"test_context_guard": self.test_context_guard.model_dump(mode="json")}
                if self.test_context_guard is not None
                else {}
            ),
            "workflow_action": deepcopy(self.workflow_action),
            "kinetic_proposal": deepcopy(self.kinetic_proposal),
            "prospective_lineage": deepcopy(self.prospective_lineage),
            "execution_audit_receipt": self.execution_audit_receipt,
            **effect_verification_mapping(self),
            "approval_expires_at": (
                self.approval_expires_at.isoformat()
                if self.approval_expires_at is not None
                else None
            ),
            "terminal_published": False,
            "resource_claimed": self.resource_claimed,
            "history": [state.value for state in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionRun:
        if data.get("kinetic_proposal") is None and data.get("prospective_lineage") is not None:
            raise ValueError("durable ActionRun prospective lineage requires a kinetic proposal")
        operational_context = bounded_operational_context(data.get("operational_context"))
        resolved_autonomy_ceiling = Autonomy(
            data.get("resolved_autonomy_ceiling", Autonomy.SHADOW_ONLY.value)
        )
        if data.get("operational_context") is not None and operational_context is None:
            resolved_autonomy_ceiling = Autonomy.SHADOW_ONLY
        run = cls(
            correlation_id=str(data["correlation_id"]),
            action_type=str(data["action_type"]),
            resource_id=data.get("resource_id"),
            state=ActionRunState(data["state"]),
            verdict=str(data["verdict"]),
            action_id=action_run_lineage.optional_bounded_text(
                data.get("action_id"),
                field_name="action_id",
            ),
            idempotency_key=str(data.get("idempotency_key") or data["correlation_id"]),
            params=deepcopy(dict(data.get("params") or {})),
            shadow_mode=bool(data.get("shadow_mode", False)),
            resolved_autonomy_ceiling=resolved_autonomy_ceiling,
            quorum_required=int(data.get("quorum_required", 1)),
            outcome=data.get("outcome"),
            initiator_principal=data.get("initiator_principal"),
            rollback_contract=str(data.get("rollback_contract", "state_forward_only")),
            rollback_ref=data.get("rollback_ref"),
            decision_case=action_run_lineage.bounded_decision_case(data.get("decision_case")),
            operational_context=operational_context,
            test_context_guard=(
                TestContextDispatchBinding.model_validate(data["test_context_guard"])
                if data.get("test_context_guard") is not None
                else None
            ),
            workflow_action=action_run_lineage.bounded_workflow_action(data.get("workflow_action")),
            kinetic_proposal=durable_kinetic_proposal(data.get("kinetic_proposal")),
            prospective_lineage=durable_prospective_lineage(data.get("prospective_lineage")),
            execution_audit_receipt=action_run_lineage.optional_bounded_text(
                data.get("execution_audit_receipt"),
                field_name="execution_audit_receipt",
            ),
            **durable_effect_verification(data),
            approval_expires_at=optional_datetime(
                data.get("approval_expires_at"),
                field_name="approval_expires_at",
            ),
            terminal_published=bool(data.get("terminal_published", False)),
            resource_claimed=bool(data.get("resource_claimed", False)),
        )
        run.history = [ActionRunState(state) for state in data.get("history", [])]
        require_bound_kinetic_proposal(run)
        return run


@runtime_checkable
class ActionRunStore(Protocol):
    """Durable persistence seam for in-flight ActionRuns."""

    async def save(self, run: ActionRun) -> None: ...

    async def load_active(self) -> list[ActionRun]: ...

    async def delete(self, correlation_id: str) -> None: ...

    async def claim_resource(
        self,
        run: ActionRun,
    ) -> Literal["acquired", "contended", "completed"]: ...

    async def release_resource(self, resource_id: str, correlation_id: str) -> bool: ...

    async def refresh_resource_claim(self, run: ActionRun) -> bool: ...

    async def validate_resource_claim(self, run: ActionRun) -> bool: ...


def kinetic_proposal(raw: object) -> KineticActionProposal | None:
    if raw is None:
        return None
    try:
        return KineticActionProposal.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None


def durable_kinetic_proposal(raw: object) -> dict[str, Any] | None:
    proposal = kinetic_proposal(raw)
    if raw is not None and proposal is None:
        raise ValueError("durable ActionRun kinetic proposal is invalid")
    return proposal.model_dump(mode="json") if proposal is not None else None


def prospective_lineage(raw: object) -> ProspectiveLineage | None:
    if raw is None:
        return None
    try:
        return ProspectiveLineage.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None


def durable_prospective_lineage(raw: object) -> dict[str, Any] | None:
    lineage = prospective_lineage(raw)
    if raw is not None and lineage is None:
        raise ValueError("durable ActionRun prospective lineage is invalid")
    return lineage.model_dump(mode="json") if lineage is not None else None


def require_bound_kinetic_proposal(run: ActionRun) -> None:
    if run.kinetic_proposal is None:
        if run.prospective_lineage is not None:
            raise ValueError("durable ActionRun prospective lineage requires a kinetic proposal")
        return
    proposal = kinetic_proposal(run.kinetic_proposal)
    if proposal is None or not kinetic_proposal_matches(
        proposal,
        correlation_id=run.correlation_id,
        action_type=run.action_type,
        resource_id=run.resource_id,
        params=run.params,
        decision_case=run.decision_case,
    ):
        raise ValueError("durable ActionRun kinetic proposal is not bound to its run")
    if run.prospective_lineage is not None:
        lineage = prospective_lineage(run.prospective_lineage)
        if (
            lineage is None
            or lineage.correlation_id != run.correlation_id
            or lineage.proposal_id != proposal.proposal_id
            or lineage.operational_plan_id != proposal.operational_plan_id
            or lineage.mutation_plan_digest != proposal.plan.digest
        ):
            raise ValueError("durable ActionRun prospective lineage is not bound to its run")


def kinetic_proposal_matches(
    proposal: KineticActionProposal,
    *,
    correlation_id: str,
    action_type: str,
    resource_id: object,
    params: Mapping[str, Any],
    decision_case: Mapping[str, Any] | None,
) -> bool:
    if (
        proposal.correlation_id != correlation_id
        or proposal.plan.action_type_ref.name != action_type
        or proposal.target_resource_ref != str(resource_id or "")
        or proposal.arguments() != dict(params)
        or decision_case is None
    ):
        return False
    operational_plan = decision_case.get("operational_plan")
    return bool(
        decision_case.get("correlation_id") == proposal.correlation_id
        and decision_case.get("process_id") == proposal.process_id
        and decision_case.get("selected_option_id") == proposal.selected_option_id
        and isinstance(operational_plan, Mapping)
        and operational_plan.get("complete") is True
        and operational_plan.get("plan_id") == proposal.operational_plan_id
    )


__all__ = [
    "ActionRun",
    "ActionRunStore",
    "kinetic_proposal",
    "kinetic_proposal_matches",
    "prospective_lineage",
]
