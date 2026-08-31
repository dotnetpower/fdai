"""Compose persisted Cost Governance activation from manager-derived metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from importlib.metadata import entry_points
from typing import Protocol, cast

from fdai.agents import DEFAULT_COST_RUNTIME_BINDINGS, CostRuntimeBindings
from fdai.core.vertical_packages import VerticalPackageActivationMetadata
from fdai.delivery.persistence.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceStore,
)
from fdai.shared.providers.cost_governance import (
    CostAdvisoryProvider,
    CostAnalysisSample,
    CostPackageActivation,
)

_COST_ADVISORY_PROVIDER_GROUP = "fdai.cost_advisory_providers"
_COST_GOVERNANCE_ENTRY_POINT = "cost-governance"
_MAX_HYDRATED_COST_SAMPLES = 1000


class _HydratableCostAdvisoryProvider(CostAdvisoryProvider, Protocol):
    async def hydrate_cost_samples(
        self,
        samples: Sequence[CostAnalysisSample],
    ) -> tuple[CostAnalysisSample, ...]: ...


def compose_cost_package_activation(
    metadata: VerticalPackageActivationMetadata,
    *,
    revision: int,
    effective_at: datetime,
    ontology_release_id: str,
    source_authority: str,
    previously_enabled: bool = False,
) -> CostPackageActivation:
    """Preserve manager-derived availability while adding persistence metadata."""

    return CostPackageActivation(
        vertical_id=metadata.vertical_id,
        package_id=metadata.package_id,
        available=metadata.available,
        enabled=metadata.enabled,
        availability_reasons=metadata.availability_reasons,
        package_version=metadata.package_version,
        image_digest=metadata.image_digest,
        asset_manifest_digest=metadata.asset_manifest_digest,
        semantic_profile_digest=metadata.semantic_profile_digest,
        revision=revision,
        effective_at=effective_at,
        ontology_release_id=ontology_release_id,
        ontology_release_digest=metadata.ontology_release_digest,
        source_authority=source_authority,
        previously_enabled=previously_enabled,
    )


async def build_cost_runtime_bindings(
    environment: Mapping[str, str],
) -> CostRuntimeBindings:
    """Bind the optional enabled package to Njord's package-neutral ports."""

    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return DEFAULT_COST_RUNTIME_BINDINGS
    store = PostgresCostGovernanceStore(config=PostgresCostGovernanceConfig(dsn=dsn))
    activation = await store.read_cost_activation("cost-governance")
    if activation is None or not activation.available or not activation.enabled:
        return CostRuntimeBindings(
            activation_reader=store,
            package_enabled=False,
        )
    budget_data_available = await store.cost_budget_data_available()
    provider = _load_cost_advisory_provider(activation.ontology_release_digest)
    observations = await store.read_recent_complete_cost_observations(
        package_id=activation.package_id,
        ontology_release_digest=activation.ontology_release_digest,
        limit=_MAX_HYDRATED_COST_SAMPLES,
    )
    initial_samples = tuple(
        CostAnalysisSample(
            scope_id=observation.scope_id,
            resource_id=observation.source_uri,
            amount_usd=observation.amount,
            correlation_id=observation.observation_id,
            observed_at=observation.observed_at,
            source_authority=observation.source_authority,
            completeness=observation.completeness,
            ontology_release_digest=observation.ontology_release_digest,
        )
        for observation in observations
    )
    initial_samples = await provider.hydrate_cost_samples(initial_samples)
    return CostRuntimeBindings(
        advisory_provider=provider,
        activation_reader=store,
        package_enabled=True,
        budget_data_available=budget_data_available,
        initial_samples=initial_samples,
    )


def _load_cost_advisory_provider(
    ontology_release_digest: str,
) -> _HydratableCostAdvisoryProvider:
    matches = tuple(
        entry_point
        for entry_point in entry_points(group=_COST_ADVISORY_PROVIDER_GROUP)
        if entry_point.name == _COST_GOVERNANCE_ENTRY_POINT
    )
    if len(matches) != 1:
        raise RuntimeError(
            "enabled Cost Governance package requires exactly one advisory provider entry point"
        )
    provider_factory: object = matches[0].load()
    if not callable(provider_factory):
        raise RuntimeError("Cost Governance advisory provider entry point is not callable")
    provider: object = provider_factory(ontology_release_digest=ontology_release_digest)
    if (
        not callable(getattr(provider, "analyze_cost_sample", None))
        or not callable(getattr(provider, "estimate_cost_effect", None))
        or not callable(getattr(provider, "hydrate_cost_samples", None))
    ):
        raise RuntimeError(
            "Cost Governance advisory provider does not implement the package-neutral port"
        )
    return cast(_HydratableCostAdvisoryProvider, provider)


__all__ = ["build_cost_runtime_bindings", "compose_cost_package_activation"]
