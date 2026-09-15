"""Project current relationship evidence without changing graph or action authority."""

from __future__ import annotations

from datetime import datetime

from fdai_operator_service.families.operations.contracts import (
    InventoryRelationshipEvidence,
)


def project_relationship_evidence(
    evidence: InventoryRelationshipEvidence | None,
    *,
    cutoff: datetime,
    evaluated_at: datetime,
    source_complete: bool | None,
) -> dict[str, object]:
    """Return one bounded evidence state at the supplied aware evaluation time."""

    if cutoff.tzinfo is None or evaluated_at.tzinfo is None:
        raise ValueError("relationship evidence times MUST be timezone-aware")
    if source_complete is not None and not isinstance(source_complete, bool):
        raise ValueError("relationship evidence source completeness MUST be boolean or null")
    if evidence is None:
        return {
            "status": "unavailable",
            "evidence_kind": None,
            "verification_status": "unavailable",
            "source": None,
            "source_property_path": None,
            "mapping_id": None,
            "evidence_method": None,
            "cutoff": None,
            "freshness_ceiling_seconds": None,
            "complete": False,
            "reason": "provider_relationship_evidence_unavailable",
        }
    evidence_cutoff = evidence.evidence_cutoff or cutoff
    age_seconds = (evaluated_at - evidence_cutoff).total_seconds()
    if evidence_cutoff > cutoff or age_seconds < 0:
        status = "stale"
        reason = "relationship_evidence_future_cutoff"
    elif age_seconds > evidence.freshness_ceiling_seconds:
        status = "stale"
        reason = "relationship_evidence_stale"
    elif evidence.evidence_kind == "configuration" and source_complete is False:
        status = "unavailable"
        reason = "relationship_source_incomplete"
    elif evidence.evidence_kind == "configuration" and source_complete is None:
        status = "unavailable"
        reason = "relationship_source_coverage_unavailable"
    else:
        status = "available"
        reason = None
    return {
        "status": status,
        "evidence_kind": evidence.evidence_kind,
        "verification_status": (
            "independently_verified"
            if evidence.evidence_kind == "observation"
            else "configuration_observed"
        ),
        "source": evidence.source_identity,
        "source_property_path": evidence.source_property_path,
        "mapping_id": evidence.mapping_id,
        "evidence_method": evidence.evidence_method,
        "cutoff": evidence_cutoff.isoformat(),
        "freshness_ceiling_seconds": evidence.freshness_ceiling_seconds,
        "complete": status == "available",
        "reason": reason,
    }


__all__ = ["project_relationship_evidence"]
