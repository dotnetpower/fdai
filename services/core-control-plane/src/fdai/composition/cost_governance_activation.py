"""Compose persisted Cost Governance activation from manager-derived metadata."""

from __future__ import annotations

from datetime import datetime

from fdai.core.vertical_packages import VerticalPackageActivationMetadata
from fdai.shared.providers.cost_governance import CostPackageActivation


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


__all__ = ["compose_cost_package_activation"]
