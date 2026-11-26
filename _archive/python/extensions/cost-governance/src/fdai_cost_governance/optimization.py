"""Deterministic resource optimization planning over reviewed service profiles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from fdai_cost_governance.guard import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsGuard,
    FinOpsGuardOutcome,
    ResourceContext,
)


class OptimizationDisposition(StrEnum):
    """Authority-neutral result of one resource optimization assessment."""

    CANDIDATE = "candidate"
    KEEP = "keep"
    REVIEW_REQUIRED = "review_required"


class ClarificationResponseShape(StrEnum):
    BOOLEAN = "boolean"
    CHOICE = "choice"
    TEXT = "text"


class ClarificationDisposition(StrEnum):
    ACCEPTED = "accepted"
    HELD = "held"


def _require_ratio(name: str, value: Decimal) -> None:
    if not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{name} MUST be a finite ratio between 0 and 1")


@dataclass(frozen=True, slots=True)
class ServiceFamilyProfile:
    """Reviewed evidence requirements for one provider-neutral resource family."""

    profile_id: str
    version: str
    resource_types: frozenset[str]
    minimum_samples: int
    maximum_evidence_age: timedelta
    maximum_utilization_p95: Decimal
    minimum_headroom: Decimal
    minimum_capacity: int = 1
    required_metrics: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip() or not self.resource_types:
            raise ValueError("service family profile identity MUST be non-empty")
        if any(not resource_type.strip() for resource_type in self.resource_types):
            raise ValueError("service family profile resource types MUST be non-empty")
        if any(not metric.strip() or metric != metric.strip() for metric in self.required_metrics):
            raise ValueError("service family profile metrics MUST be exact non-empty text")
        if self.minimum_samples < 1 or self.maximum_evidence_age <= timedelta(0):
            raise ValueError("service family profile evidence bounds MUST be positive")
        _require_ratio("maximum_utilization_p95", self.maximum_utilization_p95)
        _require_ratio("minimum_headroom", self.minimum_headroom)
        if self.minimum_capacity < 1:
            raise ValueError("service family profile minimum_capacity MUST be positive")

    @property
    def digest(self) -> str:
        payload = json.dumps(
            {
                "maximum_evidence_age_seconds": int(self.maximum_evidence_age.total_seconds()),
                "maximum_utilization_p95": str(self.maximum_utilization_p95),
                "minimum_capacity": self.minimum_capacity,
                "minimum_headroom": str(self.minimum_headroom),
                "minimum_samples": self.minimum_samples,
                "profile_id": self.profile_id,
                "required_metrics": sorted(self.required_metrics),
                "resource_types": sorted(self.resource_types),
                "version": self.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ResourceOptimizationEvidence:
    """One source-qualified sizing or cleanup recommendation input."""

    resource: ResourceContext
    resource_type: str
    observed_at: datetime
    source_authority: str
    completeness: Decimal
    sample_count: int
    utilization_p95: Decimal
    headroom: Decimal
    proposed_kind: FinOpsActionKind
    proposed_capacity: int | None = None
    metrics: tuple[tuple[str, Decimal], ...] = ()
    incompatibilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("optimization evidence time MUST be timezone-aware")
        if (
            not self.resource.resource_id.strip()
            or not self.resource_type.strip()
            or not self.source_authority.strip()
        ):
            raise ValueError("optimization evidence identity MUST be non-empty")
        if self.sample_count < 0 or self.resource.current_capacity < 0:
            raise ValueError("optimization evidence counts and capacity MUST be non-negative")
        if self.proposed_capacity is not None and self.proposed_capacity < 0:
            raise ValueError("optimization evidence proposed_capacity MUST be non-negative")
        metric_names = tuple(name for name, _value in self.metrics)
        if metric_names != tuple(sorted(metric_names)) or len(metric_names) != len(
            set(metric_names)
        ):
            raise ValueError("optimization evidence metrics MUST be unique and sorted")
        for name, value in self.metrics:
            if not name.strip() or name != name.strip() or not value.is_finite():
                raise ValueError("optimization evidence metrics MUST be exact and finite")
        if any(not reason.strip() or reason != reason.strip() for reason in self.incompatibilities):
            raise ValueError("optimization evidence incompatibilities MUST be exact")
        _require_ratio("completeness", self.completeness)
        _require_ratio("utilization_p95", self.utilization_p95)
        _require_ratio("headroom", self.headroom)


@dataclass(frozen=True, slots=True)
class ResourceOptimizationPlan:
    """One bounded result that grants no approval or execution authority."""

    disposition: OptimizationDisposition
    resource_id: str
    profile_id: str | None
    profile_version: str | None
    profile_digest: str | None
    candidate: FinOpsCandidate | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoupledResourceOptimizationEvidence:
    """One complete, bounded target set that must change and recover atomically."""

    target_set_id: str
    target_revision_digest: str
    resources: tuple[ResourceOptimizationEvidence, ...]
    causal_order: tuple[str, ...]
    membership_complete: bool
    truncated: bool
    rollback_tested: bool
    logical_target_lock: str
    idempotency_key: str
    subscription_scoped: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.target_set_id,
            self.target_revision_digest,
            self.logical_target_lock,
            self.idempotency_key,
        ):
            if not value.strip() or value != value.strip():
                raise ValueError("coupled optimization identity MUST be exact")
        _require_sha256("coupled target revision", self.target_revision_digest)
        if not 1 < len(self.resources) <= 20:
            raise ValueError("coupled optimization MUST contain between 2 and 20 resources")
        resource_ids = tuple(item.resource.resource_id for item in self.resources)
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("coupled optimization resources MUST be unique")
        if set(self.causal_order) != set(resource_ids):
            raise ValueError("coupled optimization causal order MUST cover each resource once")
        if len(self.causal_order) != len(set(self.causal_order)):
            raise ValueError("coupled optimization causal order MUST be unique")


@dataclass(frozen=True, slots=True)
class CoupledResourceOptimizationPlan:
    """Authority-neutral all-or-nothing optimization result for one target set."""

    disposition: OptimizationDisposition
    target_set_id: str
    target_revision_digest: str
    candidates: tuple[FinOpsCandidate, ...]
    profile_digests: tuple[str, ...]
    causal_order: tuple[str, ...]
    logical_target_lock: str
    idempotency_key: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OptimizationClarificationRequest:
    """One narrow, expiring question after bounded evidence recovery failed."""

    request_id: str
    target_id: str
    target_revision_digest: str
    missing_fact: str
    blocking_reason: str
    eligible_roles: tuple[str, ...]
    response_shape: ClarificationResponseShape
    allowed_values: tuple[str, ...]
    effective_scope: str
    created_at: datetime
    expires_at: datetime
    reevaluation_key: str
    recovery_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        text_values = (
            self.request_id,
            self.target_id,
            self.target_revision_digest,
            self.missing_fact,
            self.blocking_reason,
            self.effective_scope,
            self.reevaluation_key,
        )
        if any(not value.strip() or value != value.strip() for value in text_values):
            raise ValueError("optimization clarification identity MUST be exact")
        _require_sha256("optimization clarification target revision", self.target_revision_digest)
        for timestamp in (self.created_at, self.expires_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("optimization clarification time MUST be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("optimization clarification expiry MUST follow creation")
        for values in (self.eligible_roles, self.recovery_evidence_refs):
            if not values or any(not value.strip() or value != value.strip() for value in values):
                raise ValueError("optimization clarification bounds MUST be non-empty and exact")
            if len(values) != len(set(values)):
                raise ValueError("optimization clarification bounds MUST be unique")
        if any(not value.strip() or value != value.strip() for value in self.allowed_values):
            raise ValueError("optimization clarification allowed values MUST be exact")
        if len(self.allowed_values) != len(set(self.allowed_values)):
            raise ValueError("optimization clarification allowed values MUST be unique")
        if self.response_shape is ClarificationResponseShape.CHOICE:
            if not self.allowed_values:
                raise ValueError("choice clarification MUST declare allowed values")
        elif self.allowed_values:
            raise ValueError("non-choice clarification MUST NOT declare allowed values")


@dataclass(frozen=True, slots=True)
class OptimizationClarificationAttestation:
    request_id: str
    actor_id: str
    actor_role: str
    response: str
    effective_scope: str
    recorded_at: datetime
    effective_until: datetime

    def __post_init__(self) -> None:
        for value in (
            self.request_id,
            self.actor_id,
            self.actor_role,
            self.response,
            self.effective_scope,
        ):
            if not value.strip() or value != value.strip():
                raise ValueError("optimization attestation fields MUST be exact")
        if len(self.response) > 512:
            raise ValueError("optimization attestation response is too long")
        for timestamp in (self.recorded_at, self.effective_until):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("optimization attestation time MUST be timezone-aware")
        if self.effective_until < self.recorded_at:
            raise ValueError("optimization attestation interval is invalid")


@dataclass(frozen=True, slots=True)
class OptimizationClarificationResult:
    disposition: ClarificationDisposition
    request_id: str
    reevaluation_key: str | None
    accepted_value: str | None
    reason: str


def build_optimization_clarification(
    *,
    target_id: str,
    target_revision_digest: str,
    missing_fact: str,
    blocking_reason: str,
    eligible_roles: tuple[str, ...],
    response_shape: ClarificationResponseShape,
    allowed_values: tuple[str, ...] = (),
    effective_scope: str,
    created_at: datetime,
    expires_at: datetime,
    reevaluation_key: str,
    recovery_evidence_refs: tuple[str, ...],
) -> OptimizationClarificationRequest:
    """Build one content-addressed question only after recovery evidence exists."""

    payload = json.dumps(
        {
            "allowed_values": allowed_values,
            "blocking_reason": blocking_reason,
            "effective_scope": effective_scope,
            "eligible_roles": eligible_roles,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "missing_fact": missing_fact,
            "recovery_evidence_refs": recovery_evidence_refs,
            "reevaluation_key": reevaluation_key,
            "response_shape": response_shape.value,
            "target_id": target_id,
            "target_revision_digest": target_revision_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request_id = "optimization-clarification:" + hashlib.sha256(payload).hexdigest()
    return OptimizationClarificationRequest(
        request_id=request_id,
        target_id=target_id,
        target_revision_digest=target_revision_digest,
        missing_fact=missing_fact,
        blocking_reason=blocking_reason,
        eligible_roles=eligible_roles,
        response_shape=response_shape,
        allowed_values=allowed_values,
        effective_scope=effective_scope,
        created_at=created_at,
        expires_at=expires_at,
        reevaluation_key=reevaluation_key,
        recovery_evidence_refs=recovery_evidence_refs,
    )


def evaluate_optimization_attestation(
    request: OptimizationClarificationRequest,
    attestation: OptimizationClarificationAttestation,
    *,
    now: datetime,
    authoritative_conflict: bool = False,
) -> OptimizationClarificationResult:
    """Accept one scoped fact or hold without converting it into action authority."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("optimization clarification evaluation time MUST be timezone-aware")
    reason = _attestation_hold_reason(
        request,
        attestation,
        now=now,
        authoritative_conflict=authoritative_conflict,
    )
    if reason is not None:
        return OptimizationClarificationResult(
            disposition=ClarificationDisposition.HELD,
            request_id=request.request_id,
            reevaluation_key=None,
            accepted_value=None,
            reason=reason,
        )
    return OptimizationClarificationResult(
        disposition=ClarificationDisposition.ACCEPTED,
        request_id=request.request_id,
        reevaluation_key=request.reevaluation_key,
        accepted_value=attestation.response,
        reason="attestation_accepted_for_reevaluation",
    )


