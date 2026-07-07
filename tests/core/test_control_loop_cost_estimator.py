"""Wave W2.5b - ControlLoop._resolve_cost_override integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from aiopspilot.core.control_loop import ControlLoop
from aiopspilot.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Rule,
)
from aiopspilot.shared.providers.cost_estimator import (
    CostConfidence,
    CostEstimate,
    CostEstimatorError,
)
from aiopspilot.shared.providers.testing.cost_estimator import InMemoryCostEstimator


def _at() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.scale-out",
        version="1.0.0",
        operation=Operation.SCALE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        irreversible=True,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
    )


def _make_rule(*, cost_impact_monthly_usd: float | None) -> Rule:
    """Build a minimal Rule with an optional static cost figure."""

    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "example.rule.cost",
        "version": "1.0.0",
        "source": "custom",
        "severity": "low",
        "category": "config_drift",
        "resource_type": "compute.vm",
        "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
        "remediation": {"template_ref": "remediations/example-x"},
        "remediates": "ops.scale-out",
        "provenance": {
            "source_url": "https://example.com/x",
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": "sha256:example",
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-05T00:00:00Z",
        },
    }
    if cost_impact_monthly_usd is not None:
        raw["remediation"]["cost_impact_monthly_usd"] = cost_impact_monthly_usd
    return Rule.model_validate(raw)


def _make_loop(*, cost_estimator: Any = None) -> ControlLoop:
    """Assemble a ControlLoop with everything mocked except the cost path."""

    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=MagicMock(),
        executor=MagicMock(),
        audit_store=MagicMock(),
        rules_by_id={},
        cost_estimator=cost_estimator,
    )


# ---------------------------------------------------------------------------
# _resolve_cost_override
# ---------------------------------------------------------------------------


async def test_rule_static_cost_wins_over_estimator() -> None:
    """Rule cost is authoritative; estimator is not even called."""

    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 999.0)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=50.0)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override is None  # None means "no override; use rule's static cost"
    assert fake.calls == ()


async def test_estimator_fills_in_when_rule_has_no_cost() -> None:
    """Estimator estimate becomes the cost_override for the authority."""

    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 250.0)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override == 250.0


async def test_no_estimator_and_no_static_cost_returns_none() -> None:
    """No source of truth for cost -> None -> risk-gate treats as 'unknown'.

    The fail-closed rule in execution-model.md 2.8 makes the Axis A
    gate route unknown-cost cases to HIL.
    """

    loop = _make_loop(cost_estimator=None)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override is None


async def test_estimator_abstain_returns_none() -> None:
    """An abstaining estimator surfaces as None (fail-closed)."""

    fake = InMemoryCostEstimator()
    # Not seeded -> abstain.
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override is None


async def test_estimator_error_returns_none() -> None:
    """An estimator raising CostEstimatorError surfaces as None."""

    fake = InMemoryCostEstimator()
    fake.next_error(CostEstimatorError("pricing api 500"))
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override is None


async def test_estimator_low_confidence_still_surfaced() -> None:
    """A LOW-confidence estimate is still surfaced; the risk-gate
    treats the figure as-is per Axis A."""

    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 150.0, confidence=CostConfidence.LOW)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override == 150.0


@pytest.mark.parametrize("static_cost", [0.0, 1.0, 99.0])
async def test_zero_or_low_static_cost_still_wins_over_estimator(static_cost: float) -> None:
    """A rule that explicitly declares $0 or any low cost is authoritative.

    Cost=0 is a real answer (control-plane change, no spend), not an
    'unknown' - so the estimator MUST NOT overwrite it. Only a truly
    unset rule cost falls through to the estimator.
    """

    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 999.0)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=static_cost)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override is None
    assert fake.calls == ()


async def test_returns_shape_is_directly_ingestable_by_evaluate_execution_authority() -> None:
    """Contract test: whatever we return is a Union[float, None]."""

    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 42.0)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert isinstance(override, float | type(None))


async def test_estimate_is_returned_intact_when_high_confidence() -> None:
    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 500.5, confidence=CostConfidence.HIGH)
    loop = _make_loop(cost_estimator=fake)
    rule = _make_rule(cost_impact_monthly_usd=None)

    override = await loop._resolve_cost_override(rule=rule, action_type=_at())
    assert override == 500.5


# Silence 'unused import' - the CostEstimate reference documents the
# shape the fake produces; keeping it in the imports makes the test
# module discoverable via grep for the Protocol type.
_ = CostEstimate
