"""100%-coverage catalog-driven forecasting, AMBA, and SLO burn-rate engine (D011-D020).

Binds all 156 canonical ResourceTypes, 312 platform metric recipes, 156 KQL
recipes, 350 AMBA baseline alert rules, and 12 Azure Monitor Log Analytics
categories to FDAI's deterministic forecasting and SLO primitives
(:class:`~fdai.core.detection.forecast.LinearForecastDetector`,
:class:`~fdai.core.detection.forecast_evaluation.ForecastTargetSpec`,
:func:`~fdai.core.detection.forecast_band.prediction_band`, and
:class:`~fdai.core.slo.burn_rate.BurnRateEvaluator`).
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from fdai.core.detection.forecast import (
    ForecastDetectorDecision,
    ForecastDetectorEvaluation,
    ForecastFinding,
    LinearForecastDetector,
)
from fdai.core.detection.forecast_band import ForecastBand, prediction_band
from fdai.core.detection.forecast_evaluation import ForecastTargetSpec
from fdai.core.detection.series import MetricSample
from fdai.core.slo.burn_rate import BurnRate, BurnRateAlert, BurnRateBreach, BurnRateEvaluator
from fdai.core.slo.models import SLI, SLO, BurnRateAlertDef, SLIKind
from fdai.delivery.azure.resource_type_recipes import (
    AmbaAlertRecipe,
    PlatformMetricRecipe,
    load_resource_type_recipe_catalog,
)
from fdai.shared.contracts.models import Category

_DEFAULT_SCOPE_DIGEST: Final[str] = "0" * 64
_CATEGORY_TO_CONTRACT: Final[Mapping[str, Category]] = {
    "compute": Category.RELIABILITY,
    "containers": Category.RELIABILITY,
    "networking": Category.RELIABILITY,
    "databases": Category.RELIABILITY,
    "storage": Category.RELIABILITY,
    "security": Category.SECURITY,
    "ai-ml": Category.RELIABILITY,
    "integration": Category.RELIABILITY,
    "observability": Category.RELIABILITY,
    "governance": Category.COMPLIANCE,
}


def _direction_for_comparison(comparison: str) -> str:
    return "rising" if comparison == "gte" else "falling"


def _direction_for_amba_operator(operator: str) -> str:
    return "rising" if operator in {"GreaterThan", "GreaterThanOrEqual"} else "falling"


@functools.lru_cache(maxsize=2)
def build_catalog_forecast_target_specs(
    repo_root: Path | None = None,
    *,
    access_scope_digest: str = _DEFAULT_SCOPE_DIGEST,
) -> Mapping[str, ForecastTargetSpec]:
    """Build 312 ForecastTargetSpecs covering 100% of canonical ResourceType platform metrics."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    specs: dict[str, ForecastTargetSpec] = {}
    for rt, profile in sorted(catalog.profiles.items()):
        for pm in profile.platform_metrics:
            direction = _direction_for_comparison(pm.comparison)
            specs[pm.metric_id] = ForecastTargetSpec(
                detector_id=f"forecast.{pm.metric_id}",
                detector_version="1.0.0",
                scorer_version="1.0.0",
                access_scope_digest=access_scope_digest,
                resource_ref=f"catalog:{rt}",
                metric=pm.metric_id,
                threshold=pm.threshold,
                horizon_seconds=1800,
                lookback_seconds=3600,
                telemetry_grace_seconds=300,
                direction=direction,
                min_samples=5,
                min_r_squared=0.5,
                confidence_level="0.90",
            )
    return MappingProxyType(specs)


@functools.lru_cache(maxsize=2)
def build_catalog_linear_forecasters(
    repo_root: Path | None = None,
) -> Mapping[str, LinearForecastDetector]:
    """Build 312 LinearForecastDetectors for all 156 canonical ResourceTypes."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    forecasters: dict[str, LinearForecastDetector] = {}
    for _rt, profile in sorted(catalog.profiles.items()):
        contract_cat = _CATEGORY_TO_CONTRACT.get(profile.category, Category.RELIABILITY)
        for pm in profile.platform_metrics:
            forecasters[pm.metric_id] = LinearForecastDetector(
                detector_id=f"forecast.{pm.metric_id}",
                threshold=pm.threshold,
                horizon_seconds=1800.0,
                direction=_direction_for_comparison(pm.comparison),
                category=contract_cat,
                min_samples=5,
                min_r_squared=0.5,
            )
    return MappingProxyType(forecasters)


@functools.lru_cache(maxsize=2)
def build_amba_pre_breach_forecasters(
    repo_root: Path | None = None,
) -> Mapping[str, LinearForecastDetector]:
    """Build 350 proactive pre-breach LinearForecastDetectors for all 350 AMBA alert recipes."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    detectors: dict[str, LinearForecastDetector] = {}
    for alert_id, alert in sorted(catalog.amba_alerts.items()):
        horizon = max(300.0, float(alert.window_minutes * 60 * 3))
        detectors[alert_id] = LinearForecastDetector(
            detector_id=f"amba-forecast.{alert_id}",
            threshold=alert.threshold,
            horizon_seconds=horizon,
            direction=_direction_for_amba_operator(alert.operator),
            category=Category.RELIABILITY,
            min_samples=5,
            min_r_squared=0.5,
        )
    return MappingProxyType(detectors)


