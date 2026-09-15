"""Pure six-slot changes and independently attributed goal reviews; no provider I/O."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_operator_service.families.iam.contracts import HandoverGoalCommand
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_service_contracts.handover_checklist import (
    HandoverSlot,
    acceptance_complete,
    checklist_complete,
    checklist_defaults,
    checklist_digest,
    checklist_slots,
)


def transition_checklist(
    current: Mapping[str, Any], *, command: HandoverGoalCommand, now: datetime
) -> dict[str, Any]:
    """Apply one checklist command after the caller's current identity and document checks.

    Legacy unassigned documents remain visible but cannot satisfy the new checklist. Updating
    evidence invalidates previous review digests; accepted and terminal goals cannot be reopened.
    """
    if current.get("state") in {"accepted", "stale", "declined", "superseded"}:
        raise IamConflictError("handover goal is closed to evidence and review commands")
    updated = {**current, "revision": command.expected_revision + 1}
    if current.get("checklist_version") is None:
        updated.update(checklist_defaults())
    try:
        checklist_slots(updated)
        slot = HandoverSlot(command.slot).value if command.slot is not None else None
        if command.operation == "evidence":
            evidence = list(updated.get("evidence", []))
            if any(
                item.get("slot") == slot and item.get("evidence_ref") == command.evidence_ref
                for item in evidence
            ):
                raise ValueError("handover evidence reference already exists in this slot")
            if slot is not None and slot in checklist_slots(updated):
                raise ValueError("handover slot is already satisfied")
            evidence.append(
                {
                    "evidence_ref": command.evidence_ref,
                    "digest": command.digest,
                    "kind": command.kind,
                    **({"slot": slot} if slot is not None else {}),
                }
            )
            updated.update(evidence=evidence, owner_review=None, backup_review=None)
        elif command.operation == "not-applicable":
            if slot is None or not command.reason_ref or not command.reason_ref.strip():
                raise ValueError("not-applicable requires an explicit slot and reason reference")
            if slot in checklist_slots(updated):
                raise ValueError("handover slot is already satisfied")
            updated.update(
                slot_exemptions={**updated.get("slot_exemptions", {}), slot: command.reason_ref},
                owner_review=None,
                backup_review=None,
            )
        elif command.operation in {"accept", "acknowledge"}:
            if current.get("state") != "ready_for_review" or not checklist_complete(updated):
                raise ValueError("handover goal requires all six evidence slots before review")
            field = "owner_review" if command.operation == "accept" else "backup_review"
            other = updated.get("backup_review" if field == "owner_review" else "owner_review")
            actor = command.principal.oid.strip().casefold()
            if (
                isinstance(other, Mapping)
                and str(other.get("reviewer_ref", "")).casefold() == actor
            ):
                raise ValueError("Owner and backup reviews require distinct people")
            if updated.get(field) is not None:
                raise ValueError("handover review already exists for this evidence revision")
            updated[field] = {
                "reviewer_ref": actor,
                "goal_revision": command.expected_revision,
                "evidence_digest": checklist_digest(updated),
                "reviewed_at": now.isoformat(),
            }
        else:
            raise ValueError("unsupported checklist operation")
        updated["state"] = (
            "accepted"
            if acceptance_complete(updated)
            else "ready_for_review"
            if checklist_complete(updated)
            else "in_progress"
        )
        updated["snoozed_until"] = None
        return updated
    except (TypeError, ValueError) as exc:
        raise IamConflictError(str(exc)) from exc


__all__ = ["transition_checklist"]
