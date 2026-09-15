"""Pure handover goal transitions and state validation; no provider I/O."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai_operator_service.families.iam.contracts import HandoverGoalCommand
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.families.iam.handover_acceptance import transition_checklist
from fdai_service_contracts.handover_checklist import checklist_defaults

_DOCUMENT_REF = re.compile(
    r"^doc:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _new_goal(
    *,
    goal_id: str,
    subject_ref: str,
    agent_name: str,
    source_revision: str,
    now: datetime,
) -> dict[str, object]:
    return {
        "goal_id": goal_id,
        "subject_ref": subject_ref,
        "agent_name": agent_name,
        "scope_ref": "scope://stewardship/current",
        "source_revision": source_revision,
        "prompt_ref": f"handover.goal.{agent_name.casefold()}-v1",
        "priority": 100,
        "state": "not_started",
        "revision": 1,
        "evidence": [],
        "not_applicable_reason_ref": None,
        "snoozed_until": None,
        "created_at": now.isoformat(),
        "execution_authority": False,
        **checklist_defaults(),
    }


def _goal_is_invitable(goal: Mapping[str, object], *, now: datetime) -> bool:
    if goal.get("state") not in {"not_started", "in_progress"}:
        return False
    snoozed = goal.get("snoozed_until")
    if snoozed is None:
        return True
    if not isinstance(snoozed, str):
        raise IamUnavailableError("handover goal snooze state is malformed")
    return _aware(datetime.fromisoformat(snoozed)) <= now


def _transition(
    current: dict[str, object],
    *,
    command: HandoverGoalCommand,
    now: datetime,
) -> dict[str, object]:
    operation = command.operation
    updated = {
        **current,
        "revision": command.expected_revision + 1,
        "updated_at": now.isoformat(),
        "last_operation": command.operation,
        "last_expected_revision": command.expected_revision,
        "last_actor": command.principal.oid,
    }
    if operation == "snooze":
        updated.update(state="in_progress", snoozed_until=(now + timedelta(hours=24)).isoformat())
    elif operation == "decline":
        updated.update(state="declined", snoozed_until=None)
    elif operation == "reuse":
        updated.update(checklist_defaults())
    elif operation in {"not-applicable", "evidence", "accept", "acknowledge"}:
        updated.update(transition_checklist(current, command=command, now=now))
        updated["revision"] = command.expected_revision + 1
    else:
        raise IamNotFoundError("unknown handover goal command")
    updated.update(
        revision=command.expected_revision + 1,
        updated_at=now.isoformat(),
        last_operation=command.operation,
        last_expected_revision=command.expected_revision,
        last_actor=command.principal.oid,
    )
    return updated


def _document_receipt(command: HandoverGoalCommand) -> tuple[UUID, UUID]:
    if (
        command.kind != "document"
        or command.evidence_ref is None
        or _DOCUMENT_REF.fullmatch(command.evidence_ref) is None
        or command.digest is None
        or _SHA256.fullmatch(command.digest) is None
    ):
        raise IamConflictError("handover evidence is not a canonical document receipt")
    _, document_id, version_id = command.evidence_ref.split(":", 2)
    return UUID(document_id), UUID(version_id)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise IamUnavailableError(f"{label} is malformed")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise IamUnavailableError(f"{label} is malformed")
    return value


def _positive_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise IamUnavailableError(f"handover goal {key} is malformed")
    return item


def _non_negative_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise IamUnavailableError(f"handover invitation {key} is malformed")
    return item


def _string_list(value: Mapping[str, object], key: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
        raise IamUnavailableError(f"handover invitation {key} is malformed")
    return list(item)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("handover time MUST be timezone-aware")
    return value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