def _attestation_hold_reason(
    request: OptimizationClarificationRequest,
    attestation: OptimizationClarificationAttestation,
    *,
    now: datetime,
    authoritative_conflict: bool,
) -> str | None:
    if request.request_id != attestation.request_id:
        return "request_identity_mismatch"
    if now > request.expires_at or now > attestation.effective_until:
        return "attestation_expired"
    if (
        attestation.recorded_at < request.created_at
        or attestation.recorded_at > request.expires_at
        or attestation.recorded_at > now
        or attestation.effective_until > request.expires_at
    ):
        return "attestation_time_invalid"
    if attestation.actor_role not in request.eligible_roles:
        return "respondent_role_ineligible"
    if attestation.effective_scope != request.effective_scope:
        return "attestation_scope_mismatch"
    if authoritative_conflict:
        return "authoritative_evidence_conflict"
    if (
        request.response_shape is ClarificationResponseShape.BOOLEAN
        and attestation.response
        not in {
            "true",
            "false",
        }
    ):
        return "attestation_response_invalid"
    if (
        request.response_shape is ClarificationResponseShape.CHOICE
        and attestation.response not in request.allowed_values
    ):
        return "attestation_response_invalid"
    return None


def _require_sha256(label: str, value: str) -> None:
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{label} MUST be an exact SHA-256 digest")


