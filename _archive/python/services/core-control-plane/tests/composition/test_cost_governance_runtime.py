"""Cost Governance package-to-Pantheon composition tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fdai.composition import cost_governance_activation
from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostObservation,
    CostPackageActivation,
    SignedCostEffectEstimate,
)


def _activation(*, enabled: bool) -> CostPackageActivation:
    digest = f"sha256:{'a' * 64}"
    return CostPackageActivation(
        vertical_id="cost-governance",
        package_id="cost-governance",
        available=True,
        enabled=enabled,
        availability_reasons=(),
        package_version="0.1.1",
        image_digest=digest,
        asset_manifest_digest=digest,
        semantic_profile_digest=digest,
        revision=2,
        effective_at=datetime(2026, 8, 31, tzinfo=UTC),
        ontology_release_id="ontology:test",
        ontology_release_digest=digest,
        source_authority="test",
    )


class _Store:
    activation = _activation(enabled=True)

    def __init__(self, *, config: object) -> None:
        del config

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
        assert package_id == "cost-governance"
        return self.activation

    async def cost_budget_data_available(self) -> bool:
        return True

    async def read_recent_complete_cost_observations(
        self,
        *,
        package_id: str,
        ontology_release_digest: str,
        limit: int,
    ) -> tuple[CostObservation, ...]:
        assert package_id == "cost-governance"
        assert ontology_release_digest == f"sha256:{'a' * 64}"
        assert limit == 1000
        observed_at = datetime(2026, 8, 30, tzinfo=UTC)
        return (
            CostObservation(
                observation_id="costobs:test",
                package_id=package_id,
                scope_id="scope-a",
                service_id="service-a",
                amount=Decimal("12.34"),
                currency="USD",
                event_start_at=datetime(2026, 8, 29, tzinfo=UTC),
                event_end_at=observed_at,
                observed_at=observed_at,
                recorded_at=observed_at,
                source_authority="test-usage-details",
                source_uri="cost-service:test",
                completeness=Decimal("1"),
                ontology_release_id="ontology:test",
                ontology_release_digest=ontology_release_digest,
                evidence_digest=f"sha256:{'b' * 64}",
                retention_until=datetime(2027, 8, 30, tzinfo=UTC),
            ),
        )


class _Provider:
    def __init__(self, *, ontology_release_digest: str) -> None:
        self.ontology_release_digest = ontology_release_digest
        self.calls = 0

    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> None:
        assert sample.ontology_release_digest == self.ontology_release_digest
        self.calls += 1

    async def hydrate_cost_samples(
        self,
        samples: tuple[CostAnalysisSample, ...],
    ) -> tuple[CostAnalysisSample, ...]:
        for sample in samples:
            assert sample.ontology_release_digest == self.ontology_release_digest
        self.calls += len(samples)
        return samples

    def estimate_cost_effect(
        self,
        action_type: str,
    ) -> SignedCostEffectEstimate | None:
        del action_type
        return None


class _EntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        return self._loaded


@pytest.mark.asyncio
async def test_absent_state_store_keeps_cost_runtime_disabled() -> None:
    binding = await cost_governance_activation.build_cost_runtime_bindings({})

    assert binding.package_enabled is False
    assert binding.advisory_provider is None
    assert binding.activation_reader is None


@pytest.mark.asyncio
async def test_enabled_package_binds_njord_advisory_without_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cost_governance_activation, "PostgresCostGovernanceStore", _Store)
    monkeypatch.setattr(
        cost_governance_activation,
        "entry_points",
        lambda **_: (_EntryPoint("cost-governance", _Provider),),
    )

    binding = await cost_governance_activation.build_cost_runtime_bindings(
        {"FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai"}
    )

    assert binding.package_enabled is True
    assert binding.advisory_provider is not None
    assert binding.activation_reader is not None
    assert binding.budget_data_available is True
    assert not hasattr(binding.advisory_provider, "execute")
    assert len(binding.initial_samples) == 1
    assert binding.initial_samples[0].resource_id == "cost-service:test"
    assert isinstance(binding.advisory_provider, _Provider)
    assert binding.advisory_provider.calls == 1


@pytest.mark.parametrize(
    "loaded",
    [object(), lambda **_: object()],
)
def test_advisory_entry_point_must_implement_package_neutral_port(
    monkeypatch: pytest.MonkeyPatch,
    loaded: object,
) -> None:
    monkeypatch.setattr(
        cost_governance_activation,
        "entry_points",
        lambda **_: (_EntryPoint("cost-governance", loaded),),
    )

    with pytest.raises(RuntimeError, match="entry point|package-neutral port"):
        cost_governance_activation._load_cost_advisory_provider(f"sha256:{'a' * 64}")
