"""Immutable provider-neutral alert-quality evidence; no authority or provider I/O."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StrictBool, model_validator

from fdai_service_contracts.alert_noise_base import AlertContractBase as ContractBase
from fdai_service_contracts.alert_noise_base import AlertTime as AwareDatetime
from fdai_service_contracts.alert_noise_base import FalseOnly
from fdai_service_contracts.executor_models import Digest

Ref = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]{0,159}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]
Positive = Annotated[int, Field(strict=True, ge=1, le=86_400)]
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Coverage = Literal["complete", "partial", "unavailable"]
AudienceKind = Literal["direct", "group", "role", "channel", "oncall"]
RuleKind = Literal["metric", "log", "activity", "processing", "unknown"]
Classification = Literal[
    "informational",
    "operational",
    "security",
    "compliance",
    "slo",
    "recovery",
    "service_health",
    "telemetry_loss",
    "approval",
    "unknown",
]


def digest_record(record: BaseModel) -> str:
    """Content-address a validated immutable record, including its exact field order."""
    return "sha256:" + hashlib.sha256(record.model_dump_json().encode()).hexdigest()


class EvidenceStamp(ContractBase):
    """Source-bound time, completeness and privacy-safe provenance."""

    source: Ref
    tenant_ref: Ref
    scope_ref: Ref
    revision: Digest
    observed_at: AwareDatetime
    recorded_at: AwareDatetime
    valid_until: AwareDatetime
    coverage: Coverage
    synthetic: StrictBool = False
    reasons: Annotated[tuple[Ref, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if not self.observed_at <= self.recorded_at < self.valid_until:
            raise ValueError("evidence times MUST be ordered inside a positive validity window")
        if self.coverage != "complete" and not self.reasons:
            raise ValueError("incomplete evidence MUST explain its unavailable reasons")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("evidence reasons MUST be unique")
        return self

    def current_at(self, now: datetime) -> bool:
        """Return current eligibility without turning completeness into authority."""
        return self.recorded_at <= now < self.valid_until


class Audience(ContractBase):
    """A destination and verified scoped identity expansion, never an email address."""

    ref: Ref
    kind: AudienceKind
    member_refs: Annotated[tuple[Ref, ...], Field(max_length=2000)] = ()
    potential_members: Count | None = None
    coverage: Coverage
    revision: Digest
    primary_verified: StrictBool = False
    backup_verified: StrictBool = False

    @model_validator(mode="after")
    def membership(self) -> Self:
        if len(set(self.member_refs)) != len(self.member_refs):
            raise ValueError("audience identities MUST be unique")
        if self.coverage == "complete" and self.potential_members != len(self.member_refs):
            raise ValueError("complete audience count MUST match verified members")
        if self.potential_members is not None and self.potential_members < len(self.member_refs):
            raise ValueError("audience upper bound MUST cover verified members")
        return self


class AlertGroup(ContractBase):
    """Observed group with all reverse dependencies and non-notification effects."""

    ref: Ref
    revision: Digest
    audience_refs: Annotated[tuple[Ref, ...], Field(max_length=128)]
    rule_refs: Annotated[tuple[Ref, ...], Field(max_length=2000)]
    automation_refs: Annotated[tuple[Ref, ...], Field(max_length=128)] = ()
    reverse_complete: StrictBool = False

    @model_validator(mode="after")
    def unique_edges(self) -> Self:
        for refs in (self.audience_refs, self.rule_refs, self.automation_refs):
            if len(set(refs)) != len(refs):
                raise ValueError("group relationships MUST be unique")
        return self


class Evaluation(ContractBase):
    """Supported threshold semantics; complex native criteria remain unsupported."""

    metric_ref: Ref
    operator: Literal["above", "below"]
    threshold: Finite
    window_seconds: Positive
    frequency_seconds: Positive
    aggregation: Literal["average", "maximum", "minimum"]


class AlertRule(ContractBase):
    """Exact observed configuration linked to service and policy, not caller labels."""

    ref: Ref
    resource_ref: Ref
    service_ref: Ref
    revision: Digest
    kind: RuleKind
    severity: Annotated[int, Field(strict=True, ge=0, le=4)] | None = None
    classification: Classification = "unknown"
    group_refs: Annotated[tuple[Ref, ...], Field(max_length=5)] = ()
    enabled: StrictBool = True
    stateful: StrictBool = True
    evaluation: Evaluation | None = None
    active_incident: StrictBool = False
    iac_owned: StrictBool = False
    ownership_verified: StrictBool = False

    @model_validator(mode="after")
    def unique_groups(self) -> Self:
        if len(set(self.group_refs)) != len(self.group_refs):
            raise ValueError("rule group bindings MUST be unique")
        return self

    @property
    def protected(self) -> bool:
        """Unknown and critical rules are protected regardless of volume."""
        return (
            self.severity is None
            or self.severity <= 1
            or self.classification not in {"informational", "operational"}
        )


class ProcessingRule(ContractBase):
    """Exact finite effective-rule projection; unknown filters fail closed."""

    ref: Ref
    revision: Digest
    rule_refs: Annotated[tuple[Ref, ...], Field(max_length=2000)]
    action: Literal["suppress", "add"]
    group_refs: Annotated[tuple[Ref, ...], Field(max_length=5)] = ()
    enabled: StrictBool
    effective_from: AwareDatetime
    effective_to: AwareDatetime
    semantics_complete: StrictBool = False

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.effective_to <= self.effective_from:
            raise ValueError("processing window MUST be positive and finite")
        if self.action == "suppress" and self.group_refs:
            raise ValueError("suppression removes all groups, not selected groups")
        if len(set(self.rule_refs)) != len(self.rule_refs) or len(set(self.group_refs)) != len(
            self.group_refs
        ):
            raise ValueError("processing relationships MUST be unique")
        return self


class AlertDelivery(ContractBase):
    """One source event/destination observation; unknown delivery is never zero."""

    ref: Ref
    episode_ref: Ref
    rule_ref: Ref
    rule_revision: Digest | None = None
    audience_ref: Ref | None = None
    attempt_ref: Ref | None = None
    acknowledger_ref: Ref | None = None
    condition: Literal["fired", "resolved"]
    state: Literal["source", "attempted", "accepted", "delivered", "acknowledged", "failed"]
    event_at: AwareDatetime
    receipt_ref: Ref

    @model_validator(mode="after")
    def observation_identity(self) -> Self:
        if self.state == "source" and any(
            (self.audience_ref, self.attempt_ref, self.acknowledger_ref)
        ):
            raise ValueError("source observations MUST NOT assert notification identity")
        if self.state != "source" and self.audience_ref is None:
            raise ValueError("notification observations require a destination")
        if self.acknowledger_ref is not None and self.state != "acknowledged":
            raise ValueError("human acknowledgement belongs only on acknowledgement observations")
        return self


class AlertEvidence(ContractBase):
    """Bounded frozen evidence with explicit independent-collection availability."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    stamp: EvidenceStamp
    window_start: AwareDatetime
    window_end: AwareDatetime
    rules: Annotated[tuple[AlertRule, ...], Field(max_length=2000)] = ()
    groups: Annotated[tuple[AlertGroup, ...], Field(max_length=1000)] = ()
    audiences: Annotated[tuple[Audience, ...], Field(max_length=2000)] = ()
    processing_rules: Annotated[tuple[ProcessingRule, ...], Field(max_length=1000)] = ()
    deliveries: Annotated[tuple[AlertDelivery, ...], Field(max_length=10000)] = ()
    delivery_coverage: Coverage = "unavailable"
    history_coverage: Coverage = "unavailable"
    independent_collection: StrictBool = False
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def consistency(self) -> Self:
        if not self.window_start < self.window_end <= self.stamp.observed_at:
            raise ValueError("observation window MUST precede the evidence cutoff")
        if (self.window_end - self.window_start).total_seconds() > 31 * 86400:
            raise ValueError("alert observation window exceeds 31 days")
        for rows in (
            self.rules,
            self.groups,
            self.audiences,
            self.processing_rules,
            self.deliveries,
        ):
            if len({row.ref for row in rows}) != len(rows):
                raise ValueError("evidence identities MUST be unique within each family")
        rules = {rule.ref: rule for rule in self.rules}
        audiences = {audience.ref for audience in self.audiences}
        for delivery in self.deliveries:
            if delivery.rule_ref not in rules:
                raise ValueError("delivery MUST reference an observed rule")
            if not self.window_start <= delivery.event_at < self.window_end:
                raise ValueError("delivery event MUST be within the observation window")
            if delivery.audience_ref is not None and delivery.audience_ref not in audiences:
                raise ValueError("delivery destination MUST reference an observed audience")
        return self


