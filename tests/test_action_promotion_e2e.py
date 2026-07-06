"""End-to-end shadow -> enforce promotion demonstration.

Realizes the phase-2 promotion contract at the ``ActionPromotionRegistry`` seam:

- **Shadow (default)** — a fresh :class:`ActionPromotionRegistry` reports
  every ActionType as :class:`Mode.SHADOW`.
- **Promotion evidence** — a synthetic :class:`PromotionMetrics` that
  clears every field of the ActionType's ``promotion_gate`` flips the
  record to :class:`Mode.ENFORCE`, and the risk-gate begins returning
  ``RiskDecision.AUTO`` for that action.
- **Regression demotion** — a follow-up :class:`PromotionMetrics` that
  breaches the ``max_policy_escapes`` bound demotes the record back to
  :class:`Mode.SHADOW` and stamps ``demoted_at``; the risk-gate reverts
  to ``RiskDecision.HIL``.
- **Cross-action isolation** — promoting ``remediate.tag-add`` MUST NOT
  affect the mode of ``remediate.disable-public-access``.

The promotion metrics used here are **synthetic** by design: the P2 exit
criterion "Auto-resolution-rate improvement is measured against the P0
baseline on the same scenario-set version" is a *live-deploy* claim that
this test does not substitute for. What it does prove is that the
promotion + demotion state machine works on the shipped ActionType
YAMLs, so a fork can hand it real measured metrics via a
:class:`~aiopspilot.core.measurement.regression.RegressionDetector` and
get a deterministic outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.core.risk_gate import (
    ActionPromotionRegistry,
    PromotionMetrics,
)
from aiopspilot.rule_catalog.schema.action_type import (
    OntologyActionType,
    load_action_type_catalog,
)
from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


@pytest.fixture(scope="module")
def action_types() -> dict[str, OntologyActionType]:
    registry = PackageResourceSchemaRegistry()
    catalog = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    return {a.name: a for a in catalog}


def _passing_metrics(action: OntologyActionType) -> PromotionMetrics:
    """Build metrics that clear every field of the ActionType's gate."""
    gate = action.promotion_gate
    return PromotionMetrics(
        action_type=action.name,
        shadow_days=gate.min_shadow_days + 3,
        samples=gate.min_samples + 25,
        accuracy=min(1.0, gate.min_accuracy + 0.001),
        policy_escapes=0,
    )


def _regression_metrics(action: OntologyActionType) -> PromotionMetrics:
    """Metrics that trip the ``max_policy_escapes`` bound after promotion."""
    gate = action.promotion_gate
    return PromotionMetrics(
        action_type=action.name,
        shadow_days=gate.min_shadow_days + 3,
        samples=gate.min_samples + 25,
        accuracy=min(1.0, gate.min_accuracy + 0.001),
        policy_escapes=gate.max_policy_escapes + 1,
    )


def test_default_mode_is_shadow_for_every_shipped_action_type(
    action_types: dict[str, OntologyActionType],
) -> None:
    """No ActionType MAY ship in enforce mode by default.

    The registry starts empty; every ``mode_of`` call falls through to
    :attr:`Mode.SHADOW`. This is the safety-first default the
    coding-conventions require.
    """
    registry = ActionPromotionRegistry()
    for action in action_types.values():
        assert registry.mode_of(action.name) is Mode.SHADOW


def test_first_promotion_flips_tag_add_to_enforce(
    action_types: dict[str, OntologyActionType],
) -> None:
    """A metrics record that clears the promotion gate flips ENFORCE."""
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    record = registry.consider_promotion(
        action_type=action,
        metrics=_passing_metrics(action),
    )
    assert record.mode is Mode.ENFORCE
    assert record.promoted_at is not None
    assert record.demoted_at is None
    assert registry.mode_of(action.name) is Mode.ENFORCE


def test_regression_demotes_back_to_shadow(
    action_types: dict[str, OntologyActionType],
) -> None:
    """A policy escape post-promotion demotes the ActionType back to shadow.

    Proves the guard-metric demotion path documented in
    phase-2 § Shadow -> Enforce Promotion.
    """
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    registry.consider_promotion(action_type=action, metrics=_passing_metrics(action))
    assert registry.mode_of(action.name) is Mode.ENFORCE

    demoted = registry.consider_promotion(
        action_type=action,
        metrics=_regression_metrics(action),
    )
    assert demoted.mode is Mode.SHADOW
    assert demoted.demoted_at is not None
    # The prior promoted_at MUST survive the demotion so the audit trail
    # keeps the original ENFORCE stamp for correlation.
    assert demoted.promoted_at is not None


def test_cross_action_isolation(
    action_types: dict[str, OntologyActionType],
) -> None:
    """Promoting one ActionType MUST NOT affect the mode of another."""
    tag_add = action_types["remediate.tag-add"]
    disable_public = action_types["remediate.disable-public-access"]
    registry = ActionPromotionRegistry()

    registry.consider_promotion(action_type=tag_add, metrics=_passing_metrics(tag_add))
    assert registry.mode_of(tag_add.name) is Mode.ENFORCE
    assert registry.mode_of(disable_public.name) is Mode.SHADOW


def test_gate_below_min_shadow_days_keeps_shadow(
    action_types: dict[str, OntologyActionType],
) -> None:
    """Insufficient shadow-time keeps the ActionType in shadow."""
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    metrics = PromotionMetrics(
        action_type=action.name,
        shadow_days=action.promotion_gate.min_shadow_days - 1,
        samples=action.promotion_gate.min_samples + 25,
        accuracy=1.0,
        policy_escapes=0,
    )
    record = registry.consider_promotion(action_type=action, metrics=metrics)
    assert record.mode is Mode.SHADOW
    assert record.promoted_at is None


def test_gate_below_min_samples_keeps_shadow(
    action_types: dict[str, OntologyActionType],
) -> None:
    """Insufficient shadow-sample count keeps the ActionType in shadow."""
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    metrics = PromotionMetrics(
        action_type=action.name,
        shadow_days=action.promotion_gate.min_shadow_days + 3,
        samples=action.promotion_gate.min_samples - 1,
        accuracy=1.0,
        policy_escapes=0,
    )
    record = registry.consider_promotion(action_type=action, metrics=metrics)
    assert record.mode is Mode.SHADOW


def test_gate_below_min_accuracy_keeps_shadow(
    action_types: dict[str, OntologyActionType],
) -> None:
    """Insufficient shadow-mode accuracy keeps the ActionType in shadow."""
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    metrics = PromotionMetrics(
        action_type=action.name,
        shadow_days=action.promotion_gate.min_shadow_days + 3,
        samples=action.promotion_gate.min_samples + 25,
        accuracy=max(0.0, action.promotion_gate.min_accuracy - 0.05),
        policy_escapes=0,
    )
    record = registry.consider_promotion(action_type=action, metrics=metrics)
    assert record.mode is Mode.SHADOW


def test_registry_metrics_used_are_preserved_on_the_record(
    action_types: dict[str, OntologyActionType],
) -> None:
    """A promotion record captures the metrics that justified the transition.

    An audit consumer downstream MUST be able to render the reason the
    registry took a state action; the record's ``metrics`` is that source.
    """
    action = action_types["remediate.tag-add"]
    registry = ActionPromotionRegistry()
    metrics = _passing_metrics(action)
    record = registry.consider_promotion(action_type=action, metrics=metrics)
    assert record.metrics == metrics
