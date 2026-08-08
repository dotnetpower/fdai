"""Wave W2.5 - CostEstimator seam + fake + resolve_cost_impact_monthly."""

from __future__ import annotations

import pytest
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.providers.cost_estimator import (
    CostConfidence,
    CostEstimate,
    CostEstimatorError,
    resolve_cost_impact_monthly,
)
from fdai.shared.providers.testing.cost_estimator import InMemoryCostEstimator


def _at(name: str = "ops.scale-out") -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
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


# ---------------------------------------------------------------------------
# CostEstimate dataclass invariants
# ---------------------------------------------------------------------------


def test_cost_estimate_requires_estimator_id() -> None:
    with pytest.raises(ValueError, match="estimator_id"):
        CostEstimate(
            monthly_usd=42.0,
            confidence=CostConfidence.HIGH,
            estimator_id="",
        )


def test_cost_estimate_abstain_forbids_a_figure() -> None:
    with pytest.raises(ValueError, match="ABSTAIN"):
        CostEstimate(
            monthly_usd=1.0,
            confidence=CostConfidence.ABSTAIN,
            estimator_id="e",
        )


def test_cost_estimate_non_abstain_requires_a_figure() -> None:
    with pytest.raises(ValueError, match="MUST be a float"):
        CostEstimate(
            monthly_usd=None,
            confidence=CostConfidence.HIGH,
            estimator_id="e",
        )


def test_cost_estimate_rejects_negative_figure() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        CostEstimate(
            monthly_usd=-1.0,
            confidence=CostConfidence.HIGH,
            estimator_id="e",
        )


def test_cost_estimate_serializes_to_dict() -> None:
    est = CostEstimate(
        monthly_usd=250.0,
        confidence=CostConfidence.MEDIUM,
        estimator_id="e-1",
        rationale="D2s_v3 x1 per hour x 730h",
        metadata={"region": "koreacentral"},
    )
    payload = est.to_dict()
    assert payload["monthly_usd"] == 250.0
    assert payload["confidence"] == "medium"
    assert payload["estimator_id"] == "e-1"
    assert payload["rationale"] == "D2s_v3 x1 per hour x 730h"
    assert payload["metadata"] == {"region": "koreacentral"}


def test_cost_estimate_abstained_property() -> None:
    est = CostEstimate(
        monthly_usd=None,
        confidence=CostConfidence.ABSTAIN,
        estimator_id="e",
    )
    assert est.abstained is True


# ---------------------------------------------------------------------------
# Fake seed / estimate contract
# ---------------------------------------------------------------------------


async def test_fake_returns_seeded_estimate() -> None:
    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 250.0, rationale="one D2s_v3")
    got = await fake.estimate(_at("ops.scale-out"), {"replica_count": 3})
    assert got.monthly_usd == 250.0
    assert got.confidence is CostConfidence.HIGH
    assert got.rationale == "one D2s_v3"
    assert fake.calls == (("ops.scale-out", {"replica_count": 3}),)


async def test_fake_abstains_by_default_when_not_seeded() -> None:
    fake = InMemoryCostEstimator()
    got = await fake.estimate(_at("ops.scale-out"), {})
    assert got.confidence is CostConfidence.ABSTAIN
    assert got.monthly_usd is None
    assert got.abstained is True


async def test_fake_seed_abstain_forces_abstain() -> None:
    fake = InMemoryCostEstimator()
    fake.seed_abstain("ops.scale-out", rationale="unknown region")
    got = await fake.estimate(_at("ops.scale-out"), {})
    assert got.abstained is True
    assert got.rationale == "unknown region"


async def test_fake_next_error_raises_once() -> None:
    fake = InMemoryCostEstimator()
    fake.next_error(CostEstimatorError("pricing api 500"))
    with pytest.raises(CostEstimatorError, match="pricing api 500"):
        await fake.estimate(_at(), {})
    # Second call recovers to abstain.
    got = await fake.estimate(_at(), {})
    assert got.abstained is True


def test_seed_rejects_abstain_confidence() -> None:
    fake = InMemoryCostEstimator()
    with pytest.raises(ValueError, match="seed_abstain"):
        fake.seed("k", 1.0, confidence=CostConfidence.ABSTAIN)


def test_estimator_id_empty_rejected() -> None:
    with pytest.raises(ValueError, match="estimator_id"):
        InMemoryCostEstimator(estimator_id="")


async def test_fake_custom_key_fn() -> None:
    fake = InMemoryCostEstimator(key_fn=lambda at, args: f"{at.name}/{args.get('sku', 'unknown')}")
    fake.seed("ops.scale-out/large", 500.0)
    fake.seed("ops.scale-out/small", 50.0)
    got_large = await fake.estimate(_at("ops.scale-out"), {"sku": "large"})
    got_small = await fake.estimate(_at("ops.scale-out"), {"sku": "small"})
    assert got_large.monthly_usd == 500.0
    assert got_small.monthly_usd == 50.0


# ---------------------------------------------------------------------------
# resolve_cost_impact_monthly adapter (the risk-gate consumer)
# ---------------------------------------------------------------------------


async def test_resolve_returns_none_when_estimator_is_none() -> None:
    got = await resolve_cost_impact_monthly(None, _at())
    assert got is None


async def test_resolve_returns_grounded_figure() -> None:
    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 250.0)
    got = await resolve_cost_impact_monthly(fake, _at("ops.scale-out"), {"replica_count": 2})
    assert got == 250.0


async def test_resolve_returns_none_when_estimator_abstains() -> None:
    fake = InMemoryCostEstimator()
    # Not seeded -> abstain.
    got = await resolve_cost_impact_monthly(fake, _at("ops.scale-out"), {})
    assert got is None


async def test_resolve_returns_none_on_estimator_error() -> None:
    fake = InMemoryCostEstimator()
    fake.next_error(CostEstimatorError("boom"))
    got = await resolve_cost_impact_monthly(fake, _at("ops.scale-out"), {})
    assert got is None


async def test_resolve_accepts_none_arguments() -> None:
    fake = InMemoryCostEstimator()
    fake.seed("ops.scale-out", 250.0)
    got = await resolve_cost_impact_monthly(fake, _at("ops.scale-out"), None)
    assert got == 250.0
