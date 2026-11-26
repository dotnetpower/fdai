"""Load the repository-governed detector and forecast policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fdai.core.detection.governance_policy_fields import (
    DetectionGovernancePolicyError,
)
from fdai.core.detection.governance_policy_fields import (
    policy_array as _array,
)
from fdai.core.detection.governance_policy_fields import (
    policy_boolean as _boolean,
)
from fdai.core.detection.governance_policy_fields import (
    policy_identifier as _identifier,
)
from fdai.core.detection.governance_policy_fields import (
    policy_integer as _integer,
)
from fdai.core.detection.governance_policy_fields import (
    policy_mapping as _mapping,
)
from fdai.core.detection.governance_policy_fields import (
    policy_member as _member,
)
from fdai.core.detection.governance_policy_fields import (
    policy_ratio as _ratio,
)
from fdai.core.detection.governance_policy_fields import (
    policy_text as _text,
)
from fdai.core.detection.governance_policy_fields import (
    policy_version as _version,
)
from fdai.core.detection.governance_policy_fields import (
    require_exact_keys as _exact_keys,
)
from fdai.core.detection.governance_policy_fields import (
    require_unique as _unique,
)

DETECTION_GOVERNANCE_POLICY_PATH = "config/detection-governance-policy.json"
DETECTION_GOVERNANCE_SCHEMA_VERSION = "1.0.0"
DETECTION_GOVERNANCE_POLICY_ID = "detection-governance"

_PHASES = frozenset({"hour_of_day", "day_of_week", "hour_of_week"})
_CORRELATION_KEYS = frozenset({"correlation_id", "resource_ref"})
_REQUIRED_CORRELATION_KEYS = ("correlation_id", "resource_ref")
_FORECAST_CONFIDENCE_LEVELS = frozenset({"0.80", "0.90", "0.95", "0.99"})
_MIN_T1_SIMILARITY = 0.85


class AnomalyMethod(StrEnum):
    """Supported deterministic anomaly methods."""

    Z_SCORE = "z_score"
    SEASONAL_Z_SCORE = "seasonal_z_score"


class ForecastModelFamily(StrEnum):
    """Supported deterministic forecast model families."""

    LINEAR_TREND = "linear_trend"


@dataclass(frozen=True, slots=True)
class SignalClassPolicy:
    """Method and cold-start floor for one signal class."""

    signal_class: str
    anomaly_method: AnomalyMethod
    min_baseline_samples: int
    seasonal_phase: str | None = None


@dataclass(frozen=True, slots=True)
class ForecastTargetPolicy:
    """Model family and default evaluation envelope for one target kind."""

    target_kind: str
    model_family: ForecastModelFamily
    horizon_seconds: int
    min_samples: int
    min_r_squared: float
    confidence_level: str


@dataclass(frozen=True, slots=True)
class CorrelationPolicy:
    """Exact-key and bounded fuzzy-correlation policy."""

    exact_keys: tuple[str, ...]
    default_window_seconds: int
    trace_window_seconds: int
    t1_similarity_floor: float
    t1_min_shared_evidence_fields: int


@dataclass(frozen=True, slots=True)
class ForecastPromotionPolicy:
    """Pre-registered backtest cadence and promotion thresholds."""

    cadence_seconds: int
    min_scorable_episodes: int
    min_shadow_days: int
    min_precision: float
    min_recall: float
    min_interval_coverage: float
    max_interval_coverage: float
    min_median_lead_seconds: int
    max_abstention_rate: float
    max_policy_escapes: int


@dataclass(frozen=True, slots=True)
class ChangeWindowPolicy:
    """Fail-closed treatment of findings during an active change window."""

    behavior: str
    require_exact_scope: bool
    require_complete_evidence: bool


@dataclass(frozen=True, slots=True)
class DetectionGovernancePolicy:
    """One immutable repository policy revision."""

    policy_id: str
    policy_version: str
    signal_classes: tuple[SignalClassPolicy, ...]
    forecast_targets: tuple[ForecastTargetPolicy, ...]
    correlation: CorrelationPolicy
    forecast_promotion: ForecastPromotionPolicy
    change_window: ChangeWindowPolicy
    content_digest: str

    def signal_class(self, value: str) -> SignalClassPolicy:
        """Return one configured signal class or fail explicitly."""

        for item in self.signal_classes:
            if item.signal_class == value:
                return item
        raise DetectionGovernancePolicyError(f"unknown detection signal class {value!r}")

    def forecast_target(self, value: str) -> ForecastTargetPolicy:
        """Return one configured forecast target kind or fail explicitly."""

        for item in self.forecast_targets:
            if item.target_kind == value:
                return item
        raise DetectionGovernancePolicyError(f"unknown forecast target kind {value!r}")


def load_detection_governance_policy(path: Path) -> DetectionGovernancePolicy:
    """Load and strictly validate the governed detector policy."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DetectionGovernancePolicyError(
            f"unreadable detection governance policy: {type(exc).__name__}"
        ) from exc
    root = _mapping(raw, "policy")
    _exact_keys(
        root,
        "policy",
        {
            "schema_version",
            "policy_id",
            "policy_version",
            "signal_classes",
            "forecast_targets",
            "correlation",
            "forecast_promotion",
            "change_window",
        },
    )
    if root["schema_version"] != DETECTION_GOVERNANCE_SCHEMA_VERSION:
        raise DetectionGovernancePolicyError(
            f"detection governance schema MUST be {DETECTION_GOVERNANCE_SCHEMA_VERSION}"
        )

    signal_classes = tuple(
        _signal_class(item, index=index)
        for index, item in enumerate(_array(root["signal_classes"], "signal_classes"))
    )
    forecast_targets = tuple(
        _forecast_target(item, index=index)
        for index, item in enumerate(_array(root["forecast_targets"], "forecast_targets"))
    )
    _unique((item.signal_class for item in signal_classes), label="signal class")
    _unique((item.target_kind for item in forecast_targets), label="forecast target")
    canonical = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    policy_id = _identifier(root["policy_id"], "policy_id")
    if policy_id != DETECTION_GOVERNANCE_POLICY_ID:
        raise DetectionGovernancePolicyError(
            f"detection governance policy_id MUST be {DETECTION_GOVERNANCE_POLICY_ID!r}"
        )
    return DetectionGovernancePolicy(
        policy_id=policy_id,
        policy_version=_version(root["policy_version"], "policy_version"),
        signal_classes=signal_classes,
        forecast_targets=forecast_targets,
        correlation=_correlation(root["correlation"]),
        forecast_promotion=_promotion(root["forecast_promotion"]),
        change_window=_change_window(root["change_window"]),
        content_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _signal_class(value: object, *, index: int) -> SignalClassPolicy:
    raw = _mapping(value, f"signal_classes[{index}]")
    _exact_keys(
        raw,
        f"signal_classes[{index}]",
        {"signal_class", "anomaly_method", "min_baseline_samples", "seasonal_phase"},
    )
    try:
        method = AnomalyMethod(_text(raw["anomaly_method"], "anomaly_method"))
    except ValueError as exc:
        raise DetectionGovernancePolicyError("unsupported anomaly method") from exc
    phase_raw = raw["seasonal_phase"]
    phase = _member(phase_raw, "seasonal_phase", allowed=_PHASES) if phase_raw is not None else None
    if method is AnomalyMethod.SEASONAL_Z_SCORE and phase is None:
        raise DetectionGovernancePolicyError("seasonal anomaly method requires seasonal_phase")
    if method is AnomalyMethod.Z_SCORE and phase is not None:
        raise DetectionGovernancePolicyError("non-seasonal anomaly method forbids seasonal_phase")
    minimum_samples = 10 if method is AnomalyMethod.SEASONAL_Z_SCORE else 30
    return SignalClassPolicy(
        signal_class=_identifier(raw["signal_class"], "signal_class"),
        anomaly_method=method,
        min_baseline_samples=_integer(
            raw["min_baseline_samples"],
            "min_baseline_samples",
            minimum=minimum_samples,
            maximum=10_000,
        ),
        seasonal_phase=phase,
    )


def _forecast_target(value: object, *, index: int) -> ForecastTargetPolicy:
    raw = _mapping(value, f"forecast_targets[{index}]")
    _exact_keys(
        raw,
        f"forecast_targets[{index}]",
        {
            "target_kind",
            "model_family",
            "horizon_seconds",
            "min_samples",
            "min_r_squared",
            "confidence_level",
        },
    )
    try:
        family = ForecastModelFamily(_text(raw["model_family"], "model_family"))
    except ValueError as exc:
        raise DetectionGovernancePolicyError("unsupported forecast model family") from exc
    return ForecastTargetPolicy(
        target_kind=_identifier(raw["target_kind"], "target_kind"),
        model_family=family,
        horizon_seconds=_integer(
            raw["horizon_seconds"], "horizon_seconds", minimum=60, maximum=31_536_000
        ),
        min_samples=_integer(raw["min_samples"], "min_samples", minimum=5, maximum=10_000),
        min_r_squared=_ratio(raw["min_r_squared"], "min_r_squared", minimum=0.5),
        confidence_level=_member(
            raw["confidence_level"],
            "confidence_level",
            allowed=_FORECAST_CONFIDENCE_LEVELS,
        ),
    )


def _correlation(value: object) -> CorrelationPolicy:
    raw = _mapping(value, "correlation")
    _exact_keys(
        raw,
        "correlation",
        {
            "exact_keys",
            "default_window_seconds",
            "trace_window_seconds",
            "t1_similarity_floor",
            "t1_min_shared_evidence_fields",
        },
    )
    exact_keys = tuple(_text(item, "exact_key") for item in _array(raw["exact_keys"], "exact_keys"))
    if not exact_keys or len(exact_keys) != len(set(exact_keys)):
        raise DetectionGovernancePolicyError("correlation exact_keys MUST be non-empty and unique")
    if any(item not in _CORRELATION_KEYS for item in exact_keys):
        raise DetectionGovernancePolicyError("correlation exact_keys contain an unsupported key")
    if exact_keys != _REQUIRED_CORRELATION_KEYS:
        raise DetectionGovernancePolicyError(
            "correlation exact_keys MUST preserve correlation_id then resource_ref"
        )
    return CorrelationPolicy(
        exact_keys=exact_keys,
        default_window_seconds=_integer(
            raw["default_window_seconds"], "default_window_seconds", minimum=10, maximum=86_400
        ),
        trace_window_seconds=_integer(
            raw["trace_window_seconds"], "trace_window_seconds", minimum=10, maximum=86_400
        ),
        t1_similarity_floor=_ratio(
            raw["t1_similarity_floor"],
            "t1_similarity_floor",
            minimum=_MIN_T1_SIMILARITY,
        ),
        t1_min_shared_evidence_fields=_integer(
            raw["t1_min_shared_evidence_fields"],
            "t1_min_shared_evidence_fields",
            minimum=2,
            maximum=16,
        ),
    )


def _promotion(value: object) -> ForecastPromotionPolicy:
    raw = _mapping(value, "forecast_promotion")
    _exact_keys(
        raw,
        "forecast_promotion",
        {
            "cadence_seconds",
            "min_scorable_episodes",
            "min_shadow_days",
            "min_precision",
            "min_recall",
            "min_interval_coverage",
            "max_interval_coverage",
            "min_median_lead_seconds",
            "max_abstention_rate",
            "max_policy_escapes",
        },
    )
    minimum_coverage = _ratio(raw["min_interval_coverage"], "min_interval_coverage", minimum=0.85)
    maximum_coverage = _ratio(raw["max_interval_coverage"], "max_interval_coverage", maximum=0.95)
    if minimum_coverage > maximum_coverage:
        raise DetectionGovernancePolicyError("forecast interval coverage bounds are reversed")
    cadence_seconds = _integer(
        raw["cadence_seconds"], "cadence_seconds", minimum=3_600, maximum=2_592_000
    )
    if cadence_seconds != 604_800:
        raise DetectionGovernancePolicyError("forecast cadence_seconds MUST remain weekly")
    return ForecastPromotionPolicy(
        cadence_seconds=cadence_seconds,
        min_scorable_episodes=_integer(
            raw["min_scorable_episodes"], "min_scorable_episodes", minimum=30, maximum=10_000
        ),
        min_shadow_days=_integer(
            raw["min_shadow_days"], "min_shadow_days", minimum=14, maximum=365
        ),
        min_precision=_ratio(raw["min_precision"], "min_precision", minimum=0.8),
        min_recall=_ratio(raw["min_recall"], "min_recall", minimum=0.8),
        min_interval_coverage=minimum_coverage,
        max_interval_coverage=maximum_coverage,
        min_median_lead_seconds=_integer(
            raw["min_median_lead_seconds"],
            "min_median_lead_seconds",
            minimum=300,
            maximum=31_536_000,
        ),
        max_abstention_rate=_ratio(raw["max_abstention_rate"], "max_abstention_rate", maximum=0.2),
        max_policy_escapes=_integer(
            raw["max_policy_escapes"], "max_policy_escapes", minimum=0, maximum=0
        ),
    )


def _change_window(value: object) -> ChangeWindowPolicy:
    raw = _mapping(value, "change_window")
    _exact_keys(
        raw,
        "change_window",
        {"behavior", "require_exact_scope", "require_complete_evidence"},
    )
    behavior = _text(raw["behavior"], "change_window.behavior")
    if behavior != "annotate_and_hold_incident":
        raise DetectionGovernancePolicyError("change-window behavior MUST hold incident promotion")
    require_exact_scope = _boolean(raw["require_exact_scope"], "require_exact_scope")
    require_complete_evidence = _boolean(
        raw["require_complete_evidence"], "require_complete_evidence"
    )
    if not require_exact_scope or not require_complete_evidence:
        raise DetectionGovernancePolicyError(
            "change-window suppression requires exact scope and complete evidence"
        )
    return ChangeWindowPolicy(
        behavior=behavior,
        require_exact_scope=require_exact_scope,
        require_complete_evidence=require_complete_evidence,
    )


__all__ = [
    "DETECTION_GOVERNANCE_POLICY_PATH",
    "DETECTION_GOVERNANCE_POLICY_ID",
    "AnomalyMethod",
    "ChangeWindowPolicy",
    "CorrelationPolicy",
    "DetectionGovernancePolicy",
    "DetectionGovernancePolicyError",
    "ForecastModelFamily",
    "ForecastPromotionPolicy",
    "ForecastTargetPolicy",
    "SignalClassPolicy",
    "load_detection_governance_policy",
]
