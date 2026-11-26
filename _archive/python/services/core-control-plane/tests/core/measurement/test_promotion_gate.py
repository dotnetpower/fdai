"""Tests for :mod:`fdai.core.measurement.promotion_gate`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.measurement.promotion_gate import (
    InMemoryShadowVerdictSource,
    PromotionGateEvaluator,
    ShadowVerdictRecord,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"

_FIXED_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


def _now_fixed() -> datetime:
    return _FIXED_NOW


def _load_action(name: str):
    catalog = load_action_type_catalog(
        ACTION_TYPES_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )
    return next(at for at in catalog if at.name == name)


def _verdict(
    action_type: str,
    *,
    days_ago: int,
    reviewed: bool = True,
    agreed: bool = True,
    escape: bool = False,
) -> ShadowVerdictRecord:
    return ShadowVerdictRecord(
        action_type_name=action_type,
        observed_at=_FIXED_NOW - timedelta(days=days_ago),
        was_policy_escape=escape,
        operator_reviewed=reviewed,
        operator_agreed=agreed,
    )


def test_gate_is_not_ready_with_zero_verdicts() -> None:
    action = _load_action("ops.publish-change-summary")
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=[])
    assert progress.ready is False
    assert progress.sample_count == 0
    assert progress.accuracy == 0.0
    joined = " ".join(progress.gaps)
    assert "min_samples" in joined
    assert "no_reviewed_verdicts" in joined


def test_gate_is_ready_when_all_criteria_met() -> None:
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    # Spread across the shadow window rather than stacked on one day: the
    # elapsed window is measured between the first and last observation, so
    # samples that all land on the same date span no time at all.
    span = gate.min_shadow_days + 1
    verdicts = [
        _verdict(
            "ops.publish-change-summary",
            days_ago=span - (index * span) // max(gate.min_samples - 1, 1),
        )
        for index in range(gate.min_samples)
    ]
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=verdicts)
    assert progress.ready is True, progress.gaps
    assert progress.gaps == ()
    assert progress.sample_count == gate.min_samples
    assert progress.reviewed_count == gate.min_samples
    assert progress.agreed_count == gate.min_samples
    assert progress.accuracy == 1.0
    assert progress.policy_escapes == 0


def test_policy_escape_blocks_promotion() -> None:
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    verdicts = [
        _verdict("ops.publish-change-summary", days_ago=(gate.min_shadow_days + 1))
        for _ in range(gate.min_samples)
    ]
    verdicts.append(
        _verdict(
            "ops.publish-change-summary",
            days_ago=1,
            escape=True,
        )
    )
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=verdicts)
    assert progress.ready is False
    assert progress.policy_escapes == 1
    assert any("policy_escapes" in g for g in progress.gaps)


def test_accuracy_below_min_blocks_promotion() -> None:
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    verdicts = []
    approved = int(gate.min_samples * 0.5)  # 50% agreement < 0.98 threshold
    for _ in range(approved):
        verdicts.append(_verdict("ops.publish-change-summary", days_ago=(gate.min_shadow_days + 1)))
    for _ in range(gate.min_samples - approved):
        verdicts.append(
            _verdict(
                "ops.publish-change-summary",
                days_ago=(gate.min_shadow_days + 1),
                agreed=False,
            )
        )
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=verdicts)
    assert progress.ready is False
    assert any("accuracy" in g for g in progress.gaps)


def test_insufficient_shadow_days_blocks_promotion() -> None:
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    # Every verdict from the last 24h - well below min_shadow_days.
    verdicts = [_verdict("ops.publish-change-summary", days_ago=1) for _ in range(gate.min_samples)]
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=verdicts)
    assert progress.ready is False
    assert any("min_shadow_days" in g for g in progress.gaps)


def test_evaluate_many_uses_source_and_window() -> None:
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    source = InMemoryShadowVerdictSource(
        verdicts=[
            # Older than the window - MUST be filtered out.
            _verdict("ops.publish-change-summary", days_ago=500),
            # Fresh, reviewed, agreed.
            *[
                _verdict("ops.publish-change-summary", days_ago=(gate.min_shadow_days + 1))
                for _ in range(gate.min_samples)
            ],
        ]
    )
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    (progress,) = evaluator.evaluate_many(
        [action], source=source, window_days=gate.min_shadow_days + 30
    )
    assert progress.sample_count == gate.min_samples  # older record excluded


def test_json_shape_is_client_safe() -> None:
    action = _load_action("ops.publish-change-summary")
    evaluator = PromotionGateEvaluator(now_fn=_now_fixed)
    progress = evaluator.evaluate(action, verdicts=[])
    payload = progress.as_json()

    import json

    reloaded = json.loads(json.dumps(payload))
    assert reloaded["action_type_name"] == "ops.publish-change-summary"
    assert reloaded["ready"] is False
    assert isinstance(reloaded["gaps"], list)


def test_now_fn_must_return_datetime() -> None:
    action = _load_action("ops.publish-change-summary")
    evaluator = PromotionGateEvaluator(now_fn=lambda: "not-a-datetime")
    with pytest.raises(TypeError):
        evaluator.evaluate(action, verdicts=[])


def test_the_clock_alone_cannot_satisfy_the_shadow_window() -> None:
    """Elapsed shadow days used to run from the first observation to now, so an
    ActionType observed on one day and never again kept accruing shadow days
    while nothing was being observed. Evidence from months ago could promote an
    action to autonomous execution today by waiting.
    """
    action = _load_action("ops.publish-change-summary")
    gate = action.promotion_gate
    stacked_long_ago = [
        _verdict("ops.publish-change-summary", days_ago=gate.min_shadow_days * 10)
        for _ in range(gate.min_samples)
    ]

    progress = PromotionGateEvaluator(now_fn=_now_fixed).evaluate(action, verdicts=stacked_long_ago)

    assert progress.shadow_days_elapsed == 0.0
    assert progress.ready is False
    assert any("min_shadow_days" in gap for gap in progress.gaps)