@functools.lru_cache(maxsize=2)
def build_catalog_slo_specs(
    repo_root: Path | None = None,
) -> Mapping[str, SLO]:
    """Build 156 multi-window, multi-burn-rate SLOs covering all 156 canonical ResourceTypes."""
    catalog = load_resource_type_recipe_catalog(repo_root)
    slos: dict[str, SLO] = {}
    for rt, profile in sorted(catalog.profiles.items()):
        sli_kind = (
            SLIKind.LATENCY if profile.category in {"databases", "ai-ml"} else SLIKind.AVAILABILITY
        )
        slos[rt] = SLO(
            id=f"slo.{rt}",
            objective_ratio=0.999,
            window_days=30,
            sli=SLI(
                kind=sli_kind,
                good_query=f"{profile.kql_recipe.log_table} | where v == 0",
                total_query=profile.kql_recipe.kql,
                labels={"resource_type": rt},
            ),
            burn_rate_alerts=(
                BurnRateAlertDef(
                    name=f"{rt}.fast_burn",
                    short_window_minutes=5,
                    long_window_minutes=60,
                    burn_rate_threshold=14.4,
                    severity="sev1",
                ),
                BurnRateAlertDef(
                    name=f"{rt}.slow_burn",
                    short_window_minutes=30,
                    long_window_minutes=360,
                    burn_rate_threshold=6.0,
                    severity="sev2",
                ),
            ),
            description=f"Catalog multi-window SLO for {rt}",
        )
    return MappingProxyType(slos)


@dataclass(frozen=True, slots=True)
class CatalogForecastPredictionResult:
    """Complete proactive forecast, AMBA pre-breach, and SLO burn-rate prediction result."""

    resource_ref: str
    resource_type: str
    metric_id: str
    amba_alert_id: str
    evaluation: ForecastDetectorEvaluation
    amba_evaluation: ForecastDetectorEvaluation
    band: ForecastBand | None
    slo_breaches: tuple[BurnRateBreach, ...]
    forecast_digest: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError("CatalogForecastPredictionResult MUST have execution_authority=False")

    @property
    def finding(self) -> ForecastFinding | None:
        return self.evaluation.finding


class CatalogForecastPredictionEngine:
    """Execute linear forecasting, AMBA pre-breach ETA, and SLO burn-rate prediction."""

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root
        self._recipes = load_resource_type_recipe_catalog(repo_root)
        self._forecasters = build_catalog_linear_forecasters(repo_root)
        self._amba_forecasters = build_amba_pre_breach_forecasters(repo_root)
        self._slos = build_catalog_slo_specs(repo_root)
        self._burn_evaluator = BurnRateEvaluator()

    def predict(
        self,
        *,
        resource_ref: str,
        resource_type: str,
        metric_id: str,
        amba_alert_id: str,
        history: Sequence[MetricSample],
        window_bucket: str = "2026-11-01T00:00Z",
        short_good_events: int = 980,
        short_total_events: int = 1000,
        long_good_events: int = 9800,
        long_total_events: int = 10000,
    ) -> CatalogForecastPredictionResult:
        """Evaluate metric forecast, AMBA pre-breach forecast, prediction band, and SLO burn."""
        if not resource_ref.strip():
            raise ValueError("resource_ref MUST be non-empty")
        profile = self._recipes.get_profile(resource_type)
        forecaster = self._forecasters[metric_id]
        amba_forecaster = self._amba_forecasters[amba_alert_id]
        slo = self._slos[profile.resource_type]

        evaluation = forecaster.evaluate_result(
            metric=metric_id,
            resource_ref=resource_ref,
            history=history,
            window_bucket=window_bucket,
        )
        amba_evaluation = amba_forecaster.evaluate_result(
            metric=metric_id,
            resource_ref=resource_ref,
            history=history,
            window_bucket=window_bucket,
        )
        band: ForecastBand | None = None
        if evaluation.finding is not None:
            band = prediction_band(
                evaluation.finding,
                confidence_level="0.90",
            )

        burn_alerts: list[BurnRateAlert] = []
        for alert_def in slo.burn_rate_alerts:
            burn_alerts.append(
                BurnRateAlert(
                    slo_id=slo.id,
                    alert=alert_def,
                    short=BurnRate(
                        window_minutes=alert_def.short_window_minutes,
                        good_events=short_good_events,
                        total_events=short_total_events,
                        objective_ratio=slo.objective_ratio,
                    ),
                    long=BurnRate(
                        window_minutes=alert_def.long_window_minutes,
                        good_events=long_good_events,
                        total_events=long_total_events,
                        objective_ratio=slo.objective_ratio,
                    ),
                )
            )
        breaches = self._burn_evaluator.evaluate(burn_alerts)
        digest_input = (
            f"{resource_ref}|{resource_type}|{metric_id}|"
            f"{amba_alert_id}|{evaluation.decision.value}"
        )
        digest = "sha256:" + hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        return CatalogForecastPredictionResult(
            resource_ref=resource_ref,
            resource_type=resource_type,
            metric_id=metric_id,
            amba_alert_id=amba_alert_id,
            evaluation=evaluation,
            amba_evaluation=amba_evaluation,
            band=band,
            slo_breaches=breaches,
            forecast_digest=digest,
        )


__all__ = [
    "AmbaAlertRecipe",
    "CatalogForecastPredictionEngine",
    "CatalogForecastPredictionResult",
    "ForecastDetectorDecision",
    "PlatformMetricRecipe",
    "build_amba_pre_breach_forecasters",
    "build_catalog_forecast_target_specs",
    "build_catalog_linear_forecasters",
    "build_catalog_slo_specs",
]
