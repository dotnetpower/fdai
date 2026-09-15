"""Strict alert-quality HTTP selectors and no-authority response envelopes."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from fdai_service_contracts.alert_noise import NoiseAssessment, Ref
from fdai_service_contracts.alert_noise_base import FalseOnly
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertTreatment
from fdai_service_contracts.executor_models import ContractBase, Digest
from pydantic import ConfigDict, Field, StrictBool, model_validator

from fdai_operator_service.alert_quality_records import (
    MAX_ALERT_QUALITY_PLANS,
    validate_alert_quality_scope,
)

MAX_ALERT_QUALITY_BODY_BYTES = 16_384
UnavailableReason = Literal[
    "scope_not_configured",
    "scope_required",
    "source_unavailable",
    "assessment_missing",
    "assessment_not_current",
    "assessment_pending",
    "proposal_pending",
]
Operation = Literal["alert_noise.assess", "alert_noise.propose"]
RouteOperation = Operation | Literal["scopes", "settings.get", "settings.put", "requests.get"]


class AlertQualityResponse(ContractBase):
    """Retain valid historical evidence separately from capability and request eligibility.

    Expired reports carry assessment_not_current; future or invalid reports are
    withheld. Requestability never grants approval or execution authority.
    """

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)

    source: Literal["alert-noise-governance"]
    available: StrictBool
    enabled: StrictBool
    requestable: StrictBool = False
    authority: Literal["shadow"]
    unavailable_reason: UnavailableReason | None
    assessment: NoiseAssessment | None
    plans: Annotated[tuple[AlertChangePlan, ...], Field(max_length=MAX_ALERT_QUALITY_PLANS)]

    @model_validator(mode="after")
    def availability(self) -> Self:
        if self.requestable and not (self.available and self.enabled):
            raise ValueError("requestable alert quality requires available enabled capability")
        if self.assessment is None and self.plans:
            raise ValueError("alert quality plans require their source assessment")
        if self.available:
            if self.unavailable_reason not in {None, "assessment_not_current"}:
                raise ValueError("available alert quality MUST distinguish stale evidence")
            if self.unavailable_reason is not None and self.assessment is None:
                raise ValueError("stale evidence requires its retained assessment")
        elif self.assessment is not None or self.plans or self.unavailable_reason is None:
            raise ValueError("unavailable alert quality MUST NOT contain manufactured evidence")
        return self


class AlertQualityScopesResponse(ContractBase):
    """Exact authenticated discovery; opaque scopes never disclose subject bindings."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)

    source: Literal["alert-noise-governance"] = "alert-noise-governance"
    scope_refs: Annotated[tuple[Ref, ...], Field(max_length=64)]
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def bounded_scopes(self) -> Self:
        for scope in self.scope_refs:
            validate_alert_quality_scope(scope)
        if self.scope_refs != tuple(sorted(set(self.scope_refs))):
            raise ValueError("alert quality scopes MUST be sorted and unique")
        return self


class AlertAssessmentBody(ContractBase):
    """Only a scope selector is accepted for a producer-owned assessment request."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=False)
    scope_ref: Ref

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        validate_alert_quality_scope(self.scope_ref)
        return self


class AlertProposalBody(AlertAssessmentBody):
    """Select frozen evidence and one treatment; never provide a report or authority."""

    evidence_digest: Digest
    treatment: AlertTreatment

    @model_validator(mode="after")
    def exact_treatment_axis(self) -> Self:
        # Check every optional field independently, including half-specified pairs.
        allowed = {
            "routing": {"replacement_group_ref", "remove_group_ref"},
            "suppression": {"processing_rule_ref", "starts_at", "ends_at"},
            "evaluation": {"evaluation"},
        }[self.treatment.kind]
        for name in type(self.treatment).model_fields:
            if name not in {"kind", "target_ref", *allowed}:
                if getattr(self.treatment, name) is not None:
                    raise ValueError("alert treatment MUST contain exactly one axis")
        return self
