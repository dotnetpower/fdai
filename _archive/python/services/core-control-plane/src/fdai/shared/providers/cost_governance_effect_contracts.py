"""Effect expectation contracts for Cost Governance settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from fdai.shared.providers._cost_governance_contract_validation import (
    _aware,
    _digest,
    _identifier,
    _text,
)


class CostEffectKind(StrEnum):
    COST = "cost"
    CAPACITY = "capacity"
    SERVICE = "service"
    RECOVERY = "recovery"


class CostSettlementStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    CENSORED = "censored"
    UNSCORABLE = "unscorable"


class CostSavingsEvidenceClass(StrEnum):
    """Evidence strength for a nonzero measured saving."""

    VERIFIED_RUN_RATE = "verified-run-rate"
    INVOICE_ALLOCATED = "invoice-allocated"


class CostObservationLane(StrEnum):
    INDEPENDENT = "independent"
    EXECUTION = "execution"


@dataclass(frozen=True, slots=True)
class CostExpectedEffect:
    """One pre-effect expectation with a bounded observation window."""

    effect_id: str
    kind: CostEffectKind
    target_ref: str
    metric: str
    baseline_value: Decimal
    acceptable_min: Decimal
    acceptable_max: Decimal
    predicted_at: datetime
    horizon: timedelta
    telemetry_grace: timedelta
    source_digest: str
    estimated_only: bool = False
    savings_evidence_class: CostSavingsEvidenceClass | None = None
    currency: str | None = None
    baseline_window_digest: str | None = None
    treatment_window_digest: str | None = None
    demand_normalization_digest: str | None = None
    finalized_billing_receipt_digest: str | None = None
    allocation_rule_digest: str | None = None

    def __post_init__(self) -> None:
        _identifier("effect_id", self.effect_id)
        _text("target_ref", self.target_ref)
        _identifier("metric", self.metric)
        _aware("predicted_at", self.predicted_at)
        _digest("source_digest", self.source_digest)
        if self.acceptable_min > self.acceptable_max:
            raise ValueError("effect acceptable range MUST be ordered")
        if self.horizon <= timedelta(0) or self.telemetry_grace < timedelta(0):
            raise ValueError("effect horizon MUST be positive and grace nonnegative")
        savings_fields = (
            self.currency,
            self.baseline_window_digest,
            self.treatment_window_digest,
            self.demand_normalization_digest,
            self.finalized_billing_receipt_digest,
            self.allocation_rule_digest,
        )
        if self.kind is not CostEffectKind.COST:
            if self.savings_evidence_class is not None or any(
                value is not None for value in savings_fields
            ):
                raise ValueError("non-cost effect MUST NOT carry savings lineage")
            return
        if self.estimated_only:
            if self.savings_evidence_class is not None or any(
                value is not None for value in savings_fields
            ):
                raise ValueError("estimated-only cost effect MUST NOT claim savings evidence")
            return
        if self.savings_evidence_class is None:
            raise ValueError("measured cost effect requires a savings evidence class")
        if (
            self.currency is None
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isupper()
        ):
            raise ValueError("measured cost effect requires one uppercase currency")
        for name, value in (
            ("baseline_window_digest", self.baseline_window_digest),
            ("treatment_window_digest", self.treatment_window_digest),
            ("demand_normalization_digest", self.demand_normalization_digest),
        ):
            if value is None:
                raise ValueError(f"measured cost effect requires {name}")
            _digest(name, value)
        invoice = self.savings_evidence_class is CostSavingsEvidenceClass.INVOICE_ALLOCATED
        if invoice != (
            self.finalized_billing_receipt_digest is not None
            and self.allocation_rule_digest is not None
        ):
            raise ValueError(
                "invoice-allocated savings require finalized billing and allocation evidence"
            )
        for name, value in (
            ("finalized_billing_receipt_digest", self.finalized_billing_receipt_digest),
            ("allocation_rule_digest", self.allocation_rule_digest),
        ):
            if value is not None:
                _digest(name, value)

    @property
    def horizon_ends_at(self) -> datetime:
        return self.predicted_at + self.horizon

    @property
    def deadline_at(self) -> datetime:
        return self.horizon_ends_at + self.telemetry_grace


__all__ = [
    "CostEffectKind",
    "CostExpectedEffect",
    "CostObservationLane",
    "CostSavingsEvidenceClass",
    "CostSettlementStatus",
]
