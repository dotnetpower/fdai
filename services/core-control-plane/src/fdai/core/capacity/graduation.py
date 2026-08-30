"""Deterministic, proposal-only capacity graduation decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.shared.contracts.models import ContractBase, SemVer

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_RECOMMENDATION_ID_PATTERN = r"^capacity-graduation-recommendation:[a-f0-9]{64}$"
_REF = Annotated[str, Field(min_length=1, max_length=512)]
_RATIO = Annotated[float, Field(ge=0.0)]


class CapacityTransition(StrEnum):
    """Optional topology transitions governed by one policy family."""

    SCALE_TO_ZERO = "scale_to_zero"
    DEDICATED_VECTOR_STORE = "dedicated_vector_store"
    AKS_OR_CELL = "aks_or_cell"
    NON_AZURE_PROVIDER = "non_azure_provider"


class GraduationRecommendationStatus(StrEnum):
    """Proposal-only outcome of one deterministic policy evaluation."""

    RECOMMEND = "recommend"
    HOLD = "hold"


class ScaleToZeroPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_profile: _REF
    min_zero_lag_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    min_cold_starts: Annotated[int, Field(ge=1)]
    min_observation_days: Annotated[int, Field(ge=1)]
    max_cold_start_budget_ratio: Annotated[float, Field(gt=0.0)]
    max_delivery_violations: Annotated[int, Field(ge=0)]
    max_cost_ratio: Annotated[float, Field(gt=0.0)]


class DedicatedVectorStorePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_profile: _REF
    min_capacity_ratio: Annotated[float, Field(gt=0.0, le=1.0)]
    min_latency_budget_ratio: Annotated[float, Field(gt=0.0, le=1.0)]
    min_consecutive_windows: Annotated[int, Field(ge=1)]
    max_cost_ratio: Annotated[float, Field(gt=0.0)]


class AksOrCellPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_profile: _REF
    min_capacity_ratio: Annotated[float, Field(gt=0.0, le=1.0)]
    min_consecutive_windows: Annotated[int, Field(ge=1)]
    max_headroom_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    heavy_capabilities: tuple[_REF, ...]
    max_cost_ratio: Annotated[float, Field(gt=0.0)]

    @model_validator(mode="after")
    def _canonical_capabilities(self) -> AksOrCellPolicy:
        if (
            not self.heavy_capabilities
            or tuple(sorted(set(self.heavy_capabilities))) != self.heavy_capabilities
        ):
            raise ValueError("heavy_capabilities MUST be non-empty, sorted, and unique")
        return self


class NonAzureProviderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_profile: _REF
    required_contract_count: Annotated[int, Field(ge=1)]
    min_shadow_campaigns: Annotated[int, Field(ge=1)]
    max_policy_escapes: Annotated[int, Field(ge=0)]
    max_cost_ratio: Annotated[float, Field(gt=0.0)]


class CapacityGraduationPolicy(ContractBase):
    """Versioned provider-neutral thresholds for optional topology transitions."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
    version: SemVer
    cost_evidence_max_age_seconds: Annotated[int, Field(ge=1)]
    scale_to_zero: ScaleToZeroPolicy
    dedicated_vector_store: DedicatedVectorStorePolicy
    aks_or_cell: AksOrCellPolicy
    non_azure_provider: NonAzureProviderPolicy
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def from_catalog(cls, value: dict[str, object]) -> Self:
        """Build a content-addressed policy from strict catalog values."""

        digest = ontology_function_digest(value)
        return cls.model_validate({**value, "content_digest": digest})

    @model_validator(mode="after")
    def _digest_matches(self) -> CapacityGraduationPolicy:
        expected = ontology_function_digest(
            self.model_dump(mode="json", exclude={"content_digest"})
        )
        if self.content_digest != expected:
            raise ValueError("capacity graduation policy digest does not match its content")
        return self


