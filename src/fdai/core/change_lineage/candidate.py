"""Candidate-only learning projection from canonical Change lineage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .models import ChangeLineageRecord


@dataclass(frozen=True, slots=True)
class ChangeLearningCandidate:
    """Inert lineage signals that require sealing before operational reuse."""

    candidate_id: str
    lineage_id: str
    change_source: str
    change_ref: str
    assessment_digest: str
    action_type_id: str
    selected_objective_ids: tuple[str, ...]
    violated_constraint_ids: tuple[str, ...]
    outcome_label: str
    verification_status: str
    execution_mode: str
    rollback_succeeded: bool | None
    evidence_refs: tuple[str, ...]
    candidate_only: bool = True
    requires_sealed_case: bool = True
    operational_reuse_eligible: bool = False
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        text_values = (
            self.candidate_id,
            self.lineage_id,
            self.change_source,
            self.change_ref,
            self.assessment_digest,
            self.action_type_id,
            self.outcome_label,
            self.verification_status,
            self.execution_mode,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("change learning candidate identities MUST be non-empty")
        canonical_sets = (
            self.selected_objective_ids,
            self.violated_constraint_ids,
            self.evidence_refs,
        )
        if any(values != tuple(sorted(set(values))) for values in canonical_sets):
            raise ValueError("change learning candidate collections MUST be sorted and unique")
        if not self.selected_objective_ids or not self.evidence_refs:
            raise ValueError("change learning candidate MUST cite objectives and evidence")
        if (
            not self.candidate_only
            or not self.requires_sealed_case
            or self.operational_reuse_eligible
            or self.execution_authority
            or self.promotion_authority
        ):
            raise ValueError(
                "change learning candidate MUST remain candidate-only and authority-free"
            )

    def to_mapping(self) -> dict[str, Any]:
        """Return the bounded projection for a future sealed-case intake owner."""

        return {
            "candidate_id": self.candidate_id,
            "lineage_id": self.lineage_id,
            "change_source": self.change_source,
            "change_ref": self.change_ref,
            "assessment_digest": self.assessment_digest,
            "action_type_id": self.action_type_id,
            "selected_objective_ids": list(self.selected_objective_ids),
            "violated_constraint_ids": list(self.violated_constraint_ids),
            "outcome_label": self.outcome_label,
            "verification_status": self.verification_status,
            "execution_mode": self.execution_mode,
            "rollback_succeeded": self.rollback_succeeded,
            "evidence_refs": list(self.evidence_refs),
            "candidate_only": True,
            "requires_sealed_case": True,
            "operational_reuse_eligible": False,
            "execution_authority": False,
            "promotion_authority": False,
        }


def extract_learning_candidate(lineage: ChangeLineageRecord) -> ChangeLearningCandidate:
    """Extract replay-stable signals without classifying or promoting reuse."""

    material = {
        "lineage_id": lineage.lineage_id,
        "change_source": lineage.change_source,
        "change_ref": lineage.change_ref,
        "assessment_digest": lineage.assessment_digest,
        "action_type_id": lineage.action_type_id,
        "selected_objective_ids": tuple(
            sorted(effect.objective_id for effect in lineage.decision.selected_effects)
        ),
        "violated_constraint_ids": lineage.decision.violated_constraint_ids,
        "outcome_label": lineage.outcome_label,
        "verification_status": lineage.resilience.verification_status,
        "execution_mode": lineage.resilience.execution_mode,
        "rollback_succeeded": lineage.resilience.rollback_succeeded,
        "evidence_refs": lineage.evidence_refs,
    }
    digest = hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return ChangeLearningCandidate(
        candidate_id=f"change-learning-candidate:{digest}",
        lineage_id=lineage.lineage_id,
        change_source=lineage.change_source,
        change_ref=lineage.change_ref,
        assessment_digest=lineage.assessment_digest,
        action_type_id=lineage.action_type_id,
        selected_objective_ids=tuple(
            sorted(effect.objective_id for effect in lineage.decision.selected_effects)
        ),
        violated_constraint_ids=lineage.decision.violated_constraint_ids,
        outcome_label=lineage.outcome_label,
        verification_status=lineage.resilience.verification_status,
        execution_mode=lineage.resilience.execution_mode,
        rollback_succeeded=lineage.resilience.rollback_succeeded,
        evidence_refs=lineage.evidence_refs,
    )


__all__ = ["ChangeLearningCandidate", "extract_learning_candidate"]
