"""Versioned, authority-free AKS commerce scenario projections."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.executor_models import ContractBase

BoundedText = Annotated[str, Field(min_length=1, max_length=512)]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")]


class AksCommerceStatus(StrEnum):
    """Deterministic state of one commerce business-service assessment."""

    CATALOG_UNAVAILABLE = "catalog_unavailable"
    DEAD_LETTER_GROWTH = "dead_letter_growth"
    DEPENDENCY_PRESSURE = "dependency_pressure"
    DEPLOYMENT_REGRESSION = "deployment_regression"
    HEALTHY = "healthy"
    HELD = "held"
    ORDER_BACKLOG = "order_backlog"
    RECOVERED = "recovered"


class AksCommerceEvidenceState(StrEnum):
    """Qualification state for one evidence family."""

    COMPLETE = "complete"
    CONFLICTING = "conflicting"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class AksCommerceMetric(ContractBase):
    """One bounded aggregate metric used by the business assessment."""

    name: ReasonCode
    unit: Annotated[str, Field(min_length=1, max_length=32)]
    current: float | None
    previous: float | None = None
    source_ref: BoundedText
    observed_at: datetime
    state: AksCommerceEvidenceState
    synthetic: bool = False

    @model_validator(mode="after")
    def validate_metric(self) -> AksCommerceMetric:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("AKS commerce metric observed_at must be timezone-aware")
        if self.state is AksCommerceEvidenceState.COMPLETE and self.current is None:
            raise ValueError("complete AKS commerce metric requires a current value")
        if self.state is not AksCommerceEvidenceState.COMPLETE and self.current is not None:
            raise ValueError("unqualified AKS commerce metric cannot carry a value")
        return self


class AksCommerceSlo(ContractBase):
    """One workload SLO state rendered without deriving values in the browser."""

    slo_id: Annotated[str, Field(min_length=1, max_length=192)]
    objective_ratio: Annotated[float, Field(gt=0, le=1)]
    observed_ratio: Annotated[float | None, Field(ge=0, le=1)] = None
    budget_remaining_ratio: Annotated[float | None, Field(ge=0, le=1)] = None
    breached: bool | None
    state: AksCommerceEvidenceState
    source_ref: BoundedText

    @model_validator(mode="after")
    def validate_slo(self) -> AksCommerceSlo:
        values = (self.observed_ratio, self.budget_remaining_ratio, self.breached)
        if self.state is AksCommerceEvidenceState.COMPLETE and any(
            value is None for value in values
        ):
            raise ValueError("complete AKS commerce SLO requires measured values")
        if self.state is not AksCommerceEvidenceState.COMPLETE and any(
            value is not None for value in values
        ):
            raise ValueError("unqualified AKS commerce SLO cannot carry measured values")
        return self


class AksCommerceWorkload(ContractBase):
    """One workload in the reviewed business dependency path."""

    workload_id: Annotated[str, Field(min_length=1, max_length=192)]
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    resource_ref: BoundedText | None = None
    ready: bool | None = None
    revision: Annotated[str | None, Field(max_length=256)] = None
    evidence_state: AksCommerceEvidenceState

    @model_validator(mode="after")
    def validate_workload(self) -> AksCommerceWorkload:
        if self.evidence_state is AksCommerceEvidenceState.COMPLETE:
            if self.resource_ref is None or self.ready is None:
                raise ValueError("complete AKS commerce workload requires identity and readiness")
        elif self.ready is not None:
            raise ValueError("unqualified AKS commerce workload cannot claim readiness")
        return self


class AksCommerceAction(ContractBase):
    """Read-only state of a governed recovery proposal or run."""

    action_type: Annotated[str, Field(min_length=1, max_length=192)]
    state: Literal["proposed", "pending_approval", "approved", "running", "completed", "failed"]
    target_ref: BoundedText
    action_run_ref: BoundedText | None = None
    execution_authority: Literal[False] = False
    effect_verified: bool | None = None
    effect_evidence_ref: BoundedText | None = None

    @model_validator(mode="after")
    def validate_action(self) -> AksCommerceAction:
        if self.effect_verified is True and self.effect_evidence_ref is None:
            raise ValueError("verified AKS commerce action requires effect evidence")
        if self.state != "completed" and self.effect_verified is not None:
            raise ValueError("nonterminal AKS commerce action cannot claim effect verification")
        return self


class AksCommerceProjection(ContractBase):
    """Authenticated Operator projection for one exact assessment window."""

    type: Literal["aks-commerce.projection"] = "aks-commerce.projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    assessment_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    service_id: Literal["order-fulfillment", "catalog-browse"]
    status: AksCommerceStatus
    summary: Annotated[str, Field(min_length=1, max_length=512)]
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    complete: bool
    synthetic: bool
    affected_workload_ids: Annotated[tuple[str, ...], Field(max_length=16)] = ()
    dependency_path: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    workloads: Annotated[tuple[AksCommerceWorkload, ...], Field(min_length=1, max_length=16)]
    metrics: Annotated[tuple[AksCommerceMetric, ...], Field(max_length=32)] = ()
    slos: Annotated[tuple[AksCommerceSlo, ...], Field(min_length=1, max_length=8)]
    evidence_gaps: Annotated[tuple[ReasonCode, ...], Field(max_length=32)] = ()
    evidence_refs: Annotated[tuple[BoundedText, ...], Field(min_length=1, max_length=64)]
    proposed_action: AksCommerceAction | None = None
    owner_agent: Literal["Forseti"] = "Forseti"
    observer_agent: Literal["Heimdall"] = "Heimdall"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_projection(self) -> AksCommerceProjection:
        times = (self.observed_at, self.window_start, self.window_end)
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("AKS commerce projection times must be timezone-aware")
        if not self.window_start < self.window_end <= self.observed_at:
            raise ValueError("AKS commerce projection window must end by observation time")
        if len(set(self.dependency_path)) != len(self.dependency_path):
            raise ValueError("AKS commerce dependency path must not contain cycles")
        if len(set(self.evidence_gaps)) != len(self.evidence_gaps):
            raise ValueError("AKS commerce evidence gaps must be unique")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("AKS commerce evidence refs must be unique")
        if self.complete == bool(self.evidence_gaps):
            raise ValueError("AKS commerce completeness must match empty evidence gaps")
        if self.status is AksCommerceStatus.HELD and self.complete:
            raise ValueError("held AKS commerce projection cannot be complete")
        if self.status is not AksCommerceStatus.HELD and not self.complete:
            raise ValueError("incomplete AKS commerce projection must be held")
        return self


__all__ = [
    "AksCommerceAction",
    "AksCommerceEvidenceState",
    "AksCommerceMetric",
    "AksCommerceProjection",
    "AksCommerceSlo",
    "AksCommerceStatus",
    "AksCommerceWorkload",
]
