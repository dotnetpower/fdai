from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import fdai.runtime.forecast_learning as forecast_runtime
import pytest
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.detection.governance_policy import load_detection_governance_policy
from fdai.runtime.forecast_learning import (
    build_forecast_learning_runtime,
    parse_forecast_targets,
)
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from tests.core.detection.test_forecast_episode import T0, _episode

_REPO_ROOT = Path(__file__).resolve().parents[4]
_POLICY_PATH = _REPO_ROOT / "config" / "detection-governance-policy.json"


def _target(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "target_kind": "capacity",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "scorer_version": "1.0.0",
        "access_scope_digest": "a" * 64,
        "resource_ref": "resource-1",
        "metric": "capacity_percent",
        "threshold": 90.0,
        "horizon_seconds": 86_400,
        "lookback_seconds": 604_800,
        "telemetry_grace_seconds": 300,
        "min_samples": 5,
        "min_r_squared": 0.5,
        "confidence_level": "0.90",
    }
    value.update(overrides)
    return value


def test_forecast_targets_must_match_the_governed_policy() -> None:
    policy = load_detection_governance_policy(_POLICY_PATH)

    targets = parse_forecast_targets(
        json.dumps([_target()]),
        governance_policy=policy,
    )

    assert len(targets) == 1
    assert targets[0].horizon_seconds == 86_400


def test_forecast_history_configuration_is_bounded_complete_and_unambiguous():
    build = forecast_runtime.build_forecast_history_collector
    assert build(dsn=None, bindings_json=None) is None
    assert build(dsn=None, bindings_json=" ") is None
    with pytest.raises(ValueError, match="duplicate field"):
        build(dsn="postgresql://example", bindings_json='[{"kind":"actions","kind":"changes"}]')
    values = [
        dict(
            kind=kind,
            access_scope_digest="a" * 64,
            target_ref="resource-example",
            state_type=kind,
            to_states=["inactive", "active"],
            active_states=["active"] if kind in {"resource_lifecycle", "excluded_windows"} else [],
            source_identity="source-example",
            source_revision="revision-example",
            freshness_seconds=300,
        )
        for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows")
    ]
    assert build(dsn="postgresql://example", bindings_json=json.dumps(values)) is not None
    for invalid in ([], {}, values[:-1], values + [values[0]], [values[0]] * 257):
        with pytest.raises(ValueError):
            build(dsn="postgresql://example", bindings_json=json.dumps(invalid))
    with pytest.raises(ValueError):
        build(dsn=None, bindings_json=json.dumps(values))
    with pytest.raises(ValueError, match="byte limit"):
        build(dsn="postgresql://example", bindings_json="[" + " " * 262_144 + "]")


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"target_kind": None}, "target_kind"),
        ({"horizon_seconds": 3_600}, "horizon_seconds"),
        ({"min_samples": 4}, "min_samples"),
        ({"min_r_squared": 0.49}, "min_r_squared"),
        ({"confidence_level": "0.95"}, "confidence_level"),
    ),
)
def test_forecast_targets_cannot_weaken_or_bypass_policy(
    overrides: dict[str, object],
    message: str,
) -> None:
    policy = load_detection_governance_policy(_POLICY_PATH)

    with pytest.raises(ValueError, match=message):
        parse_forecast_targets(
            json.dumps([_target(**overrides)]),
            governance_policy=policy,
        )


def test_startup_loads_policy_even_when_forecast_targets_are_disabled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unreadable detection governance policy"):
        build_forecast_learning_runtime(
            dsn=None,
            targets_json=None,
            metric_provider=StaticMetricProvider([]),
            governance_policy_path=tmp_path / "missing.json",
        )


async def test_runtime_without_context_binding_closes_unscorable_not_false_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryForecastEpisodeStore()
    monkeypatch.setattr(forecast_runtime, "PostgresForecastEpisodeStore", lambda **_kwargs: store)
    episode = _episode(horizon_ended_at=T0 + timedelta(days=1))
    await store.record(episode)
    points = tuple(
        MetricPoint(
            metric_name=episode.metric,
            at=T0 + timedelta(minutes=5 * index),
            value=70.0,
            labels={"resource_id": episode.target_ref},
        )
        for index in range(289)
    )
    runtime = build_forecast_learning_runtime(
        dsn="postgresql://example",
        targets_json=json.dumps([_target()]),
        metric_provider=StaticMetricProvider(points),
    )
    assert runtime is not None
    assert await runtime.closer.close_due(now=episode.closure_due_at) == 1
    payload = next(iter(store.outbox.values())).payload
    assert payload["schema_version"] == "1.1.0"
    assert payload["label"] == "unscorable"
    assert payload["telemetry_completeness"] == "complete"
    assert payload["scoring_exclusions"] == ["intervention_history_unavailable"]


def test_default_policy_path_is_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert (
        build_forecast_learning_runtime(
            dsn=None,
            targets_json=None,
            metric_provider=StaticMetricProvider([]),
        )
        is None
    )
