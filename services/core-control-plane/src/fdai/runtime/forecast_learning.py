"""Production composition for durable forecast evaluation and closure."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_context import ContextualForecastObservationProvider
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator, ForecastTargetSpec
from fdai.core.detection.forecast_history import (
    ForecastHistoryBinding,
    StateTransitionForecastHistoryCollector,
)
from fdai.core.detection.forecast_observation import MetricForecastObservationProvider
from fdai.core.detection.governance_policy import (
    DETECTION_GOVERNANCE_POLICY_PATH,
    DetectionGovernancePolicy,
    ForecastModelFamily,
    load_detection_governance_policy,
)
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
)
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.forecast_context import ForecastContextProvider
from fdai.shared.providers.metric import MetricProvider


@dataclass(frozen=True, slots=True)
class ForecastLearningRuntime:
    store: PostgresForecastEpisodeStore
    evaluator: ForecastEpisodeEvaluator
    closer: ForecastClosureCoordinator


def build_forecast_learning_runtime(
    *,
    dsn: str | None,
    targets_json: str | None,
    metric_provider: MetricProvider,
    governance_policy_path: Path | None = None,
    context_provider: ForecastContextProvider | None = None,
    context_admission: DecisionEvidenceAdmissionProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ForecastLearningRuntime | None:
    policy_path = governance_policy_path or repo_asset_root() / DETECTION_GOVERNANCE_POLICY_PATH
    governance_policy = load_detection_governance_policy(policy_path)
    targets = parse_forecast_targets(targets_json, governance_policy=governance_policy)
    if not targets:
        return None
    if dsn is None or not dsn.strip():
        raise RuntimeError("forecast learning targets require FDAI_STATE_STORE_DSN")
    store = PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(dsn=dsn.strip()))
    return ForecastLearningRuntime(
        store=store,
        evaluator=ForecastEpisodeEvaluator(
            source=MetricSeriesSource(metric_provider),
            store=store,
            targets=targets,
        ),
        closer=ForecastClosureCoordinator(
            store=store,
            observations=ContextualForecastObservationProvider(
                observations=MetricForecastObservationProvider(metric_provider),
                context=context_provider,
                admission_provider=context_admission,
                clock=clock,
            ),
        ),
    )


def build_forecast_history_collector(
    *, dsn: str | None, bindings_json: str | None
) -> StateTransitionForecastHistoryCollector | None:
    """Bind reviewed exact source mappings to the existing PostgreSQL state-transition store."""
    if bindings_json is None or not bindings_json.strip():
        return None
    if len(bindings_json.encode()) > 262_144:
        raise ValueError("forecast history source mappings exceed the byte limit")
    raw = json.loads(bindings_json, object_pairs_hook=_unique_history_fields)
    if not isinstance(raw, list) or not 1 <= len(raw) <= 256 or not dsn or not dsn.strip():
        raise ValueError("forecast history collection requires bounded mappings and a database")
    return StateTransitionForecastHistoryCollector(
        store=PostgresStateTransitionStore(
            config=PostgresStateTransitionStoreConfig(
                dsn=dsn, statement_timeout_ms=3000, connect_timeout_s=3
            )
        ),
        bindings=tuple(ForecastHistoryBinding.model_validate(item) for item in raw),
    )


def _unique_history_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("forecast history source mappings contain a duplicate field")
        result[name] = value
    return result


def parse_forecast_targets(
    raw: str | None,
    *,
    governance_policy: DetectionGovernancePolicy,
) -> tuple[ForecastTargetSpec, ...]:
    if raw is None or not raw.strip():
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_FORECAST_TARGETS_JSON MUST be valid JSON") from exc
    if not isinstance(decoded, list):
        raise ValueError("FDAI_FORECAST_TARGETS_JSON MUST be an array")
    targets: list[ForecastTargetSpec] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ValueError(f"FDAI_FORECAST_TARGETS_JSON[{index}] MUST be an object")
        target = dict(item)
        target_kind = target.pop("target_kind", None)
        if not isinstance(target_kind, str):
            raise ValueError(f"FDAI_FORECAST_TARGETS_JSON[{index}].target_kind MUST be configured")
        target_policy = governance_policy.forecast_target(target_kind)
        if target_policy.model_family is not ForecastModelFamily.LINEAR_TREND:
            raise ValueError(
                f"FDAI_FORECAST_TARGETS_JSON[{index}] requests an unsupported model family"
            )
        try:
            spec = ForecastTargetSpec(**target)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"FDAI_FORECAST_TARGETS_JSON[{index}] is invalid") from exc
        if spec.horizon_seconds != target_policy.horizon_seconds:
            raise ValueError(
                f"FDAI_FORECAST_TARGETS_JSON[{index}].horizon_seconds "
                "does not match governed policy"
            )
        if spec.min_samples < target_policy.min_samples:
            raise ValueError(
                f"FDAI_FORECAST_TARGETS_JSON[{index}].min_samples weakens governed policy"
            )
        if spec.min_r_squared < target_policy.min_r_squared:
            raise ValueError(
                f"FDAI_FORECAST_TARGETS_JSON[{index}].min_r_squared weakens governed policy"
            )
        if spec.confidence_level != target_policy.confidence_level:
            raise ValueError(
                f"FDAI_FORECAST_TARGETS_JSON[{index}].confidence_level "
                "does not match governed policy"
            )
        targets.append(spec)
    identities = {
        (target.access_scope_digest, target.detector_id, target.resource_ref, target.metric)
        for target in targets
    }
    if len(identities) != len(targets):
        raise ValueError("FDAI_FORECAST_TARGETS_JSON contains duplicate target identities")
    return tuple(targets)


__all__ = [
    "ForecastLearningRuntime",
    "build_forecast_learning_runtime",
    "parse_forecast_targets",
]
