"""Pure transition planning for atomic catalog-generation rollback stores."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogGenerationRollbackReceipt,
    CatalogGenerationStaleError,
)


@dataclass(frozen=True, slots=True)
class CatalogGenerationRollbackTransition:
    """Validated state replacement, or an exact already-applied retry."""

    receipt: CatalogGenerationRollbackReceipt
    already_applied: bool


def plan_catalog_generation_rollback(
    *,
    current: CatalogGenerationMetadata,
    target: CatalogGenerationMetadata,
    active_generation_id: str | None,
    expected_active_generation_digest: str,
    expected_target_generation_digest: str,
    expected_validation_receipt_digest: str,
    ontology_compatibility_receipt: OntologyGenerationCompatibilityReceipt,
    rolled_back_at: datetime,
) -> CatalogGenerationRollbackTransition:
    """Validate pinned identities and return the all-or-nothing metadata transition."""

    if rolled_back_at.tzinfo is None:
        raise ValueError("catalog rollback time MUST be timezone-aware")
    if current.generation_id == target.generation_id:
        raise ValueError("catalog rollback target MUST differ from the active generation")
    if current.generation_digest != expected_active_generation_digest:
        raise ValueError("active catalog generation digest mismatch")
    if target.generation_digest != expected_target_generation_digest:
        raise ValueError("target catalog generation digest mismatch")
    if target.validation_receipt_digest != expected_validation_receipt_digest:
        raise ValueError("target catalog generation validation receipt mismatch")
    if current.corpus != target.corpus:
        raise ValueError("catalog rollback generations MUST share one corpus")
    if active_generation_id == target.generation_id:
        if (
            current.state == "retired"
            and target.state == "active"
            and target.activated_at == rolled_back_at
        ):
            return CatalogGenerationRollbackTransition(
                receipt=CatalogGenerationRollbackReceipt(
                    retired_generation=current,
                    reactivated_generation=target,
                    validation_receipt_digest=expected_validation_receipt_digest,
                    ontology_compatibility_receipt=ontology_compatibility_receipt,
                    rolled_back_at=rolled_back_at,
                ),
                already_applied=True,
            )
        raise CatalogGenerationStaleError("active catalog generation is stale")
    if active_generation_id != current.generation_id or current.state != "active":
        raise CatalogGenerationStaleError("active catalog generation is stale")
    if target.state != "retired" or target.activated_at is None:
        raise ValueError("target catalog generation is not a retained prior generation")

    retired = replace(current, state="retired")
    reactivated = replace(target, state="active", activated_at=rolled_back_at)
    return CatalogGenerationRollbackTransition(
        receipt=CatalogGenerationRollbackReceipt(
            retired_generation=retired,
            reactivated_generation=reactivated,
            validation_receipt_digest=expected_validation_receipt_digest,
            ontology_compatibility_receipt=ontology_compatibility_receipt,
            rolled_back_at=rolled_back_at,
        ),
        already_applied=False,
    )


__all__ = [
    "CatalogGenerationRollbackTransition",
    "plan_catalog_generation_rollback",
]
