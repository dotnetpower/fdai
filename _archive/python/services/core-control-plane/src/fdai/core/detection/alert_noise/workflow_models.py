"""Immutable alert workflow bindings, results, and injected reader contracts.

These types depend on canonical contracts, never on the alert execution coordinator.
They retain no mutable workflow state and grant no authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Literal, Protocol

from fdai_service_contracts.alert_noise import AlertEvidence, Ref
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.executor_models import Digest, NonEmpty, SemVer
from fdai_service_contracts.ontology_query import content_digest
from pydantic import Field

from fdai.shared.contracts.models import Action, Event, Mode, Workflow
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessSnapshot, ProcessStatus

ALERT_WORKFLOWS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "ops.update-alert-routing": ("alert-routing-change", "update_routing"),
        "ops.set-alert-notification-window": (
            "alert-notification-window-change",
            "set_notification_window",
        ),
        "ops.tune-alert-evaluation": ("alert-evaluation-change", "tune_evaluation"),
    }
)
ALERT_WORKFLOW_PROMOTION_PURPOSE = "alert-noise-workflow-promotion"
PLAN_CONTEXT_KEY = "event.payload.alert_plan.plan_digest"
_PLAN_PARAMS = {"plan_digest": "${" + PLAN_CONTEXT_KEY + "}"}


class AlertRequesterReader(Protocol):
    """Resolve a current private subject from the composed opaque-reference mapping.

    Resolution establishes identity only. It cannot grant a role, approval or execution
    permission, and MUST NOT resolve a subject supplied in the proposal body.
    """

    async def resolve(self, *, requester_ref: str) -> str | None: ...


class WorkflowPromotionReader(Protocol):
    """Resolve independent admission for an existing, exact workflow release record."""

    async def read(
        self,
        *,
        workflow: Workflow,
        plan: AlertChangePlan,
        target_resource_id: str,
        now: datetime,
    ) -> DecisionEvidenceAdmission | None: ...


class AlertActionBinder(Protocol):
    """Bind an existing shadow Action before risk; absence MUST hold alert actions."""

    async def bind(self, action: Action, event: Event) -> Action: ...


class AlertWorkflowBinding(AlertContractBase):
    """Immutable private invocation inputs; the principal never enters the public result."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    process_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")]
    workflow_ref: NonEmpty
    workflow_version: SemVer
    workflow_digest: Digest
    plan_digest: Digest
    evidence_digest: Digest
    target_resource_id: Ref
    requester_ref: Ref
    requester_principal: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    correlation_id: NonEmpty
    trigger_ts: AlertTime
    mode: Mode
    source_revision: NonEmpty
    execution_authority: FalseOnly = False

    @property
    def context(self) -> Mapping[str, str]:
        """Reproduce exactly the three server-owned values accepted by this bridge."""
        return MappingProxyType(
            {
                "requester.principal": self.requester_principal,
                "workflow.requester_principal": self.requester_principal,
                PLAN_CONTEXT_KEY: self.plan_digest.removeprefix("sha256:"),
            }
        )

    def to_record(self) -> dict[str, object]:
        """Serialize full private context before invocation, including its content digest."""
        body = {"binding": self.model_dump(mode="json"), "context": dict(self.context)}
        return {**body, "record_digest": content_digest(body)}


@dataclass(frozen=True, slots=True)
class AlertWorkflowResult:
    """No-authority Process reference, not approval, publication or observed success."""

    process_id: str
    workflow_ref: str
    plan_digest: str
    status: ProcessStatus
    mode: Mode
    execution_authority: Literal[False] = field(default=False, init=False)
    approval_authority: Literal[False] = field(default=False, init=False)
    promotion_authority: Literal[False] = field(default=False, init=False)

    @property
    def process_ref(self) -> str:
        """Return the canonical Process reference for a scoped projection."""
        return "process:" + self.process_id


@dataclass(frozen=True, slots=True)
class AlertWorkflowResolution:
    """Exact retained inputs used internally for invocation and action-lineage checks."""

    binding: AlertWorkflowBinding
    plan: AlertChangePlan
    workflow: Workflow
    evidence: AlertEvidence
    snapshot: ProcessSnapshot
    events: tuple[ProcessEvent, ...]