def default_service_family_profiles() -> tuple[ServiceFamilyProfile, ...]:
    """Return reviewed provider-neutral profile assets for the first five families."""

    def profile(
        profile_id: str,
        resource_types: frozenset[str],
        required_metrics: frozenset[str],
    ) -> ServiceFamilyProfile:
        return ServiceFamilyProfile(
            profile_id=profile_id,
            version="1.0.0",
            resource_types=resource_types,
            minimum_samples=168,
            maximum_evidence_age=timedelta(hours=2),
            maximum_utilization_p95=Decimal("0.4"),
            minimum_headroom=Decimal("0.3"),
            required_metrics=required_metrics,
        )

    return (
        profile(
            "compute-vm-conservative",
            frozenset({"virtual-machine", "virtual-machine-scale-set"}),
            frozenset({"cpu", "memory", "network", "disk-throughput", "disk-iops", "burst-credit"}),
        ),
        profile(
            "database-conservative",
            frozenset({"azure-sql", "postgresql"}),
            frozenset(
                {
                    "cpu",
                    "memory",
                    "data-io",
                    "log-io",
                    "connections",
                    "storage-growth",
                    "throttling",
                    "ha",
                    "zone",
                    "backup",
                }
            ),
        ),
        profile(
            "aks-node-pool-conservative",
            frozenset({"aks-node-pool"}),
            frozenset(
                {
                    "requested-cpu",
                    "used-cpu",
                    "requested-memory",
                    "used-memory",
                    "pending-pods",
                    "node-pressure",
                    "disruption-budget",
                    "topology",
                    "autoscale-bounds",
                }
            ),
        ),
        profile(
            "application-host-conservative",
            frozenset({"app-service", "container-app"}),
            frozenset(
                {
                    "request-concurrency",
                    "replica-utilization",
                    "latency",
                    "error-rate",
                    "cold-starts",
                    "scale-events",
                    "minimum-replicas",
                }
            ),
        ),
        profile(
            "storage-conservative",
            frozenset({"storage-account"}),
            frozenset(
                {
                    "capacity",
                    "transaction-mix",
                    "access-frequency",
                    "redundancy",
                    "retrieval",
                    "replication",
                    "egress",
                }
            ),
        ),
    )


