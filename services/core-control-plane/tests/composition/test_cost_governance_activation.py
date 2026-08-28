"""Cost Governance manager-to-persistence composition tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.composition.cost_governance_activation import compose_cost_package_activation
from fdai.core.vertical_packages import VerticalPackageActivationMetadata


def _metadata(*, available: bool, enabled: bool) -> VerticalPackageActivationMetadata:
    return VerticalPackageActivationMetadata(
        vertical_id="cost-governance",
        package_id="fdai-cost-governance",
        available=available,
        enabled=enabled,
        availability_reasons=(() if available else ("missing_provider:cost-estimator",)),
        package_version="0.1.0",
        image_digest=f"sha256:{'a' * 64}",
        asset_manifest_digest=f"sha256:{'b' * 64}",
        semantic_profile_digest=f"sha256:{'c' * 64}",
        ontology_release_digest=f"sha256:{'d' * 64}",
    )


def test_composition_preserves_available_disabled_without_deriving_from_enablement() -> None:
    activation = compose_cost_package_activation(
        _metadata(available=True, enabled=False),
        revision=7,
        effective_at=datetime(2026, 8, 28, tzinfo=UTC),
        ontology_release_id="ontology-release:2026-08",
        source_authority="vertical-package-manager",
    )

    assert activation.available is True
    assert activation.enabled is False
    assert activation.availability_reasons == ()
    assert activation.revision == 7


def test_composition_preserves_unavailable_reason_and_artifact_identity() -> None:
    activation = compose_cost_package_activation(
        _metadata(available=False, enabled=False),
        revision=8,
        effective_at=datetime(2026, 8, 28, tzinfo=UTC),
        ontology_release_id="ontology-release:2026-08",
        source_authority="vertical-package-manager",
    )

    assert activation.available is False
    assert activation.enabled is False
    assert activation.availability_reasons == ("missing_provider:cost-estimator",)
    assert activation.package_version == "0.1.0"
    assert activation.semantic_profile_digest == f"sha256:{'c' * 64}"
