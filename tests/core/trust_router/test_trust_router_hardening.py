from __future__ import annotations

from typing import Any

import pytest

from fdai.core.trust_router import RoutingTier, TrustRouter
from tests.core.trust_router.test_trust_router import _event, _index, _rule


@pytest.mark.parametrize(
    ("payload", "expected_type", "expected_tier"),
    [
        ({"resource": {"type": " compute.vm "}}, "compute.vm", RoutingTier.T0),
        ({"resource_type": "\tcompute.vm\n"}, "compute.vm", RoutingTier.T0),
        ({"resource": {"type": "   "}}, None, RoutingTier.ABSTAIN),
        ({"resource_type": "\t"}, None, RoutingTier.ABSTAIN),
        ({"resource": {"type": " "}, "resource_type": "compute.vm"}, "compute.vm", RoutingTier.T0),
        (
            {"resource": {"type": "compute.vm"}, "resource_type": "object-storage"},
            "compute.vm",
            RoutingTier.T0,
        ),
        ({"resource": {"type": 42}, "resource_type": "compute.vm"}, "compute.vm", RoutingTier.T0),
        ({"resource": None, "resource_type": "object-storage"}, "object-storage", RoutingTier.T1),
        ({"resource": {}, "resource_type": ""}, None, RoutingTier.ABSTAIN),
        ({}, None, RoutingTier.ABSTAIN),
    ],
)
def test_resource_type_boundary_normalization(
    payload: dict[str, Any],
    expected_type: str | None,
    expected_tier: RoutingTier,
) -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))

    decision = router.route(_event(payload))

    assert decision.resource_type == expected_type
    assert decision.tier is expected_tier
