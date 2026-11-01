"""FinOps FOCUS 1.1, Telemetry Cost Governance & GreenOps Carbon SCI (Rounds 9-12, E025-E036).

Implements 2025-2026 FinOps Foundation FOCUS 1.1 specification, Observability cost
governance, AI/GPU unit economics, and Green Software Foundation SCI carbon metrics:
- E025: FinOps FOCUS 1.1 normalized cost & usage record (``FocusCostRecord``)
- E026: Commitment discount analyzer (``CommitmentDiscountAssessment``)
- E027: Telemetry FinOps cardinality & tier advisor (``TelemetryCostAssessment``)
- E028: GenAI token & GPU unit-economics FinOps analyzer (``AiUnitEconomicsAssessment``)
- E029: Kubernetes / AKS namespace slack & Spot FinOps allocator (``KubernetesCostAllocation``)
- E030: FinOps spend velocity & budget exhaustion ETA forecaster (``ForecastCostBurnResult``)
- E031: GreenOps Scope 1/2/3 carbon footprint record (``CarbonFootprintRecord``)
- E032: Green Software Foundation SCI calculator (``SciScoreAssessment``)
- E033: Carbon-aware region & time-window shifting advisor (``CarbonAwareRecommendation``)
- E034: Orphaned & zombie resource waste detector (``OrphanedResourceAssessment``)
- E035: Cross-zone & NAT Gateway egress cost analyzer (``NetworkEgressCostAssessment``)
- E036: Unified FOCUS + Advisor + GreenOps evaluator (``evaluate_finops_greenops_posture``)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

_FOCUS_CHARGE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"Usage", "Purchase", "Tax", "Credit", "Adjustment"}
)


@dataclass(frozen=True, slots=True)
class FocusCostRecord:
    """E025: FinOps Open Cost and Usage Specification (FOCUS 1.1) normalized record."""

    resource_id: str
    service_name: str
    charge_category: str
    billed_cost: float
    effective_cost: float
    list_cost: float
    contracted_cost: float
    pricing_quantity: float
    pricing_unit: str
    commitment_discount_status: str = "None"
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.resource_id.strip()
            or not self.service_name.strip()
            or not self.pricing_unit.strip()
        ):
            raise ValueError("FocusCostRecord text fields MUST be non-empty")
        if self.charge_category not in _FOCUS_CHARGE_CATEGORIES:
            raise ValueError(f"Unsupported FOCUS ChargeCategory: {self.charge_category!r}")
        for val in (
            self.billed_cost,
            self.effective_cost,
            self.list_cost,
            self.contracted_cost,
            self.pricing_quantity,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("FocusCostRecord numeric amounts MUST be finite non-negative")
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("FocusCostRecord MUST remain read-only (execution_authority=False)")

    @property
    def negotiated_savings(self) -> float:
        return round(max(0.0, self.list_cost - self.effective_cost), 4)


@dataclass(frozen=True, slots=True)
class CommitmentDiscountAssessment:
    """E026: Azure Reservations & Savings Plans utilization and coverage assessment."""

    committed_hourly_usd: float
    utilized_hourly_usd: float
    eligible_on_demand_hourly_usd: float

    def __post_init__(self) -> None:
        for val in (
            self.committed_hourly_usd,
            self.utilized_hourly_usd,
            self.eligible_on_demand_hourly_usd,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Commitment discount amounts MUST be finite non-negative")
        if self.utilized_hourly_usd > self.committed_hourly_usd:
            raise ValueError("utilized_hourly_usd MUST NOT exceed committed_hourly_usd")

    @property
    def utilization_ratio(self) -> float:
        return (
            round(self.utilized_hourly_usd / self.committed_hourly_usd, 4)
            if self.committed_hourly_usd > 0
            else 1.0
        )

    @property
    def coverage_ratio(self) -> float:
        denom = self.utilized_hourly_usd + self.eligible_on_demand_hourly_usd
        return round(self.utilized_hourly_usd / denom, 4) if denom > 0 else 1.0

    @property
    def unused_waste_hourly_usd(self) -> float:
        return round(max(0.0, self.committed_hourly_usd - self.utilized_hourly_usd), 4)


@dataclass(frozen=True, slots=True)
class TelemetryCostAssessment:
    """E027: Observability FinOps for Log Analytics table ingestion and Prometheus cardinality."""

    table_name: str
    daily_ingestion_gb: float
    query_frequency_per_day: int
    active_prometheus_series: int
    analytics_tier_usd_per_gb: float = 2.76
    basic_tier_usd_per_gb: float = 0.50

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("table_name MUST be non-empty")
        if (
            type(self.daily_ingestion_gb) is bool
            or not math.isfinite(self.daily_ingestion_gb)
            or self.daily_ingestion_gb < 0
        ):
            raise ValueError("daily_ingestion_gb MUST be finite non-negative")
        for cnt in (self.query_frequency_per_day, self.active_prometheus_series):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("TelemetryCostAssessment counts MUST be non-negative integers")

    @property
    def recommend_basic_or_auxiliary_tier(self) -> bool:
        return self.daily_ingestion_gb >= 10.0 and self.query_frequency_per_day <= 2

    @property
    def cardinality_explosion_detected(self) -> bool:
        return self.active_prometheus_series >= 500_000

    @property
    def estimated_daily_savings_usd(self) -> float:
        if not self.recommend_basic_or_auxiliary_tier:
            return 0.0
        return round(
            self.daily_ingestion_gb
            * max(0.0, self.analytics_tier_usd_per_gb - self.basic_tier_usd_per_gb),
            2,
        )


@dataclass(frozen=True, slots=True)
class AiUnitEconomicsAssessment:
    """E028: GenAI token and GPU cluster unit-economics FinOps assessment."""

    total_cost_usd: float
    total_tokens_processed: int
    gpu_allocated_hours: float
    gpu_active_compute_hours: float

    def __post_init__(self) -> None:
        for val in (self.total_cost_usd, self.gpu_allocated_hours, self.gpu_active_compute_hours):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("AI unit-economics floats MUST be finite non-negative")
        if type(self.total_tokens_processed) is not int or self.total_tokens_processed < 0:
            raise ValueError("total_tokens_processed MUST be a non-negative integer")
        if self.gpu_active_compute_hours > self.gpu_allocated_hours:
            raise ValueError("gpu_active_compute_hours MUST NOT exceed gpu_allocated_hours")

    @property
    def cost_per_1k_tokens_usd(self) -> float:
        return (
            round((self.total_cost_usd / self.total_tokens_processed) * 1000.0, 6)
            if self.total_tokens_processed > 0
            else 0.0
        )

    @property
    def gpu_idle_waste_ratio(self) -> float:
        if self.gpu_allocated_hours == 0:
            return 0.0
        return round(
            (self.gpu_allocated_hours - self.gpu_active_compute_hours) / self.gpu_allocated_hours,
            4,
        )


@dataclass(frozen=True, slots=True)
class KubernetesCostAllocation:
    """E029: AKS namespace CPU/memory slack waste and Spot eligibility FinOps assessment."""

    namespace: str
    requested_cpu_cores: float
    used_cpu_cores_p95: float
    requested_memory_gib: float
    used_memory_gib_p95: float
    stateless_fault_tolerant: bool = False

    def __post_init__(self) -> None:
        if not self.namespace.strip():
            raise ValueError("namespace MUST be non-empty")
        for val in (
            self.requested_cpu_cores,
            self.used_cpu_cores_p95,
            self.requested_memory_gib,
            self.used_memory_gib_p95,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Kubernetes resource quantities MUST be finite non-negative")

    @property
    def cpu_slack_ratio(self) -> float:
        if self.requested_cpu_cores == 0:
            return 0.0
        return round(
            max(0.0, self.requested_cpu_cores - self.used_cpu_cores_p95) / self.requested_cpu_cores,
            4,
        )

    @property
    def memory_slack_ratio(self) -> float:
        if self.requested_memory_gib == 0:
            return 0.0
        return round(
            max(0.0, self.requested_memory_gib - self.used_memory_gib_p95)
            / self.requested_memory_gib,
            4,
        )

    @property
    def right_sizing_recommended(self) -> bool:
        return self.cpu_slack_ratio >= 0.50 or self.memory_slack_ratio >= 0.50


@dataclass(frozen=True, slots=True)
class ForecastCostBurnResult:
    """E030: Proactive FinOps budget burn-rate and exhaustion ETA forecast."""

    monthly_budget_usd: float
    mtd_spend_usd: float
    daily_burn_rate_usd: float
    days_remaining_in_month: int

    def __post_init__(self) -> None:
        for val in (self.monthly_budget_usd, self.mtd_spend_usd, self.daily_burn_rate_usd):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Budget values MUST be finite non-negative")
        if type(self.days_remaining_in_month) is not int or self.days_remaining_in_month < 0:
            raise ValueError("days_remaining_in_month MUST be a non-negative integer")

    @property
    def projected_eom_spend_usd(self) -> float:
        return round(
            self.mtd_spend_usd + self.daily_burn_rate_usd * self.days_remaining_in_month, 2
        )

    @property
    def budget_breach_predicted(self) -> bool:
        return self.projected_eom_spend_usd > self.monthly_budget_usd


@dataclass(frozen=True, slots=True)
class CarbonFootprintRecord:
    """E031: GreenOps & Azure Carbon Optimization Scope 1/2/3 emissions record."""

    resource_id: str
    region: str
    energy_kwh: float
    grid_carbon_intensity_g_per_kwh: float
    embodied_emissions_g_co2e: float

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.region.strip():
            raise ValueError("resource_id and region MUST be non-empty")
        for val in (
            self.energy_kwh,
            self.grid_carbon_intensity_g_per_kwh,
            self.embodied_emissions_g_co2e,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Carbon metrics MUST be finite non-negative")

    @property
    def operational_emissions_g_co2e(self) -> float:
        return round(self.energy_kwh * self.grid_carbon_intensity_g_per_kwh, 4)

    @property
    def total_emissions_kg_co2e(self) -> float:
        return round(
            (self.operational_emissions_g_co2e + self.embodied_emissions_g_co2e) / 1000.0, 6
        )


@dataclass(frozen=True, slots=True)
class SciScoreAssessment:
    """E032: Green Software Foundation SCI (Software Carbon Intensity) score: ((E * I) + M) / R."""

    footprint: CarbonFootprintRecord
    functional_units_r: int
    functional_unit_name: str = "1k_requests"

    def __post_init__(self) -> None:
        if type(self.functional_units_r) is not int or self.functional_units_r <= 0:
            raise ValueError("functional_units_r MUST be a positive integer")
        if not self.functional_unit_name.strip():
            raise ValueError("functional_unit_name MUST be non-empty")

    @property
    def sci_g_co2e_per_unit(self) -> float:
        total_g = (
            self.footprint.operational_emissions_g_co2e + self.footprint.embodied_emissions_g_co2e
        )
        return round(total_g / self.functional_units_r, 6)


@dataclass(frozen=True, slots=True)
class CarbonAwareRecommendation:
    """E033: Proposal-only carbon-aware batch/training region or window recommendation."""

    workload_ref: str
    current_region: str
    candidate_region: str
    current_intensity_g_per_kwh: float
    candidate_intensity_g_per_kwh: float
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.workload_ref.strip()
            or not self.current_region.strip()
            or not self.candidate_region.strip()
        ):
            raise ValueError("CarbonAwareRecommendation regions and workload_ref MUST be non-empty")
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("CarbonAwareRecommendation MUST have execution_authority=False")

    @property
    def reduction_ratio(self) -> float:
        if self.current_intensity_g_per_kwh <= 0:
            return 0.0
        diff = max(0.0, self.current_intensity_g_per_kwh - self.candidate_intensity_g_per_kwh)
        return round(diff / self.current_intensity_g_per_kwh, 4)


@dataclass(frozen=True, slots=True)
class OrphanedResourceAssessment:
    """E034: Zombie & orphaned cloud resource FinOps waste assessment."""

    unattached_disks_count: int
    idle_public_ips_count: int
    stale_snapshots_count: int
    empty_app_service_plans_count: int
    estimated_monthly_waste_usd: float

    def __post_init__(self) -> None:
        for cnt in (
            self.unattached_disks_count,
            self.idle_public_ips_count,
            self.stale_snapshots_count,
            self.empty_app_service_plans_count,
        ):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("Orphaned resource counts MUST be non-negative integers")
        if (
            type(self.estimated_monthly_waste_usd) is bool
            or not math.isfinite(self.estimated_monthly_waste_usd)
            or self.estimated_monthly_waste_usd < 0
        ):
            raise ValueError("estimated_monthly_waste_usd MUST be finite non-negative")

    @property
    def total_orphaned_resources(self) -> int:
        return (
            self.unattached_disks_count
            + self.idle_public_ips_count
            + self.stale_snapshots_count
            + self.empty_app_service_plans_count
        )


@dataclass(frozen=True, slots=True)
class NetworkEgressCostAssessment:
    """E035: Inter-zone, VNet peering, and NAT Gateway data-transfer FinOps analyzer."""

    cross_zone_gb: float
    vnet_peering_gb: float
    nat_gateway_gb: float
    internet_egress_gb: float

    def __post_init__(self) -> None:
        for val in (
            self.cross_zone_gb,
            self.vnet_peering_gb,
            self.nat_gateway_gb,
            self.internet_egress_gb,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("Network transfer GB values MUST be finite non-negative")

    @property
    def total_transfer_gb(self) -> float:
        return round(
            self.cross_zone_gb
            + self.vnet_peering_gb
            + self.nat_gateway_gb
            + self.internet_egress_gb,
            2,
        )


def evaluate_finops_greenops_posture(
    *,
    focus: FocusCostRecord,
    commitment: CommitmentDiscountAssessment,
    telemetry_cost: TelemetryCostAssessment,
    ai_unit: AiUnitEconomicsAssessment,
    k8s_cost: KubernetesCostAllocation,
    burn: ForecastCostBurnResult,
    sci: SciScoreAssessment,
    orphaned: OrphanedResourceAssessment,
    egress: NetworkEgressCostAssessment,
) -> dict[str, object]:
    """E036: Combine FOCUS 1.1, Telemetry FinOps, AI Unit Economics, and GreenOps SCI."""
    return {
        "negotiated_savings_usd": focus.negotiated_savings,
        "commitment_utilization_ratio": commitment.utilization_ratio,
        "telemetry_daily_savings_usd": telemetry_cost.estimated_daily_savings_usd,
        "cost_per_1k_tokens_usd": ai_unit.cost_per_1k_tokens_usd,
        "gpu_idle_waste_ratio": ai_unit.gpu_idle_waste_ratio,
        "k8s_right_sizing_recommended": k8s_cost.right_sizing_recommended,
        "budget_breach_predicted": burn.budget_breach_predicted,
        "sci_g_co2e_per_unit": sci.sci_g_co2e_per_unit,
        "total_orphaned_resources": orphaned.total_orphaned_resources,
        "total_network_transfer_gb": egress.total_transfer_gb,
        "execution_authority": False,
    }


__all__ = [
    "AiUnitEconomicsAssessment",
    "CarbonAwareRecommendation",
    "CarbonFootprintRecord",
    "CommitmentDiscountAssessment",
    "FocusCostRecord",
    "ForecastCostBurnResult",
    "KubernetesCostAllocation",
    "NetworkEgressCostAssessment",
    "OrphanedResourceAssessment",
    "SciScoreAssessment",
    "TelemetryCostAssessment",
    "evaluate_finops_greenops_posture",
]
