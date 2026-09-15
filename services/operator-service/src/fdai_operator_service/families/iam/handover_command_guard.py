"""Pure authority and replay checks for server-owned handover goal commands."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from fdai_operator_service.families.iam.contracts import HandoverGoalCommand
from fdai_operator_service.families.iam.errors import IamConflictError, IamPermissionError
from fdai_service_contracts import OperatorRole


def authorize_goal_command(goal: Mapping[str, object], command: HandoverGoalCommand) -> str:
    """Return the exact goal subject after independent review or subject checks.

    This complements HTTP authorization at the durable command boundary. It never interprets
    ownership, grants a role, or treats a content digest as authorization.
    """
    subject = goal.get("subject_ref")
    if not isinstance(subject, str) or not subject.strip():
        raise IamConflictError("handover goal ownership is unavailable")
    same_subject = subject.strip().casefold() == command.principal.oid.strip().casefold()
    if command.operation == "accept":
        if OperatorRole.OWNER not in command.principal.roles or same_subject:
            raise IamPermissionError("independent Owner review is required")
    elif command.operation == "acknowledge":
        if same_subject or not command.principal.roles - {OperatorRole.BREAK_GLASS}:
            raise IamPermissionError("independent current backup acknowledgement is required")
    elif command.operation not in {"snooze", "decline", "not-applicable", "evidence", "reuse"}:
        raise IamConflictError("unknown handover goal command")
    elif not same_subject:
        raise IamPermissionError("handover goal belongs to another subject")
    return subject


def goal_command_digest(command: HandoverGoalCommand) -> str:
    """Bind replay identity to the entire command without retaining evidence content."""
    payload = {
        "goal_id": command.goal_id,
        "actor": command.principal.oid.casefold(),
        "operation": command.operation,
        "expected_revision": command.expected_revision,
        "reason_ref": command.reason_ref,
        "evidence_ref": command.evidence_ref,
        "digest": command.digest,
        "kind": command.kind,
        **({"slot": command.slot} if command.slot is not None else {}),
        **(
            {"source_goal_id": command.source_goal_id} if command.source_goal_id is not None else {}
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["authorize_goal_command", "goal_command_digest"]
