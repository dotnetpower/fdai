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
                    scope=scope,
                    evidence_refs=tuple(str(item) for item in artifact.get("evidence", ())),
                )
            )

        evidence_kinds = _mapping(gate.get("evidence_kinds"), "evidence_kinds")
        evidence_bindings = _mapping(
            gate.get("checklist_evidence_bindings"),
            "checklist_evidence_bindings",
        )
        not_applicable_bindings = _mapping(
            gate.get("not_applicable_bindings"),
            "not_applicable_bindings",
        )
        for raw_ref in _sequence(
            gate.get("checklist_required_evidence"),
            "checklist_required_evidence",
        ):
            ref = str(raw_ref)
            kind = RequirementKind(str(evidence_kinds.get(ref)))
            binding = evidence_bindings.get(ref)
            not_applicable = not_applicable_bindings.get(ref)
            if binding is not None and not_applicable is not None:
                raise ValueError(f"{ref!r} MUST NOT have both evidence and not-applicable bindings")
            status = (
                RequirementStatus.NOT_APPLICABLE
                if not_applicable is not None
                else RequirementStatus.SATISFIED
                if binding is not None
                else RequirementStatus.UNKNOWN
            )
            observed_at = None
            recorded_at = None
            source_identity = None
            evidence_digest = None
            evidence_refs: tuple[str, ...] = ()
            not_applicable_reason = None
            not_applicable_approved_by = None
            if binding is not None:
                bound = _mapping(binding, f"checklist_evidence_bindings.{ref}")
                _require_binding_scope_and_kind(
                    bound,
                    expected_scope=scope,
                    expected_kind=kind,
                    label=f"checklist_evidence_bindings.{ref}",
                )
                observed_at = _timestamp(
                    bound.get("observed_at"),
                    f"checklist_evidence_bindings.{ref}.observed_at",
                )
                recorded_at = _timestamp(
                    bound.get("recorded_at"),
                    f"checklist_evidence_bindings.{ref}.recorded_at",
                )
                source_identity = _required_text(
                    bound.get("source_identity"),
                    f"checklist_evidence_bindings.{ref}.source_identity",
                )
                evidence_digest = _sha256(
                    bound.get("sha256"),
                    f"checklist_evidence_bindings.{ref}.sha256",
                )
                evidence_refs = (str(bound["uri"]),)
                expires_at = _timestamp(
                    bound.get("expires_at"),
                    f"checklist_evidence_bindings.{ref}.expires_at",
                )
                if expires_at <= self.clock():
                    status = RequirementStatus.FAILED
            if not_applicable is not None:
                bound = _mapping(
                    not_applicable,
                    f"not_applicable_bindings.{ref}",
                )
                _require_binding_scope_and_kind(
                    bound,
                    expected_scope=scope,
                    expected_kind=kind,
                    label=f"not_applicable_bindings.{ref}",
                )
                observed_at = _timestamp(
                    bound.get("approved_at"),
                    f"not_applicable_bindings.{ref}.approved_at",
                )
                recorded_at = observed_at
                source_identity = _required_text(
                    bound.get("source_identity"),
                    f"not_applicable_bindings.{ref}.source_identity",
                )
                evidence_digest = _sha256(
                    bound.get("sha256"),
                    f"not_applicable_bindings.{ref}.sha256",
                )
                evidence_refs = (str(bound["uri"]),)
                not_applicable_reason = _required_text(
                    bound.get("justification"),
                    f"not_applicable_bindings.{ref}.justification",
                )
                not_applicable_approved_by = _required_text(
                    bound.get("approved_by"),
                    f"not_applicable_bindings.{ref}.approved_by",
                )
                if source_identity == not_applicable_approved_by:
                    status = RequirementStatus.UNKNOWN
                expires_at = _timestamp(
                    bound.get("expires_at"),
                    f"not_applicable_bindings.{ref}.expires_at",
                )
                if expires_at <= self.clock():
                    status = RequirementStatus.FAILED
            outcomes.append(
                RequirementOutcome(
                    kind=kind,
                    ref=ref,
                    status=status,
                    scope=scope,
                    evidence_refs=evidence_refs,
                    observed_at=observed_at,
                    recorded_at=recorded_at,
                    source_identity=source_identity,
                    evidence_digest=evidence_digest,
                    not_applicable_reason=not_applicable_reason,
                    not_applicable_approved_by=not_applicable_approved_by,
                )
            )

        approval_bindings = _mapping(gate.get("approval_bindings"), "approval_bindings")
        for raw_ref in _sequence(gate.get("required_owner_slots"), "required_owner_slots"):
            ref = str(raw_ref)
            binding = approval_bindings.get(ref)
            status = RequirementStatus.UNKNOWN
            approval_observed_at = None
            approval_evidence_refs: tuple[str, ...] = ()
            approval_source_identity = None
            approval_evidence_digest = None
            if binding is not None:
                bound = _mapping(binding, f"approval_bindings.{ref}")
                if _required_text(bound.get("scope"), f"approval_bindings.{ref}.scope") != scope:
                    raise ValueError(f"approval_bindings.{ref}.scope does not match request scope")
                approval_observed_at = _timestamp(
                    bound.get("approved_at"),
                    f"approval_bindings.{ref}.approved_at",
                )
                expires_at = _timestamp(
                    bound.get("expires_at"),
                    f"approval_bindings.{ref}.expires_at",
                )
                approval_source_identity = _required_text(
                    bound.get("approved_by"),
                    f"approval_bindings.{ref}.approved_by",
                )
                approval_evidence_digest = _sha256(
                    bound.get("sha256"),
                    f"approval_bindings.{ref}.sha256",
                )
                approval_evidence_refs = (str(bound["uri"]),)
                status = (
                    RequirementStatus.FAILED
                    if expires_at <= self.clock()
                    else RequirementStatus.SATISFIED
                )
            outcomes.append(
                RequirementOutcome(
                    kind=RequirementKind.APPROVAL,
                    ref=ref,
                    status=status,
                    scope=scope,
                    evidence_refs=approval_evidence_refs,
                    observed_at=approval_observed_at,
                    recorded_at=approval_observed_at,
                    source_identity=approval_source_identity,
                    evidence_digest=approval_evidence_digest,
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
        raise ValueError(f"{label} MUST be an ISO 8601 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} MUST be timezone-aware")
    return parsed


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} MUST be a non-empty string")
    return value.strip()


def _sha256(value: Any, label: str) -> str:
    digest = _required_text(value, label)
    if len(digest) != 71 or not digest.startswith("sha256:"):
        raise ValueError(f"{label} MUST be a sha256 digest")
    try:
        int(digest[7:], 16)
    except ValueError as exc:
        raise ValueError(f"{label} MUST be a sha256 digest") from exc
    return digest


def _require_binding_scope_and_kind(
    binding: Mapping[str, Any],
    *,
    expected_scope: str,
    expected_kind: RequirementKind,
    label: str,
) -> None:
    scope = _required_text(binding.get("scope"), f"{label}.scope")
    kind = RequirementKind(_required_text(binding.get("kind"), f"{label}.kind"))
    if scope != expected_scope:
        raise ValueError(f"{label}.scope does not match request scope")
    if kind is not expected_kind:
        raise ValueError(f"{label}.kind does not match declared evidence kind")


__all__ = ["ArchitectureReviewChecklistEvidenceProvider"]
