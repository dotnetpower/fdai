"""Alert-quality proposal, approval and effect records without implied authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from fdai_service_contracts.alert_noise import (
    AlertRule,
    Count,
    Evaluation,
    Positive,
    ProcessingRule,
    Ref,
)
from fdai_service_contracts.alert_noise_base import AlertContractBase as ContractBase
from fdai_service_contracts.alert_noise_base import AlertTime as AwareDatetime
from fdai_service_contracts.alert_noise_base import AlertDispatchRef, FalseOnly
from fdai_service_contracts.executor_models import Digest

ActionName = Literal[
    "ops.update-alert-routing",
    "ops.set-alert-notification-window",
    "ops.tune-alert-evaluation",
    "ops.restore-alert-configuration",
]


class AlertRollbackBaseline(ContractBase):
    """Exact pre-change configuration for the changed object, not its dependency."""

    rule: AlertRule
    processing_rule: ProcessingRule | None = None


class AlertTreatment(ContractBase):
    """Exactly one operator-selected treatment, never a provider path or script."""

    kind: Literal["routing", "suppression", "evaluation"]
    target_ref: Ref
    replacement_group_ref: Ref | None = None
    remove_group_ref: Ref | None = None
    processing_rule_ref: Ref | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    evaluation: Evaluation | None = None

    @model_validator(mode="after")
    def single_axis(self) -> Self:
        routing = self.replacement_group_ref is not None and self.remove_group_ref is not None
        scheduling = self.starts_at is not None and self.ends_at is not None
        any_routing = self.replacement_group_ref is not None or self.remove_group_ref is not None
        any_scheduling = self.starts_at is not None or self.ends_at is not None
        if self.kind == "routing":
            if not routing or any((self.processing_rule_ref, any_scheduling, self.evaluation)):
                raise ValueError("routing treatment MUST contain only two group references")
            if self.remove_group_ref == self.replacement_group_ref:
                raise ValueError("replacement group MUST differ from removed group")
        elif self.kind == "suppression":
            if not scheduling or not self.processing_rule_ref or any_routing or self.evaluation:
                raise ValueError("suppression MUST name a pre-provisioned rule and finite window")
            if self.starts_at is not None and self.ends_at is not None:
                if self.starts_at >= self.ends_at:
                    raise ValueError("suppression interval MUST be positive")
        elif self.evaluation is None or any(
            (any_routing, self.processing_rule_ref, any_scheduling)
        ):
            raise ValueError("evaluation treatment MUST contain only evaluation parameters")
        return self


class AlertChangePlan(ContractBase):
    """Immutable no-authority commitment, reconstructed before every admission."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    action_type: ActionName
    tenant_ref: Ref
    scope_ref: Ref
    requester_ref: Ref
    evidence_digest: Digest
    policy_digest: Digest
    target_revision: Digest
    treatment: AlertTreatment
    service_refs: Annotated[tuple[Ref, ...], Field(min_length=1, max_length=64)]
    lock_refs: Annotated[tuple[Ref, ...], Field(min_length=1, max_length=256)]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    max_execution_seconds: Positive
    max_observation_seconds: Positive
    max_recovery_seconds: Positive
    rollback_ref: Digest
    evaluation_receipt_digest: Digest | None = None
    execution_path: Literal["pr_manual"] = "pr_manual"
    default_mode: Literal["shadow"] = "shadow"
    quorum_required: Literal[2] = 2
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def bindings(self) -> Self:
        expected = {
            "routing": "ops.update-alert-routing",
            "suppression": "ops.set-alert-notification-window",
            "evaluation": "ops.tune-alert-evaluation",
        }[self.treatment.kind]
        if self.action_type != expected:
            raise ValueError("plan action MUST match its exact treatment")
        if self.expires_at <= self.created_at:
            raise ValueError("plan validity MUST be positive")
        if self.lock_refs != tuple(sorted(set(self.lock_refs))):
            raise ValueError("plan lock identities MUST be sorted and unique")
        if self.service_refs != tuple(sorted(set(self.service_refs))):
            raise ValueError("plan service identities MUST be sorted and unique")
        return self


class AlertApproval(ContractBase):
    """Verified Var-lane decision input; only an authenticated journal may supply it."""

    plan_digest: Digest
    principal_ref: Ref
    tenant_ref: Ref
    scope_ref: Ref
    decision: Literal["approved", "rejected"]
    lane: Literal["service_owner", "change_owner"]
    service_refs: Annotated[tuple[Ref, ...], Field(max_length=64)] = ()
    decided_at: AwareDatetime
    expires_at: AwareDatetime
    receipt_ref: Ref
    authority_revision: Digest

    @model_validator(mode="after")
    def decision_interval(self) -> Self:
        if self.expires_at <= self.decided_at or len(set(self.service_refs)) != len(
            self.service_refs
        ):
            raise ValueError("approval interval and service identities MUST be unambiguous")
        return self


class AlertDispatchEvidence(ContractBase):
    """Exact current admission observations supplied by trusted runtime ports."""

    plan_digest: Digest
    evidence_digest: Digest
    policy_digest: Digest
    target_revision: Digest
    evaluated_at: AwareDatetime
    valid_until: AwareDatetime
    authorization_until: AwareDatetime | None = None
    executor_ref: Ref
    dry_run_digest: Digest
    promotion_digest: Digest | None = None
    writer_fence_ref: Ref | None = None
    audit_intent_ref: Ref | None = None
    recovery_admission_ref: Ref | None = None
    dependencies_current: StrictBool = False
    actors_current: StrictBool = False
    observer_ready: StrictBool = False
    recovery_ready: StrictBool = False
    kill_switch: StrictBool = True
    mode: Literal["shadow", "enforce"] = "shadow"
    synthetic: StrictBool = False


class AlertEffectObservation(ContractBase):
    """Independent observation; a provider acceptance cannot produce success."""

    plan_digest: Digest
    dispatch_ref: AlertDispatchRef
    source_ref: Ref
    observer_ref: Ref
    executor_ref: Ref
    window_start: AwareDatetime
    window_end: AwareDatetime
    recorded_at: AwareDatetime
    coverage: Literal["complete", "partial", "unavailable"]
    configuration_matches: StrictBool = False
    collection_continues: StrictBool = False
    protected_paths_preserved: StrictBool = False
    response_deadlines_preserved: StrictBool = False
    expected_delivery_observed: StrictBool = False
    eligible_events: Count = 0
    failures: Count = 0
    missed_incidents: Count = 0
    synthetic: StrictBool = False
    receipt_ref: Ref
    recovery: StrictBool = False
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def time_and_identity(self) -> Self:
        if not self.window_start < self.window_end <= self.recorded_at:
            raise ValueError("effect observation window MUST be positive and complete")
        if len({self.source_ref, self.observer_ref, self.executor_ref}) != 3:
            raise ValueError("effect source, observer and executor MUST be distinct")
        return self