class CapacityGraduationEvidence(ContractBase):
    """Exact measurement receipt inputs for one optional transition."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    transition: CapacityTransition
    target_ref: _REF
    correlation_id: _REF
    observed_at: datetime
    source_authority_ref: _REF
    evidence_refs: tuple[_REF, ...]
    complete: bool
    synthetic: bool
    projected_cost_ratio: _RATIO | None = None
    cost_evidence_ref: _REF | None = None
    cost_observed_at: datetime | None = None
    zero_lag_ratio: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    cold_start_count: Annotated[int, Field(ge=0)] | None = None
    observation_days: Annotated[int, Field(ge=0)] | None = None
    cold_start_budget_ratio: _RATIO | None = None
    delivery_violations: Annotated[int, Field(ge=0)] | None = None
    capacity_ratio: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    latency_budget_ratio: _RATIO | None = None
    consecutive_windows: Annotated[int, Field(ge=0)] | None = None
    headroom_ratio: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    required_capabilities: tuple[_REF, ...] = ()
    contract_count: Annotated[int, Field(ge=0)] | None = None
    shadow_campaigns: Annotated[int, Field(ge=0)] | None = None
    policy_escapes: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _canonical_evidence(self) -> CapacityGraduationEvidence:
        if self.observed_at.tzinfo is None:
            raise ValueError("capacity graduation observed_at MUST be timezone-aware")
        if not self.evidence_refs or tuple(sorted(set(self.evidence_refs))) != self.evidence_refs:
            raise ValueError("capacity graduation evidence_refs MUST be non-empty and canonical")
        if tuple(sorted(set(self.required_capabilities))) != self.required_capabilities:
            raise ValueError("required_capabilities MUST be sorted and unique")
        if self.cost_observed_at is not None and self.cost_observed_at.tzinfo is None:
            raise ValueError("cost_observed_at MUST be timezone-aware")
        return self


class CapacityGraduationRecommendation(ContractBase):
    """Freyr-owned, shadow-only result that grants no topology authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: Annotated[str, Field(pattern=_RECOMMENDATION_ID_PATTERN)]
    transition: CapacityTransition
    target_ref: _REF
    status: GraduationRecommendationStatus
    target_profile: _REF
    reason_codes: tuple[_REF, ...]
    policy_id: _REF
    policy_version: SemVer
    policy_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    evidence_refs: tuple[_REF, ...]
    evaluated_at: datetime
    producer_principal: Literal["Freyr"] = "Freyr"
    shadow_only: Literal[True] = True
    execution_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        evidence: CapacityGraduationEvidence,
        policy: CapacityGraduationPolicy,
        status: GraduationRecommendationStatus,
        target_profile: str,
        reason_codes: tuple[str, ...],
        evaluated_at: datetime,
    ) -> Self:
        """Create a replay-stable advisory result."""

        prototype = cls.model_construct(
            schema_version="1.0.0",
            id="capacity-graduation-recommendation:" + "0" * 64,
            transition=evidence.transition,
            target_ref=evidence.target_ref,
            status=status,
            target_profile=target_profile,
            reason_codes=reason_codes,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_digest=policy.content_digest,
            evidence_refs=evidence.evidence_refs,
            evaluated_at=evaluated_at.astimezone(UTC),
            producer_principal="Freyr",
            shadow_only=True,
            execution_authority=False,
        )
        body = prototype.model_dump(mode="json", exclude={"id"})
        digest = ontology_function_digest(body)
        return cls.model_validate(
            {
                **body,
                "id": (f"capacity-graduation-recommendation:{digest.removeprefix('sha256:')}"),
            }
        )