class ResourceOptimizationPlanner:
    """Admit provider advice only through an exact reviewed service profile."""

    def __init__(
        self,
        *,
        profiles: Iterable[ServiceFamilyProfile],
        guard: FinOpsGuard | None = None,
    ) -> None:
        self._profiles: dict[str, ServiceFamilyProfile] = {}
        for profile in profiles:
            for resource_type in profile.resource_types:
                if resource_type in self._profiles:
                    raise ValueError("resource type MUST map to exactly one service family profile")
                self._profiles[resource_type] = profile
        if not self._profiles:
            raise ValueError("at least one service family profile is required")
        self._guard = guard or FinOpsGuard()

    def plan(
        self,
        evidence: ResourceOptimizationEvidence,
        *,
        now: datetime,
    ) -> ResourceOptimizationPlan:
        if now.tzinfo is None:
            raise ValueError("optimization planning time MUST be timezone-aware")
        profile = self._profiles.get(evidence.resource_type)
        if profile is None:
            return self._review(evidence, None, "service_family_profile_unavailable")
        if evidence.completeness != Decimal("1"):
            return self._review(evidence, profile, "evidence_incomplete")
        age = now - evidence.observed_at
        if age < timedelta(0):
            return self._review(evidence, profile, "evidence_from_future")
        if age > profile.maximum_evidence_age:
            return self._review(evidence, profile, "evidence_stale")
        if evidence.sample_count < profile.minimum_samples:
            return self._review(evidence, profile, "sample_count_insufficient")
        metric_names = {name for name, _value in evidence.metrics}
        missing_metrics = sorted(profile.required_metrics - metric_names)
        if missing_metrics:
            return self._review(
                evidence,
                profile,
                "required_metrics_missing:" + ",".join(missing_metrics),
            )
        if evidence.incompatibilities:
            return self._review(evidence, profile, *evidence.incompatibilities)
        if evidence.utilization_p95 > profile.maximum_utilization_p95:
            return self._keep(evidence, profile, "utilization_requires_current_capacity")
        if evidence.headroom < profile.minimum_headroom:
            return self._keep(evidence, profile, "headroom_below_profile_floor")

        target_capacity = evidence.proposed_capacity
        if evidence.proposed_kind is FinOpsActionKind.RIGHT_SIZE:
            if target_capacity is None:
                return self._review(evidence, profile, "target_capacity_required")
            if target_capacity >= evidence.resource.current_capacity:
                return self._keep(evidence, profile, "no_capacity_reduction")
            if target_capacity < profile.minimum_capacity:
                return self._review(evidence, profile, "target_below_profile_floor")
        elif evidence.proposed_kind is FinOpsActionKind.SHUTDOWN:
            if evidence.utilization_p95 != Decimal("0"):
                return self._review(evidence, profile, "shutdown_requires_zero_utilization")
            target_capacity = None
        else:
            return self._review(evidence, profile, "unsupported_optimization_kind")

        candidate = FinOpsCandidate(
            action_id=f"optimization:{profile.profile_id}:{evidence.resource.resource_id}",
            kind=evidence.proposed_kind,
            resource=evidence.resource,
            target_capacity=target_capacity,
        )
        guard_decision = self._guard.evaluate(candidate)
        if guard_decision.outcome is FinOpsGuardOutcome.REJECTED:
            return self._review(evidence, profile, *guard_decision.reasons)
        return ResourceOptimizationPlan(
            disposition=OptimizationDisposition.CANDIDATE,
            resource_id=evidence.resource.resource_id,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            profile_digest=profile.digest,
            candidate=candidate,
            reasons=(),
        )

    def plan_coupled(
        self,
        evidence: CoupledResourceOptimizationEvidence,
        *,
        now: datetime,
    ) -> CoupledResourceOptimizationPlan:
        """Plan one bounded target set only when every member is action-eligible."""

        reasons: list[str] = []
        if not evidence.membership_complete:
            reasons.append("target_membership_incomplete")
        if evidence.truncated:
            reasons.append("target_membership_truncated")
        if evidence.subscription_scoped:
            reasons.append("subscription_scope_not_actionable")
        if not evidence.rollback_tested:
            reasons.append("coupled_rollback_untested")
        if reasons:
            return self._coupled_result(evidence, (), (), tuple(reasons))

        plans = tuple(self.plan(item, now=now) for item in evidence.resources)
        review_reasons = tuple(
            f"{plan.resource_id}:{reason}"
            for plan in plans
            if plan.disposition is OptimizationDisposition.REVIEW_REQUIRED
            for reason in plan.reasons
        )
        if review_reasons:
            return self._coupled_result(evidence, (), (), review_reasons)
        if any(plan.disposition is OptimizationDisposition.KEEP for plan in plans):
            if all(plan.disposition is OptimizationDisposition.KEEP for plan in plans):
                return self._coupled_result(
                    evidence,
                    (),
                    tuple(plan.profile_digest for plan in plans if plan.profile_digest),
                    ("all_members_keep_current_configuration",),
                    disposition=OptimizationDisposition.KEEP,
                )
            return self._coupled_result(
                evidence,
                (),
                (),
                ("coupled_members_do_not_share_one_eligible_outcome",),
            )
        candidates = tuple(plan.candidate for plan in plans if plan.candidate is not None)
        if len(candidates) != len(plans):
            return self._coupled_result(
                evidence,
                (),
                (),
                ("coupled_candidate_set_incomplete",),
            )
        return self._coupled_result(
            evidence,
            candidates,
            tuple(plan.profile_digest for plan in plans if plan.profile_digest),
            (),
            disposition=OptimizationDisposition.CANDIDATE,
        )

    @staticmethod
    def _coupled_result(
        evidence: CoupledResourceOptimizationEvidence,
        candidates: tuple[FinOpsCandidate, ...],
        profile_digests: tuple[str, ...],
        reasons: tuple[str, ...],
        *,
        disposition: OptimizationDisposition = OptimizationDisposition.REVIEW_REQUIRED,
    ) -> CoupledResourceOptimizationPlan:
        return CoupledResourceOptimizationPlan(
            disposition=disposition,
            target_set_id=evidence.target_set_id,
            target_revision_digest=evidence.target_revision_digest,
            candidates=candidates,
            profile_digests=profile_digests,
            causal_order=evidence.causal_order,
            logical_target_lock=evidence.logical_target_lock,
            idempotency_key=evidence.idempotency_key,
            reasons=reasons,
        )

    def _review(
        self,
        evidence: ResourceOptimizationEvidence,
        profile: ServiceFamilyProfile | None,
        *reasons: str,
    ) -> ResourceOptimizationPlan:
        return self._result(
            evidence,
            profile,
            OptimizationDisposition.REVIEW_REQUIRED,
            reasons,
        )

    def _keep(
        self,
        evidence: ResourceOptimizationEvidence,
        profile: ServiceFamilyProfile,
        reason: str,
    ) -> ResourceOptimizationPlan:
        return self._result(evidence, profile, OptimizationDisposition.KEEP, (reason,))

    @staticmethod
    def _result(
        evidence: ResourceOptimizationEvidence,
        profile: ServiceFamilyProfile | None,
        disposition: OptimizationDisposition,
        reasons: tuple[str, ...],
    ) -> ResourceOptimizationPlan:
        return ResourceOptimizationPlan(
            disposition=disposition,
            resource_id=evidence.resource.resource_id,
            profile_id=profile.profile_id if profile else None,
            profile_version=profile.version if profile else None,
            profile_digest=profile.digest if profile else None,
            candidate=None,
            reasons=reasons,
        )


__all__ = [
    "ClarificationDisposition",
    "ClarificationResponseShape",
    "CoupledResourceOptimizationEvidence",
    "CoupledResourceOptimizationPlan",
    "OptimizationDisposition",
    "OptimizationClarificationAttestation",
    "OptimizationClarificationRequest",
    "OptimizationClarificationResult",
    "ResourceOptimizationEvidence",
    "ResourceOptimizationPlan",
    "ResourceOptimizationPlanner",
    "ServiceFamilyProfile",
    "default_service_family_profiles",
    "build_optimization_clarification",
    "evaluate_optimization_attestation",
]
