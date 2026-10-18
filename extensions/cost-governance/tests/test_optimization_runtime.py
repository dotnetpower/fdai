from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.cost_governance import CostPackageActivation

from fdai_cost_governance.optimization_runtime import (
    CostOptimizationRuntime,
    OptimizationPublicationState,
)
from fdai_cost_governance.pantheon_composition import (
    OptimizationReinjectionDisposition,
    OptimizationReinjectionResult,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


class Activation:
    def __init__(self, snapshot: CostPackageActivation | None) -> None:
        self.snapshot = snapshot

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
        assert package_id == "cost-governance"
        return self.snapshot


class Publisher:
    def __init__(self) -> None:
        self.values: list[tuple[dict[str, Any], int]] = []

    async def publish_cost_optimization_candidate(
        self,
        candidate: dict[str, Any],
        *,
        activation_revision: int,
    ) -> None:
        self.values.append((candidate, activation_revision))


def _activation(*, enabled: bool) -> CostPackageActivation:
    return CostPackageActivation(
        vertical_id="cost-governance",
        package_id="cost-governance",
        available=True,
        enabled=enabled,
        availability_reasons=(),
        package_version="0.1.0",
        image_digest="sha256:" + "a" * 64,
        asset_manifest_digest="sha256:" + "b" * 64,
        semantic_profile_digest="sha256:" + "c" * 64,
        previously_enabled=False,
        revision=7,
        effective_at=NOW,
        ontology_release_id="ontology-release:example",
        ontology_release_digest="sha256:" + "d" * 64,
        source_authority="activation-store",
    )


async def test_reinjection_publication_uses_current_activation_revision() -> None:
    publisher = Publisher()
    runtime = CostOptimizationRuntime(
        package_id="cost-governance",
        activation_reader=Activation(_activation(enabled=True)),
        publisher=publisher,
    )
    candidate = {
        "kind": "cross_vertical_candidate",
        "correlation_id": "optimization-example",
        "idempotency_key": "optimization-example:v2",
        "resource_id": "optimization-set-example",
        "observed_at": NOW.isoformat(),
    }

    result = await runtime.publish_reinjection(
        OptimizationReinjectionResult(
            disposition=OptimizationReinjectionDisposition.READY,
            reason="attestation_accepted_for_typed_reinjection",
            candidate=candidate,
        )
    )

    assert result.state is OptimizationPublicationState.PUBLISHED
    assert publisher.values == [(candidate, 7)]


async def test_disabled_activation_and_held_reinjection_publish_nothing() -> None:
    publisher = Publisher()
    disabled = CostOptimizationRuntime(
        package_id="cost-governance",
        activation_reader=Activation(_activation(enabled=False)),
        publisher=publisher,
    )
    candidate = {
        "kind": "cross_vertical_candidate",
        "correlation_id": "optimization-example",
        "idempotency_key": "optimization-example:v2",
        "resource_id": "optimization-set-example",
        "observed_at": NOW.isoformat(),
    }

    disabled_result = await disabled.publish_reinjection(
        OptimizationReinjectionResult(
            disposition=OptimizationReinjectionDisposition.READY,
            reason="ready",
            candidate=candidate,
        )
    )
    held_result = await disabled.publish_reinjection(
        OptimizationReinjectionResult(
            disposition=OptimizationReinjectionDisposition.HELD,
            reason="attestation_expired",
            candidate=None,
        )
    )

    assert disabled_result.state is OptimizationPublicationState.HELD
    assert held_result.state is OptimizationPublicationState.HELD
    assert publisher.values == []