class CapacityGraduationController:
    """Apply one reviewed policy without reading providers or changing topology."""

    def __init__(self, policy: CapacityGraduationPolicy) -> None:
        self._policy = policy

    def evaluate(
        self,
        evidence: CapacityGraduationEvidence,
        *,
        evaluated_at: datetime,
    ) -> CapacityGraduationRecommendation:
        """Return a shadow recommendation or explicit hold with stable reasons."""

        if evaluated_at.tzinfo is None:
            raise ValueError("capacity graduation evaluated_at MUST be timezone-aware")
        reasons = self._common_holds(evidence, evaluated_at=evaluated_at)
        policy = self._transition_policy(evidence.transition)
        reasons.extend(self._transition_holds(evidence))
        status = (
            GraduationRecommendationStatus.HOLD
            if reasons
            else GraduationRecommendationStatus.RECOMMEND
        )
        return CapacityGraduationRecommendation.create(
            evidence=evidence,
            policy=self._policy,
            status=status,
            target_profile=policy.target_profile,
            reason_codes=tuple(sorted(set(reasons))) or ("graduation_thresholds_satisfied",),
            evaluated_at=evaluated_at,
        )

    def _common_holds(
        self,
        evidence: CapacityGraduationEvidence,
        *,
        evaluated_at: datetime,
    ) -> list[str]:
        reasons: list[str] = []
        if not evidence.complete:
            reasons.append("evidence_incomplete")
        if evidence.synthetic:
            reasons.append("evidence_synthetic")
        if (
            evidence.projected_cost_ratio is None
            or evidence.cost_evidence_ref is None
            or evidence.cost_observed_at is None
        ):
            reasons.append("cost_evidence_missing")
        elif evaluated_at.astimezone(UTC) > evidence.cost_observed_at.astimezone(UTC) + timedelta(
            seconds=self._policy.cost_evidence_max_age_seconds
        ):
            reasons.append("cost_evidence_stale")
        else:
            max_cost_ratio = self._transition_policy(evidence.transition).max_cost_ratio
            if evidence.projected_cost_ratio > max_cost_ratio:
                reasons.append("cost_ceiling_exceeded")
        return reasons

    def _transition_policy(
        self,
        transition: CapacityTransition,
    ) -> ScaleToZeroPolicy | DedicatedVectorStorePolicy | AksOrCellPolicy | NonAzureProviderPolicy:
        if transition is CapacityTransition.SCALE_TO_ZERO:
            return self._policy.scale_to_zero
        if transition is CapacityTransition.DEDICATED_VECTOR_STORE:
            return self._policy.dedicated_vector_store
        if transition is CapacityTransition.AKS_OR_CELL:
            return self._policy.aks_or_cell
        return self._policy.non_azure_provider

    def _transition_holds(self, evidence: CapacityGraduationEvidence) -> list[str]:
        if evidence.transition is CapacityTransition.SCALE_TO_ZERO:
            scale_policy = self._policy.scale_to_zero
            return _threshold_holds(
                (
                    (
                        "zero_lag_ratio_below_threshold",
                        evidence.zero_lag_ratio,
                        scale_policy.min_zero_lag_ratio,
                        "ge",
                    ),
                    (
                        "cold_start_samples_insufficient",
                        evidence.cold_start_count,
                        scale_policy.min_cold_starts,
                        "ge",
                    ),
                    (
                        "observation_window_insufficient",
                        evidence.observation_days,
                        scale_policy.min_observation_days,
                        "ge",
                    ),
                    (
                        "cold_start_budget_exceeded",
                        evidence.cold_start_budget_ratio,
                        scale_policy.max_cold_start_budget_ratio,
                        "le",
                    ),
                    (
                        "delivery_violations_exceeded",
                        evidence.delivery_violations,
                        scale_policy.max_delivery_violations,
                        "le",
                    ),
                )
            )
        if evidence.transition is CapacityTransition.DEDICATED_VECTOR_STORE:
            vector_policy = self._policy.dedicated_vector_store
            capacity_ready = (
                evidence.capacity_ratio is not None
                and evidence.capacity_ratio >= vector_policy.min_capacity_ratio
            )
            latency_ready = (
                evidence.latency_budget_ratio is not None
                and evidence.latency_budget_ratio >= vector_policy.min_latency_budget_ratio
                and evidence.consecutive_windows is not None
                and evidence.consecutive_windows >= vector_policy.min_consecutive_windows
            )
            return [] if capacity_ready or latency_ready else ["vector_pressure_below_threshold"]
        if evidence.transition is CapacityTransition.AKS_OR_CELL:
            cell_policy = self._policy.aks_or_cell
            sustained_pressure = (
                evidence.capacity_ratio is not None
                and evidence.capacity_ratio >= cell_policy.min_capacity_ratio
                and evidence.consecutive_windows is not None
                and evidence.consecutive_windows >= cell_policy.min_consecutive_windows
            )
            low_headroom = (
                evidence.headroom_ratio is not None
                and evidence.headroom_ratio < cell_policy.max_headroom_ratio
            )
            heavy_need = bool(
                set(evidence.required_capabilities).intersection(cell_policy.heavy_capabilities)
            )
            return (
                []
                if sustained_pressure or low_headroom or heavy_need
                else ["cell_pressure_below_threshold"]
            )
        provider_policy = self._policy.non_azure_provider
        return _threshold_holds(
            (
                (
                    "provider_contracts_incomplete",
                    evidence.contract_count,
                    provider_policy.required_contract_count,
                    "ge",
                ),
                (
                    "shadow_campaigns_insufficient",
                    evidence.shadow_campaigns,
                    provider_policy.min_shadow_campaigns,
                    "ge",
                ),
                (
                    "policy_escapes_exceeded",
                    evidence.policy_escapes,
                    provider_policy.max_policy_escapes,
                    "le",
                ),
            )
        )


def _threshold_holds(
    checks: tuple[tuple[str, int | float | None, int | float, Literal["ge", "le"]], ...],
) -> list[str]:
    return [
        reason
        for reason, actual, expected, comparison in checks
        if actual is None
        or (comparison == "ge" and actual < expected)
        or (comparison == "le" and actual > expected)
    ]


__all__ = [
    "AksOrCellPolicy",
    "CapacityGraduationController",
    "CapacityGraduationEvidence",
    "CapacityGraduationPolicy",
    "CapacityGraduationRecommendation",
    "CapacityTransition",
    "DedicatedVectorStorePolicy",
    "GraduationRecommendationStatus",
    "NonAzureProviderPolicy",
    "ScaleToZeroPolicy",
]
