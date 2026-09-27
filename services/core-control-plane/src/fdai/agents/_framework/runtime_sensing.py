"""Focused Pantheon runtime wiring for Heimdall sensing dependencies."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents.heimdall import (
    ActionObservationHook,
    Heimdall,
    OperationalEvidenceHook,
)
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator


def configure_heimdall(
    agents: dict[str, Any],
    *,
    rate_threshold: int,
    rate_window: int,
    security_high_threshold: int,
    security_window_events: int,
    alert_rate_per_hour: int,
    action_semantics: ActionSemanticsCatalog | None,
    forecast_evaluator: ForecastEpisodeEvaluator | None,
    forecast_closer: ForecastClosureCoordinator | None,
    forecast_store: ForecastEpisodeStore | None,
    operational_evidence_hook: OperationalEvidenceHook | None,
    action_observation_hook: ActionObservationHook | None,
) -> None:
    if (forecast_evaluator is None) != (forecast_closer is None) or (
        forecast_evaluator is None
    ) != (forecast_store is None):
        raise ValueError("forecast runtime bindings MUST be supplied together")
    agents["Heimdall"] = Heimdall(
        rate_threshold=rate_threshold,
        rate_window=rate_window,
        security_high_threshold=security_high_threshold,
        security_window_events=security_window_events,
        alert_rate_per_hour=alert_rate_per_hour,
        action_semantics=action_semantics,
        forecast_evaluator=forecast_evaluator,
        forecast_closer=forecast_closer,
        forecast_store=forecast_store,
        operational_evidence_hook=operational_evidence_hook,
        action_observation_hook=action_observation_hook,
    )


__all__ = ["configure_heimdall"]
