"""Deterministic impact assessment for one normalized Change revision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.impact_analysis.analyzer import ImpactAnalyzer, ImpactTraversalBounds
from fdai.core.impact_analysis.models import AffectedSet


@dataclass(frozen=True, slots=True)
class ChangeAssessment:
    change_id: str
    correlation_id: str
    target_ref: str
    occurred_at: datetime
    affected_set: AffectedSet
    review_required: bool
    reasons: tuple[str, ...]
    evidence_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
            "occurred_at": self.occurred_at.isoformat(),
            "affected_resource_ids": list(self.affected_set.all_resource_ids),
            "protected_service_ids": list(self.affected_set.protected_services),
            "protected_objective_ids": list(self.affected_set.protected_objectives),
            "control_dependency_ids": list(self.affected_set.control_dependencies),
            "graph_revision": self.affected_set.graph_revision,
            "review_required": self.review_required,
            "reasons": list(self.reasons),
            "evidence_digest": self.evidence_digest,
        }


class ChangeAssessmentService:
    """Assess a Change against fresh bounded ontology impact evidence."""

    def __init__(
        self,
        *,
        analyzer: ImpactAnalyzer,
        max_affected_resources: int = 10,
        traversal_bounds: ImpactTraversalBounds | None = None,
    ) -> None:
        if max_affected_resources < 1:
            raise ValueError("max_affected_resources MUST be positive")
        self._analyzer = analyzer
        self._max_affected_resources = max_affected_resources
        self._traversal_bounds = traversal_bounds or ImpactTraversalBounds()

    async def assess(
        self,
        change: Mapping[str, Any],
        *,
        graph_fresh: bool,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> ChangeAssessment:
        change_id = _required_text(change, "id")
        correlation_id = _required_text(change, "correlation_id")
        target_ref = _required_text(change, "target_ref")
        occurred_at = _required_datetime(change, "occurred_at")
        affected = await self._analyzer.analyze(
            direct_target_ids=(target_ref,),
            bounds=self._traversal_bounds,
            graph_fresh=graph_fresh,
            unresolved_conflicts=unresolved_conflicts,
        )
        reasons = list(affected.incomplete_reasons)
        if affected.truncated:
            reasons.append("impact_truncated")
        if not affected.protected_services:
            reasons.append("service_mapping_missing")
        if not affected.protected_objectives:
            reasons.append("objective_mapping_missing")
        if len(affected.all_resource_ids) > self._max_affected_resources:
            reasons.append("affected_resource_cap_exceeded")
        if str(change.get("intent_kind") or "") == "planned":
            if not str(change.get("desired_state_digest") or "").strip():
                reasons.append("desired_state_digest_missing")
            if not str(change.get("plan_receipt_ref") or "").strip():
                reasons.append("plan_receipt_missing")
        normalized_reasons = tuple(sorted(set(reasons)))
        evidence_digest = _assessment_digest(
            change_id=change_id,
            correlation_id=correlation_id,
            target_ref=target_ref,
            occurred_at=occurred_at,
            affected=affected,
            reasons=normalized_reasons,
        )
        return ChangeAssessment(
            change_id=change_id,
            correlation_id=correlation_id,
            target_ref=target_ref,
            occurred_at=occurred_at,
            affected_set=affected,
            review_required=bool(normalized_reasons),
            reasons=normalized_reasons,
            evidence_digest=evidence_digest,
        )


def _required_text(value: Mapping[str, Any], name: str) -> str:
    resolved = str(value.get(name) or "").strip()
    if not resolved:
        raise ValueError(f"change {name} MUST be non-empty")
    return resolved


def _required_datetime(value: Mapping[str, Any], name: str) -> datetime:
    raw = _required_text(value, name)
    try:
        resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"change {name} MUST be RFC 3339") from exc
    if resolved.tzinfo is None:
        raise ValueError(f"change {name} MUST be timezone-aware")
    return resolved


def _assessment_digest(
    *,
    change_id: str,
    correlation_id: str,
    target_ref: str,
    occurred_at: datetime,
    affected: AffectedSet,
    reasons: tuple[str, ...],
) -> str:
    material = {
        "change_id": change_id,
        "correlation_id": correlation_id,
        "target_ref": target_ref,
        "occurred_at": occurred_at.isoformat(),
        "affected_resource_ids": affected.all_resource_ids,
        "protected_services": affected.protected_services,
        "protected_objectives": affected.protected_objectives,
        "control_dependencies": affected.control_dependencies,
        "graph_revision": affected.graph_revision,
        "reasons": reasons,
    }
    encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ChangeAssessment", "ChangeAssessmentService"]