class NoisePolicy(ContractBase):
    """Versioned finite analysis limits; cannot lower protected traffic constraints."""

    version: Ref = "alert-noise-v1"
    burst_threshold: Annotated[int, Field(strict=True, ge=2, le=10000)] = 50
    flapping_threshold: Annotated[int, Field(strict=True, ge=2, le=1000)] = 6
    max_candidates: Annotated[int, Field(strict=True, ge=1, le=32)] = 32
    min_cohort_size: Annotated[int, Field(strict=True, ge=2, le=100)] = 5
    max_suppression_seconds: Positive = 3600
    propagation_seconds: Annotated[int, Field(strict=True, ge=1800, le=86400)] = 1800


class NoiseFinding(ContractBase):
    """A bounded explanation keyed to evidence, never a mutation instruction."""

    rule_ref: Ref
    service_ref: Ref
    reason: Literal[
        "storm", "flapping", "overlap", "broad_role", "unowned", "protected", "incomplete"
    ]
    guidance: Literal[
        "review-routing",
        "review-evaluation",
        "review-ownership",
        "retain-protected",
        "collect-evidence",
    ]
    source_episodes: Count | None
    observed_deliveries: Count | None
    potential_recipients_lower: Count | None = None
    potential_recipients_upper: Count | None = None
    duplicate_paths: Count = 0
    protected: StrictBool


class NoiseAssessment(ContractBase):
    """Privacy-minimized report binding counts and findings to a frozen input."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source: Literal["alert-noise-evidence"] = "alert-noise-evidence"
    evidence_digest: Digest
    policy_digest: Digest
    tenant_ref: Ref
    scope_ref: Ref
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    coverage: Coverage
    reasons: Annotated[tuple[Ref, ...], Field(max_length=32)]
    source_episodes: Count | None
    notification_attempts: Count | None
    confirmed_deliveries: Count | None
    acknowledgements: Count | None
    findings: Annotated[tuple[NoiseFinding, ...], Field(max_length=10000)]
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def observation_window(self) -> Self:
        if self.valid_until <= self.observed_at:
            raise ValueError("assessment validity MUST be positive")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("assessment observation bounds MUST be supplied together")
        if self.window_start is not None and self.window_end is not None:
            if not self.window_start < self.window_end <= self.observed_at:
                raise ValueError("assessment observation window MUST precede cutoff")
        return self
