"""Versioned evidence completeness, never document admission or human authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HandoverSlot(StrEnum):
    """The six explicit responsibilities in the standard handover template."""

    SCOPE = "scope_exclusions"
    DECISIONS = "decision_triggers"
    RUNBOOK = "runbook_rollback"
    DEPENDENCIES = "dependencies_escalation"
    RISKS = "failure_risks"
    SOURCES = "source_governance"


HANDOVER_SLOTS = tuple(slot.value for slot in HandoverSlot)
CHECKLIST_VERSION = "1.0.0"


class HandoverReview(BaseModel):
    """Immutable human review over a specific goal revision and checklist digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewer_ref: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    goal_revision: Annotated[int, Field(strict=True, ge=1)]
    evidence_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reviewed_at: datetime

    @field_validator("reviewer_ref")
    @classmethod
    def _exact_reviewer(cls, value: str) -> str:
        if value != value.strip() or not value or any(char.isspace() for char in value):
            raise ValueError("handover reviewer MUST be an exact identity reference")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _aware_review(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("handover review time MUST include a timezone")
        return value


def checklist_slots(goal: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Validate explicitly assigned evidence slots; legacy unassigned evidence counts as none.

    A document may support several slots only through explicit separate assignments. Duplicate
    slots, conflicting exemptions, or malformed evidence fail closed instead of being counted.
    Every consumer must separately revalidate admission, current ACL, and source availability.
    """
    if goal.get("checklist_version") != CHECKLIST_VERSION:
        raise ValueError("handover checklist requires current versioned requirements")
    if goal.get("required_slots") != list(HANDOVER_SLOTS):
        raise ValueError("handover checklist requirements are incomplete or reordered")
    raw = goal.get("evidence", [])
    exemptions = goal.get("slot_exemptions", {})
    if not isinstance(raw, list) or len(raw) > 64 or not isinstance(exemptions, Mapping):
        raise ValueError("handover checklist evidence is malformed")
    slots: dict[str, dict[str, str]] = {}
    for evidence in raw:
        if not isinstance(evidence, Mapping):
            raise ValueError("handover evidence item MUST be an object")
        slot = evidence.get("slot")
        if slot is None:
            continue
        key = HandoverSlot(slot).value
        if key in slots:
            raise ValueError("handover slot already contains evidence")
        reference, digest, kind = (
            evidence.get(field) for field in ("evidence_ref", "digest", "kind")
        )
        if (
            not isinstance(reference, str)
            or not reference.startswith("doc:")
            or not 1 <= len(reference) <= 256
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or kind not in {"document", "document_span"}
        ):
            raise ValueError("handover slot requires an immutable document reference and digest")
        slots[key] = {"evidence_ref": reference, "digest": digest, "kind": str(kind)}
    for slot, reason in exemptions.items():
        key = HandoverSlot(slot).value
        if key in slots or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("not-applicable slot requires a distinct bounded reason")
        slots[key] = {"reason_ref": reason.strip()}
    return slots


def checklist_digest(goal: Mapping[str, Any]) -> str:
    """Bind review to the exact subject, ownership, scope, template, impact and six slots."""
    slots = checklist_slots(goal)
    high_impact = goal.get("high_impact")
    if type(high_impact) is not bool:
        raise ValueError("handover impact classification is unavailable")
    content = {
        key: goal.get(key)
        for key in (
            "goal_id",
            "subject_ref",
            "assignment_case_id",
            "agent_name",
            "scope_ref",
            "source_revision",
            "prompt_ref",
            "checklist_version",
            "required_slots",
            "high_impact",
        )
    }
    content["slots"] = slots
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def checklist_complete(goal: Mapping[str, Any]) -> bool:
    """Return completeness only, not acceptance or permission to use the facts."""
    return set(checklist_slots(goal)) == set(HANDOVER_SLOTS)


def acceptance_complete(goal: Mapping[str, Any]) -> bool:
    """Check digest-bound distinct review records; callers still prove current reviewer roles."""
    if not checklist_complete(goal):
        return False
    digest = checklist_digest(goal)
    owner = goal.get("owner_review")
    if not _review_matches(owner, digest, goal):
        return False
    if goal["high_impact"] is False:
        return True
    backup = goal.get("backup_review")
    return (
        _review_matches(backup, digest, goal)
        and isinstance(owner, Mapping)
        and isinstance(backup, Mapping)
        and owner["reviewer_ref"].casefold() != backup["reviewer_ref"].casefold()
    )


def checklist_defaults(*, high_impact: bool = True) -> dict[str, Any]:
    """Return conservative new-goal requirements; unknown impact requires backup review."""
    return {
        "checklist_version": CHECKLIST_VERSION,
        "required_slots": list(HANDOVER_SLOTS),
        "slot_exemptions": {},
        "high_impact": high_impact,
        "owner_review": None,
        "backup_review": None,
    }


def project_checklist(goal: Mapping[str, Any]) -> dict[str, Any]:
    """Keep legacy evidence readable without projecting its old acceptance as current.

    This is a negative-only read projection, not a history rewrite. A later authenticated,
    revision-fenced evidence command adopts the checklist in its ordinary audited transaction.
    Unknown versions and inconsistent current acceptance are unavailable, never auto-repaired.
    """
    projected = dict(goal)
    version = goal.get("checklist_version")
    if version in {None, "legacy"}:
        projected.update(checklist_defaults())
        if goal.get("state") in {"accepted", "ready_for_review"}:
            projected.update(state="blocked", legacy_state=goal["state"])
    elif version != CHECKLIST_VERSION:
        raise ValueError("handover checklist version is unsupported")
    checklist_slots(projected)
    if projected.get("state") == "accepted" and not acceptance_complete(projected):
        raise ValueError("accepted handover lacks valid current checklist reviews")
    return projected


def evidence_documents(goal: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Return bounded document evidence after checklist validation for an admission reader."""
    checklist_slots(goal)
    return tuple(item for item in goal["evidence"] if item.get("slot") is not None)


def _review_matches(value: object, digest: str, goal: Mapping[str, Any]) -> bool:
    try:
        review = HandoverReview.model_validate(value)
    except ValueError:
        return False
    revision = goal.get("revision")
    return (
        review.evidence_digest == digest
        and type(revision) is int
        and review.goal_revision < revision
        and review.reviewer_ref.casefold() != str(goal.get("subject_ref", "")).strip().casefold()
    )


__all__ = [
    "CHECKLIST_VERSION",
    "HANDOVER_SLOTS",
    "HandoverReview",
    "HandoverSlot",
    "acceptance_complete",
    "checklist_complete",
    "checklist_defaults",
    "checklist_digest",
    "checklist_slots",
    "evidence_documents",
    "project_checklist",
]
