"""Revalidate model-proposed constraint slot values against Core catalogs."""

from __future__ import annotations

from typing import Any, Protocol

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal
from fdai_service_contracts.semantic_slots import ConstraintSlotRole

from fdai.core.ontology_platform import ReviewedPropertyRead

from .semantic_reasoning_concepts import concept_catalogs
from .semantic_reasoning_form import MentionDomain
from .semantic_reasoning_lifecycle import lifecycle_values

_CATALOG_DOMAINS = {
    ConstraintSlotRole.LOCATION: MentionDomain.REGION,
    ConstraintSlotRole.LIFECYCLE_STATUS: MentionDomain.STATE,
}


class SlotCatalogManifest(Protocol):
    @property
    def descriptors(self) -> tuple[dict[str, Any], ...]: ...

    @property
    def property_reads(self) -> tuple[ReviewedPropertyRead, ...]: ...


def reground_constraint_slots(
    proposal: SemanticJudgmentProposal,
    *,
    manifest: SlotCatalogManifest,
) -> SemanticJudgmentProposal:
    """Keep a grounded slot only when its canonical value is in Core's closed catalog."""

    if not proposal.constraint_slots:
        return proposal
    catalogs = concept_catalogs(manifest.descriptors, property_reads=manifest.property_reads)
    allowed = {
        role: frozenset(
            value for candidate in catalogs.get(domain, ()) for value in candidate.values
        )
        for role, domain in _CATALOG_DOMAINS.items()
    }
    allowed[ConstraintSlotRole.LIFECYCLE_STATUS] = frozenset(
        item.concept for item in lifecycle_values(manifest.descriptors)
    )
    slots = tuple(
        slot.model_copy(
            update={
                "grounded": False,
                "unbound_reason": "out_of_domain",
            }
        )
        if slot.grounded and slot.role in allowed and slot.value not in allowed[slot.role]
        else slot
        for slot in proposal.constraint_slots
    )
    return (
        proposal
        if slots == proposal.constraint_slots
        else proposal.model_copy(update={"constraint_slots": slots})
    )


__all__ = ["reground_constraint_slots"]
