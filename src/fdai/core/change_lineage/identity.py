"""Canonical content-bound identity for immutable Change lineage records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .traces import ChangeDecisionTrace, ChangeResilienceTrace

_LINEAGE_PREFIX = "change-lineage:"


def validate_change_lineage_id(lineage_id: str) -> None:
    """Reject lineage identities that are not lowercase SHA-256 references."""

    lineage_digest = lineage_id.removeprefix(_LINEAGE_PREFIX)
    if (
        not lineage_id.startswith(_LINEAGE_PREFIX)
        or len(lineage_digest) != 64
        or any(character not in "0123456789abcdef" for character in lineage_digest)
    ):
        raise ValueError("change lineage lineage_id MUST contain a lowercase SHA-256 digest")


def compute_change_lineage_id(
    *,
    change_id: str,
    change_source: str,
    change_ref: str,
    correlation_id: str,
    assessment_digest: str,
    decision_case_id: str,
    selected_option_id: str,
    action_id: str,
    event_id: str,
    action_type_id: str,
    target_digest: str,
    outcome_id: str,
    outcome_label: str,
    change_at: datetime,
    decision_at: datetime,
    action_at: datetime,
    outcome_at: datetime,
    decision: ChangeDecisionTrace,
    resilience: ChangeResilienceTrace,
    evidence_refs: tuple[str, ...],
) -> str:
    """Return the canonical content-bound identity for one lineage record."""

    identity_material: dict[str, object] = {
        "change_id": change_id,
        "change_source": change_source,
        "change_ref": change_ref,
        "correlation_id": correlation_id,
        "assessment_digest": assessment_digest,
        "decision_case_id": decision_case_id,
        "selected_option_id": selected_option_id,
        "action_id": action_id,
        "event_id": event_id,
        "action_type_id": action_type_id,
        "target_digest": target_digest,
        "outcome_id": outcome_id,
        "outcome_label": outcome_label,
        "change_at": change_at.isoformat(),
        "decision_at": decision_at.isoformat(),
        "action_at": action_at.isoformat(),
        "outcome_at": outcome_at.isoformat(),
        "decision": decision.to_mapping(),
        "resilience": resilience.to_mapping(),
        "evidence_refs": evidence_refs,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return f"{_LINEAGE_PREFIX}{digest}"


__all__ = ["compute_change_lineage_id"]
