"""Retained alert effect contracts and exact lookup identities, without Process writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import (
    ALERT_DISPATCH_REF_PATTERN,
    AlertContractBase,
    AlertDispatchRef,
    AlertTime,
    FalseOnly,
)
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.executor_models import Digest, NonEmpty
from fdai_service_contracts.ontology_query import content_digest
from pydantic import Field, model_validator

from fdai.core.detection.alert_noise.execution_models import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    alert_execution_key,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.shared.contracts.models import Action, Mode, Operation, RollbackKind
from fdai.shared.providers.process_runtime import ProcessEvent
from fdai.shared.providers.remediation_pr import PublishReceipt

ALERT_EFFECT_PURPOSE: Literal["alert-noise-effect"] = "alert-noise-effect"
ALERT_RECOVERY_EFFECT_PURPOSE: Literal["alert-noise-recovery-effect"] = (
    "alert-noise-recovery-effect"
)
AlertEffectPurpose = Literal["alert-noise-effect", "alert-noise-recovery-effect"]
AlertEffectOutcome = Literal[
    "held", "recovery_required", "recovery_incomplete", "unscorable", "verified", "recovered"
]
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_DISPATCH_REF = re.compile(ALERT_DISPATCH_REF_PATTERN)


def alert_executed_action_key(action_digest: str) -> str:
    """Address the original executor-owned record by the full Action, never its fingerprint."""
    if type(action_digest) is not str or _DIGEST.fullmatch(action_digest) is None:
        raise AlertExecutionHeld("alert_effect_action_digest_invalid")
    return "alert-noise:executed-action:" + action_digest


def alert_effect_key(*, plan_digest: str, dispatch_ref: str) -> str:
    """Bound an exact plan/dispatch lookup without truncating either identity."""
    if (
        type(plan_digest) is not str
        or _DIGEST.fullmatch(plan_digest) is None
        or type(dispatch_ref) is not str
        or _DISPATCH_REF.fullmatch(dispatch_ref) is None
    ):
        raise AlertExecutionHeld("alert_effect_lookup_invalid")
    return "alert-noise:effect:" + content_digest(
        {
            "plan_digest": plan_digest,
            "dispatch_ref": dispatch_ref,
        }
    )


class AlertExecutionNotice(AlertContractBase):
    """Reference-only projection of an authenticated Thor terminal ActionRun publication.

    The parent retains these exact fields before publishing. The handler consumes only
    these fields from the authenticated bus envelope, never Action or observation contents.
    """

    producer_principal: Literal["Thor"]
    action_id: UUID
    action_digest: Digest
    correlation_id: NonEmpty
    state: Literal["succeeded", "rolled_back", "rollback_failed", "effect_observing"]
    terminal_at: AlertTime


class AlertExecutedActionRecord(AlertContractBase):
    """Private parent-written Action, plan, actual publication receipt and original notice.

    ``dispatch_generation`` comes from the real safeguard coordinator evidence identity.
    Retain the first publication, including its original already_existed value and notice;
    a delivery replay must not replace it. This module supplies no producer or writer.
    """

    action: Action
    plan: AlertChangePlan
    publication_receipt: PublishReceipt
    execution_outcome: Literal["published", "already_existed"]
    dispatch_generation: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
    source_event: AlertExecutionNotice

    @model_validator(mode="after")
    def exact_binding(self) -> Self:
        """Reject a changed Action, invented restore plan, or publication/notice mismatch."""
        action, plan, notice = self.action, self.plan, self.source_event
        digest = digest_record(plan)
        target = plan.treatment.processing_rule_ref or plan.treatment.target_ref
        receipt = self.publication_receipt
        expected_outcome = "already_existed" if receipt.already_existed else "published"
        if (
            full_action_digest(action) != notice.action_digest
            or action.action_id != notice.action_id
            or action.params != {"plan_digest": digest[7:]}
            or action.action_type not in {plan.action_type, RESTORE_ACTION}
            or action.mode is not Mode.ENFORCE
            or action.operation is not Operation.UPDATE
            or action.rollback_ref.kind is not RollbackKind.PR_REVERT
            or action.rollback_ref.reference != plan.rollback_ref
            or action.target_resource_ref != target
            or target not in plan.lock_refs
            or action.idempotency_key != alert_execution_key(action.action_type, digest)
            or action.workflow_action is None
            or not action.executor_identity_ref
            or not action.created_at <= notice.terminal_at
            or type(receipt.already_existed) is not bool
            or receipt.state not in {"open", "closed", "merged"}
            or not 1 <= len(receipt.pr_ref) <= 512
            or receipt.pr_ref != receipt.pr_ref.strip()
            or self.execution_outcome != expected_outcome
        ):
            raise ValueError("alert executed record MUST bind the exact Action and publication")
        alert_effect_key(plan_digest=digest, dispatch_ref=action.workflow_action.proposal_ref)
        return self

    @property
    def dispatch_ref(self) -> str:
        """Use the original canonical workflow proposal reference as dispatch identity."""
        lineage = self.action.workflow_action
        if lineage is None:
            raise AlertExecutionHeld("alert_effect_workflow_missing")
        return lineage.proposal_ref


@dataclass(frozen=True, slots=True)
class AlertEffectContext:
    """Trusted readback inputs; dispatch time is from the safeguard store, not the event."""

    execution: AlertExecutedActionRecord
    dispatched_at: datetime
    safeguard_bundle_digest: str
    purpose: AlertEffectPurpose
    process_events: tuple[ProcessEvent, ...]


class AlertEffectDrift(AlertContractBase):
    """Reference-only Heimdall Drift; Forseti must re-read it, never trust a completion claim."""

    kind: Literal["alert_noise_effect"] = "alert_noise_effect"
    effect_schema_version: Literal["1.0.0"] = "1.0.0"
    producer_principal: Literal["Heimdall"] = "Heimdall"
    correlation_id: NonEmpty
    idempotency_key: NonEmpty
    resource_id: Ref
    process_id: NonEmpty
    step_id: NonEmpty
    action_digest: Digest
    plan_digest: Digest
    dispatch_ref: AlertDispatchRef
    outcome_ref: NonEmpty
    effect_outcome: AlertEffectOutcome
    workflow_outcome_ref: NonEmpty | None
    recorded_at: AlertTime
    execution_authority: FalseOnly = False
    promotion_authority: FalseOnly = False
    process_completed: FalseOnly = False
