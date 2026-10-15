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

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip() or not self.resource_types:
            raise ValueError("service family profile identity MUST be non-empty")
        if any(not resource_type.strip() for resource_type in self.resource_types):
            raise ValueError("service family profile resource types MUST be non-empty")
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
    execution_authority: bool = False


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
    "OptimizationDisposition",
    "ResourceOptimizationEvidence",
    "ResourceOptimizationPlan",
    "ResourceOptimizationPlanner",
    "ServiceFamilyProfile",
]
