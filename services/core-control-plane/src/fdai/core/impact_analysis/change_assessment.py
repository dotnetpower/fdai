"""Deterministic impact assessment for one normalized Change revision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.core.impact_analysis.analyzer import ImpactAnalyzer, ImpactTraversalBounds
from fdai.core.impact_analysis.models import AffectedSet
from fdai.core.ontology_platform.graph_evidence_refresh import GraphEvidenceFreshness
from fdai.core.operational_context.models import OperationalContextSnapshot


class GraphEvidenceReleaseState(StrEnum):
    """Describe whether the pinned ontology release matches the assessment input."""

    ALIGNED = "aligned"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ChangeGraphEvidenceReceipt:
    """Bound one planned-change assessment to graph freshness and release evidence."""

    freshness: GraphEvidenceFreshness
    release_state: GraphEvidenceReleaseState
    graph_revision: str | None = None
    authenticated: bool = True
    source_complete: bool = True
    source_generation: str | None = None
    truncated: bool = False
    conflict_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.graph_revision is not None and not self.graph_revision.strip():
            raise ValueError("graph evidence graph_revision MUST be non-empty when provided")
        if self.source_generation is not None and not self.source_generation.strip():
            raise ValueError("graph evidence source_generation MUST be non-empty when provided")
        if any(not reason.strip() for reason in self.conflict_reasons):
            raise ValueError("graph evidence conflict_reasons MUST contain non-empty values")

    @classmethod
    def unavailable(cls) -> ChangeGraphEvidenceReceipt:
        """Return the fail-closed receipt for callers without verified graph evidence."""

        return cls(
            freshness=GraphEvidenceFreshness.UNAVAILABLE,
            release_state=GraphEvidenceReleaseState.UNKNOWN,
            authenticated=False,
            source_complete=False,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "graph_revision": self.graph_revision,
            "freshness": self.freshness.value,
            "release_state": self.release_state.value,
            "authenticated": self.authenticated,
            "source_complete": self.source_complete,
            "source_generation": self.source_generation,
            "truncated": self.truncated,
            "conflict_reasons": list(self.conflict_reasons),
        }


def change_graph_evidence_from_snapshot(
    snapshot: OperationalContextSnapshot,
    *,
    expected_ontology_release: str,
) -> ChangeGraphEvidenceReceipt:
    """Project one exact operational context snapshot into graph assessment evidence."""

    if not expected_ontology_release.strip():
        raise ValueError("expected ontology release MUST be non-empty")
    catalog_versions = dict(snapshot.catalog_versions)
    graph_ontology_release = catalog_versions.get("ontology")
    release_state = GraphEvidenceReleaseState.UNKNOWN
    if graph_ontology_release is not None:
        release_state = (
            GraphEvidenceReleaseState.ALIGNED
            if graph_ontology_release == expected_ontology_release
            else GraphEvidenceReleaseState.MIXED
        )
    conflict_reasons = set(snapshot.conflicts)
    evidence_complete = True
    authenticated = bool(snapshot.evidence_links)
    for link in snapshot.evidence_links:
        identity = f"{link.link_type}:{link.from_id}:{link.to_id}"
        metadata = link.observation_metadata
        if metadata is None:
            authenticated = False
            evidence_complete = False
            conflict_reasons.add(f"link_evidence_missing:{identity}")
            continue
        fact = metadata.state_fact
        if not metadata.verified:
            authenticated = False
            conflict_reasons.add(f"link_evidence_unverified:{identity}")
        if fact.completeness < 1.0:
            evidence_complete = False
            conflict_reasons.add(f"link_evidence_incomplete:{identity}")
        if fact.conflicts:
            conflict_reasons.add(f"link_evidence_conflicting:{identity}")
        if fact.synthetic:
            conflict_reasons.add(f"link_evidence_synthetic:{identity}")
        if (
            fact.recorded_at > snapshot.cutoff
            or fact.evidence_cutoff > snapshot.cutoff
            or fact.effective_at > snapshot.cutoff
        ):
            conflict_reasons.add(f"link_evidence_after_cutoff:{identity}")
        elif (snapshot.cutoff - fact.effective_at).total_seconds() > fact.freshness_ceiling_seconds:
            conflict_reasons.add(f"link_evidence_stale:{identity}")

    freshness = GraphEvidenceFreshness.CURRENT
    if "target_resource_missing" in conflict_reasons:
        freshness = GraphEvidenceFreshness.UNAVAILABLE
    elif not snapshot.graph_source_complete or not evidence_complete:
        freshness = GraphEvidenceFreshness.UNKNOWN
    elif snapshot.stale_sources or any(
        reason.startswith("link_evidence_stale:") for reason in conflict_reasons
    ):
        freshness = GraphEvidenceFreshness.STALE
    elif any(
        reason.startswith(
            (
                "source_freshness_missing:",
                "source_after_",
                "link_evidence_after_",
            )
        )
        for reason in conflict_reasons
    ):
        freshness = GraphEvidenceFreshness.UNKNOWN
    return ChangeGraphEvidenceReceipt(
        graph_revision=snapshot.snapshot_id,
        freshness=freshness,
        release_state=release_state,
        authenticated=authenticated,
        source_complete=snapshot.graph_source_complete and evidence_complete,
        source_generation=snapshot.graph_source_generation,
        truncated="context_graph_truncated" in conflict_reasons,
        conflict_reasons=tuple(sorted(conflict_reasons)),
    )


@dataclass(frozen=True, slots=True)
class ChangeAssessment:
    change_id: str
    correlation_id: str
    target_ref: str
    occurred_at: datetime
    affected_set: AffectedSet
    graph_evidence: ChangeGraphEvidenceReceipt
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
            "graph_evidence": self.graph_evidence.to_mapping(),
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
        graph_evidence: ChangeGraphEvidenceReceipt,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> ChangeAssessment:
        change_id = _required_text(change, "id")
        correlation_id = _required_text(change, "correlation_id")
        target_ref = _required_text(change, "target_ref")
        occurred_at = _required_datetime(change, "occurred_at")
        combined_conflicts = (*graph_evidence.conflict_reasons, *unresolved_conflicts)
        affected = await self._analyzer.analyze(
            direct_target_ids=(target_ref,),
            bounds=self._traversal_bounds,
            graph_fresh=graph_evidence.freshness is GraphEvidenceFreshness.CURRENT,
            unresolved_conflicts=combined_conflicts,
        )
        reasons = list(affected.incomplete_reasons)
        reasons.extend(_graph_evidence_reasons(graph_evidence))
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
            graph_evidence=graph_evidence,
            reasons=normalized_reasons,
        )
        return ChangeAssessment(
            change_id=change_id,
            correlation_id=correlation_id,
            target_ref=target_ref,
            occurred_at=occurred_at,
            affected_set=affected,
            graph_evidence=graph_evidence,
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
    graph_evidence: ChangeGraphEvidenceReceipt,
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
        "graph_evidence": graph_evidence.to_mapping(),
        "reasons": reasons,
    }
    encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _graph_evidence_reasons(graph_evidence: ChangeGraphEvidenceReceipt) -> tuple[str, ...]:
    reasons: list[str] = []
    if not graph_evidence.authenticated:
        reasons.append("graph_receipt_unverified")
    if not graph_evidence.source_complete:
        reasons.append("graph_source_incomplete")
    if graph_evidence.release_state is GraphEvidenceReleaseState.MIXED:
        reasons.append("graph_release_mixed")
    elif graph_evidence.release_state is GraphEvidenceReleaseState.UNKNOWN:
        reasons.append("graph_release_unknown")
    if graph_evidence.freshness is GraphEvidenceFreshness.STALE:
        reasons.append("graph_stale")
    elif graph_evidence.freshness is GraphEvidenceFreshness.UNKNOWN:
        reasons.append("graph_freshness_unknown")
    elif graph_evidence.freshness is GraphEvidenceFreshness.UNAVAILABLE:
        reasons.append("graph_unavailable")
    if graph_evidence.truncated:
        reasons.append("graph_truncated")
    return tuple(reasons)


__all__ = [
    "ChangeAssessment",
    "ChangeAssessmentService",
    "ChangeGraphEvidenceReceipt",
    "change_graph_evidence_from_snapshot",
    "GraphEvidenceReleaseState",
]
