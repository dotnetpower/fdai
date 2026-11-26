from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.core.detection.governance_policy import (
    AnomalyMethod,
    DetectionGovernancePolicyError,
    ForecastModelFamily,
    load_detection_governance_policy,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POLICY_PATH = _REPO_ROOT / "config" / "detection-governance-policy.json"


def _policy() -> dict[str, object]:
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_repository_policy_resolves_every_open_design_decision() -> None:
    policy = load_detection_governance_policy(_POLICY_PATH)

    assert policy.signal_class("reliability.stationary").anomaly_method is AnomalyMethod.Z_SCORE
    assert (
        policy.signal_class("reliability.seasonal").anomaly_method is AnomalyMethod.SEASONAL_Z_SCORE
    )
    assert policy.forecast_target("capacity").model_family is ForecastModelFamily.LINEAR_TREND
    assert policy.forecast_target("expiry").horizon_seconds == 2_592_000
    assert policy.correlation.exact_keys == ("correlation_id", "resource_ref")
    assert policy.correlation.t1_similarity_floor == 0.85
    assert policy.forecast_promotion.min_scorable_episodes == 30
    assert policy.forecast_promotion.max_policy_escapes == 0
    assert policy.change_window.behavior == "annotate_and_hold_incident"
    assert len(policy.content_digest) == 64


def test_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    raw = _policy()
    raw["unexpected"] = True

    with pytest.raises(DetectionGovernancePolicyError, match="fields"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_a_non_semantic_policy_version(tmp_path: Path) -> None:
    raw = _policy()
    raw["policy_version"] = "latest"

    with pytest.raises(DetectionGovernancePolicyError, match="semantic version"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_a_relabelled_policy_identity(tmp_path: Path) -> None:
    raw = _policy()
    raw["policy_id"] = "replacement-policy"

    with pytest.raises(DetectionGovernancePolicyError, match="policy_id"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_duplicate_signal_classes(tmp_path: Path) -> None:
    raw = _policy()
    signal_classes = raw["signal_classes"]
    assert isinstance(signal_classes, list)
    signal_classes.append(dict(signal_classes[0]))

    with pytest.raises(DetectionGovernancePolicyError, match="signal class"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_bounds_signal_class_count_before_loading_entries(tmp_path: Path) -> None:
    raw = _policy()
    signal_classes = raw["signal_classes"]
    assert isinstance(signal_classes, list)
    template = dict(signal_classes[-1])
    raw["signal_classes"] = [
        {**template, "signal_class": f"reliability.class-{index}"} for index in range(65)
    ]

    with pytest.raises(DetectionGovernancePolicyError, match="at most 64"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_seasonal_method_without_phase(tmp_path: Path) -> None:
    raw = _policy()
    signal_classes = raw["signal_classes"]
    assert isinstance(signal_classes, list)
    signal_classes[0]["seasonal_phase"] = None

    with pytest.raises(DetectionGovernancePolicyError, match="requires seasonal_phase"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_reports_a_malformed_seasonal_phase_as_a_policy_error(tmp_path: Path) -> None:
    raw = _policy()
    signal_classes = raw["signal_classes"]
    assert isinstance(signal_classes, list)
    signal_classes[0]["seasonal_phase"] = []

    with pytest.raises(DetectionGovernancePolicyError, match="seasonal_phase"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize(("index", "samples"), ((0, 9), (2, 29)))
def test_policy_rejects_weakened_anomaly_cold_start_floors(
    tmp_path: Path,
    index: int,
    samples: int,
) -> None:
    raw = _policy()
    signal_classes = raw["signal_classes"]
    assert isinstance(signal_classes, list)
    signal_classes[index]["min_baseline_samples"] = samples

    with pytest.raises(DetectionGovernancePolicyError, match="min_baseline_samples"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize(("metric", "value"), (("min_samples", 4), ("min_r_squared", 0.49)))
def test_policy_rejects_weakened_forecast_fit_floors(
    tmp_path: Path,
    metric: str,
    value: float,
) -> None:
    raw = _policy()
    targets = raw["forecast_targets"]
    assert isinstance(targets, list)
    targets[0][metric] = value

    with pytest.raises(DetectionGovernancePolicyError, match=metric):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_a_narrowed_exact_correlation_key_set(tmp_path: Path) -> None:
    raw = _policy()
    correlation = raw["correlation"]
    assert isinstance(correlation, dict)
    correlation["exact_keys"] = ["correlation_id"]

    with pytest.raises(DetectionGovernancePolicyError, match="preserve"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_a_weakened_t1_similarity_floor(tmp_path: Path) -> None:
    raw = _policy()
    correlation = raw["correlation"]
    assert isinstance(correlation, dict)
    correlation["t1_similarity_floor"] = 0.5

    with pytest.raises(DetectionGovernancePolicyError, match="t1_similarity_floor"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_single_field_t1_evidence(tmp_path: Path) -> None:
    raw = _policy()
    correlation = raw["correlation"]
    assert isinstance(correlation, dict)
    correlation["t1_min_shared_evidence_fields"] = 1

    with pytest.raises(DetectionGovernancePolicyError, match="shared_evidence"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_reversed_interval_coverage(tmp_path: Path) -> None:
    raw = _policy()
    promotion = raw["forecast_promotion"]
    assert isinstance(promotion, dict)
    promotion["min_interval_coverage"] = 0.99

    with pytest.raises(DetectionGovernancePolicyError, match="reversed"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize(
    ("metric", "value"),
    (("min_interval_coverage", 0.84), ("max_interval_coverage", 0.96)),
)
def test_policy_rejects_weakened_interval_coverage_bounds(
    tmp_path: Path,
    metric: str,
    value: float,
) -> None:
    raw = _policy()
    promotion = raw["forecast_promotion"]
    assert isinstance(promotion, dict)
    promotion[metric] = value

    with pytest.raises(DetectionGovernancePolicyError, match=metric):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize("metric", ("min_precision", "min_recall"))
def test_policy_rejects_weakened_forecast_accuracy_floors(tmp_path: Path, metric: str) -> None:
    raw = _policy()
    promotion = raw["forecast_promotion"]
    assert isinstance(promotion, dict)
    promotion[metric] = 0.79

    with pytest.raises(DetectionGovernancePolicyError, match=metric):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize(
    ("metric", "value"),
    (("min_median_lead_seconds", 299), ("max_abstention_rate", 0.21)),
)
def test_policy_rejects_weakened_lead_time_or_abstention_bounds(
    tmp_path: Path,
    metric: str,
    value: float,
) -> None:
    raw = _policy()
    promotion = raw["forecast_promotion"]
    assert isinstance(promotion, dict)
    promotion[metric] = value

    with pytest.raises(DetectionGovernancePolicyError, match=metric):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize(
    ("metric", "value"),
    (("cadence_seconds", 86_400), ("min_shadow_days", 13)),
)
def test_policy_rejects_weakened_backtest_observation_period(
    tmp_path: Path,
    metric: str,
    value: int,
) -> None:
    raw = _policy()
    promotion = raw["forecast_promotion"]
    assert isinstance(promotion, dict)
    promotion[metric] = value

    with pytest.raises(DetectionGovernancePolicyError, match=metric):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


def test_policy_rejects_confidence_levels_the_forecast_band_cannot_evaluate(
    tmp_path: Path,
) -> None:
    raw = _policy()
    targets = raw["forecast_targets"]
    assert isinstance(targets, list)
    targets[0]["confidence_level"] = "0.85"

    with pytest.raises(DetectionGovernancePolicyError, match="confidence_level"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))


@pytest.mark.parametrize("field", ("require_exact_scope", "require_complete_evidence"))
def test_policy_rejects_weakened_change_window_evidence_guards(
    tmp_path: Path,
    field: str,
) -> None:
    raw = _policy()
    change_window = raw["change_window"]
    assert isinstance(change_window, dict)
    change_window[field] = False

    with pytest.raises(DetectionGovernancePolicyError, match="exact scope"):
        load_detection_governance_policy(_write_policy(tmp_path, raw))
