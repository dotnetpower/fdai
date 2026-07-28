"""Project architecture-review bindings into checklist evidence outcomes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.shared.contracts.models import (
    RequirementKind,
    RequirementOutcome,
    RequirementStatus,
)


@dataclass(frozen=True, slots=True)
class ArchitectureReviewChecklistEvidenceProvider:
    """Read immutable ARB owner and evidence bindings without granting authority."""

    manifest: Mapping[str, Any]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def outcomes_for_scope(self, scope: str) -> Sequence[RequirementOutcome]:
        if not scope.strip():
            raise ValueError("scope MUST be non-empty")
        review = _mapping(self.manifest.get("architecture_review"), "architecture_review")
        gate = _mapping(review.get("production_gate"), "production_gate")
        outcomes: list[RequirementOutcome] = []

        for raw in _sequence(review.get("artifacts"), "artifacts"):
            artifact = _mapping(raw, "artifact")
            status = str(artifact.get("status"))
            outcomes.append(
                RequirementOutcome(
                    kind=RequirementKind.ARTIFACT,
                    ref=str(artifact["id"]),
                    status=(
                        RequirementStatus.SATISFIED
                        if status == "ready"
                        else RequirementStatus.FAILED
                        if status == "blocked"
                        else RequirementStatus.UNKNOWN
                    ),
                    evidence_refs=tuple(str(item) for item in artifact.get("evidence", ())),
                )
            )

        evidence_bindings = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
        for raw_ref in _sequence(gate.get("required_evidence"), "required_evidence"):
            ref = str(raw_ref)
            binding = evidence_bindings.get(ref)
            status = (
                RequirementStatus.SATISFIED if binding is not None else RequirementStatus.UNKNOWN
            )
            observed_at = None
            evidence_refs: tuple[str, ...] = ()
            if binding is not None:
                bound = _mapping(binding, f"evidence_bindings.{ref}")
                observed_at = _timestamp(bound.get("approved_at"), f"evidence_bindings.{ref}")
                evidence_refs = (str(bound["uri"]),)
                expires_at = _timestamp(bound.get("expires_at"), f"evidence_bindings.{ref}")
                if expires_at <= self.clock():
                    status = RequirementStatus.FAILED
            for kind in (
                RequirementKind.ARTIFACT,
                RequirementKind.METRIC,
                RequirementKind.DRILL,
            ):
                outcomes.append(
                    RequirementOutcome(
                        kind=kind,
                        ref=ref,
                        status=status,
                        evidence_refs=evidence_refs,
                        observed_at=observed_at,
                    )
                )

        owner_bindings = _mapping(gate.get("owner_bindings"), "owner_bindings")
        for raw_ref in _sequence(gate.get("required_owner_slots"), "required_owner_slots"):
            ref = str(raw_ref)
            outcomes.append(
                RequirementOutcome(
                    kind=RequirementKind.APPROVAL,
                    ref=ref,
                    status=(
                        RequirementStatus.SATISFIED
                        if ref in owner_bindings
                        else RequirementStatus.UNKNOWN
                    ),
                )
            )
        return tuple(outcomes)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} MUST be a sequence")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label}.approved_at MUST be an ISO 8601 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label}.approved_at MUST be timezone-aware")
    return parsed


__all__ = ["ArchitectureReviewChecklistEvidenceProvider"]
