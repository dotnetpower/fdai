"""Server-owned proactive handover invitations and revisioned goal state."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_operator_service.families.iam.contracts import (
    HandoverGoalCommand,
    HumanIdentityDirectory,
    JsonMapping,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.families.operations.contracts import ProjectionQuery, ProjectionReader
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)
from fdai_service_contracts import OperatorRole

_GOAL_PREFIX = "operator-handover-goal:"
_INVITATION_PREFIX = "operator-handover-invitation:"
_WEEK_PREFIX = "operator-handover-week:"
_MAX_WEEKLY_INVITATIONS = 2
_MAX_CAS_ATTEMPTS = 4
_MAX_GOALS = 15
_DOCUMENT_REF = re.compile(
    r"^doc:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HandoverStateStore(Protocol):
    """Small durable state surface required by proactive handover."""

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool: ...

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ProactiveHandoverRuntime:
    """Create one bounded invitation from the authoritative ownership projection."""

    store: HandoverStateStore
    ownership: ProjectionReader
    directory: HumanIdentityDirectory
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        roles: frozenset[OperatorRole],
        session_id: str,
    ) -> JsonMapping | None:
        now = _aware(self.clock())
        agents, source_revision = await self._mapped_agents(subject_ref=subject_ref, roles=roles)
        invitation_key = f"{_INVITATION_PREFIX}{_digest(f'{subject_ref}\0{session_id}')}"
        existing = await self._read(invitation_key)
        if existing is not None:
            goal_id = existing.get("goal_id")
            agent_name = existing.get("agent_name")
            if (
                not isinstance(goal_id, str)
                or agent_name not in agents
                or not _goal_is_invitable(
                    await self._read_required(f"{_GOAL_PREFIX}{goal_id}"),
                    now=now,
                )
            ):
                return None
            return existing

        for agent_name in agents[:_MAX_GOALS]:
            goal_id = _digest(f"{subject_ref}\0{agent_name}\0{source_revision}")
            goal_key = f"{_GOAL_PREFIX}{goal_id}"
            goal = await self._read(goal_key)
            if goal is None:
                candidate = _new_goal(
                    goal_id=goal_id,
                    subject_ref=subject_ref,
                    agent_name=agent_name,
                    source_revision=source_revision,
                    now=now,
                )
                await self._create(goal_key, candidate)
                goal = await self._read(goal_key) or candidate
            if not _goal_is_invitable(goal, now=now):
                continue
            if not await self._claim_week(subject_ref=subject_ref, session_id=session_id, now=now):
                return None
            invitation = {
                "invitation_id": _digest(f"{subject_ref}\0{session_id}\0{goal_id}"),
                "goal_id": goal_id,
                "goal_revision": _positive_int(goal, "revision"),
                "subject_ref": subject_ref,
                "agent_name": agent_name,
                "prompt_ref": str(goal["prompt_ref"]),
                "session_id": session_id,
                "max_questions": 3,
                "max_minutes": 5,
                "source_revision": source_revision,
                "created_at": now.isoformat(),
                "execution_authority": False,
            }
            await self._create(invitation_key, invitation)
            return await self._read(invitation_key) or invitation
        return None

    async def get_goal(self, goal_id: str) -> JsonMapping:
        goal = await self._read(f"{_GOAL_PREFIX}{goal_id}")
        if goal is None:
            raise IamNotFoundError(f"handover goal {goal_id!r} was not found")
        return goal

    async def submit(self, command: HandoverGoalCommand) -> JsonMapping:
        current = dict(await self.get_goal(command.goal_id))
        if (
            current.get("revision") == command.expected_revision + 1
            and current.get("last_operation") == command.operation
            and current.get("last_expected_revision") == command.expected_revision
            and current.get("last_actor") == command.principal.oid
        ):
            return current
        if _positive_int(current, "revision") != command.expected_revision:
            raise IamConflictError("handover goal revision is stale")
        if (
            str(current.get("subject_ref")) != command.principal.oid
            and command.operation != "accept"
        ):
            raise IamConflictError("handover goal belongs to another subject")
        updated = _transition(current, command=command, now=_aware(self.clock()))
        try:
            await self.store.append_revisioned_proposal(
                family="iam",
                operation=f"handover.{command.operation}",
                principal_id=command.principal.oid,
                idempotency_key=(
                    f"handover:{command.goal_id}:{command.operation}:{command.expected_revision}"
                ),
                payload={
                    "goal_id": command.goal_id,
                    "operation": command.operation,
                    "expected_revision": command.expected_revision,
                    "execution_authority": False,
                },
                state_key=f"{_GOAL_PREFIX}{command.goal_id}",
                state_value=updated,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError("handover goal revision is stale") from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("handover goal state is unavailable") from exc
        return dict(await self.get_goal(command.goal_id))

    async def _mapped_agents(
        self,
        *,
        subject_ref: str,
        roles: frozenset[OperatorRole],
    ) -> tuple[tuple[str, ...], str]:
        try:
            payload = await self.ownership.read(
                ProjectionQuery(
                    operation="stewardship.coverage",
                    principal_id=subject_ref,
                    path={},
                    params={},
                    limit=100,
                    cursor=None,
                    roles=roles,
                    purpose="knowledge-handover",
                )
            )
            current = payload.get("current_ownership")
            if isinstance(current, Mapping):
                source_revision = str(current.get("source_revision") or "unversioned")
                agents = _sequence(current.get("agents"), "current ownership agents")
                current_shape = True
            else:
                stewardship = _mapping(payload.get("map"), "stewardship map")
                source_revision = str(payload.get("_revision") or "unversioned")
                agents = _sequence(stewardship.get("agents"), "stewardship agents")
                current_shape = False
        except (TypeError, ValueError, RuntimeError) as exc:
            raise IamUnavailableError("current ownership projection is unavailable") from exc

        try:
            identity = await self.directory.get_by_subject_id(subject_ref)
        except (RuntimeError, IamUnavailableError) as exc:
            raise IamUnavailableError("human identity directory is unavailable") from exc
        if identity is None or not identity.active:
            return (), source_revision
        matched: list[tuple[int, str]] = []
        duty_order = {"primary": 0, "backup": 1, "escalation": 2}
        for value in agents:
            agent = _mapping(value, "current ownership agent")
            name = agent.get("name")
            if not isinstance(name, str) or not name:
                raise IamUnavailableError("current ownership agent identity is malformed")
            raw_subjects = agent.get("subjects") if current_shape else agent.get("stewards")
            for raw_subject in _sequence(raw_subjects, "ownership subjects"):
                subject = _mapping(raw_subject, "ownership subject")
                if (
                    subject.get("kind") == "user"
                    and (subject.get("subject_id") if current_shape else subject.get("id"))
                    == subject_ref
                    and subject.get("responsibility") == "accountable"
                    and (not current_shape or subject.get("active") is True)
                ):
                    matched.append((duty_order.get(str(subject.get("duty")), 3), name))
                    break
        matched.sort(key=lambda item: (item[0], item[1]))
        return tuple(name for _duty, name in matched), source_revision

    async def _claim_week(self, *, subject_ref: str, session_id: str, now: datetime) -> bool:
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        subject_hash = _digest(subject_ref)
        session_hash = _digest(session_id)
        key = f"{_WEEK_PREFIX}{subject_hash}:{week}"
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            current = await self._read(key)
            revision = 0 if current is None else _non_negative_int(current, "revision")
            sessions = [] if current is None else _string_list(current, "sessions")
            if session_hash in sessions:
                return True
            if len(sessions) >= _MAX_WEEKLY_INVITATIONS:
                return False
            updated = {
                "revision": revision + 1,
                "week": week,
                "sessions": [*sessions, session_hash],
                "updated_at": now.isoformat(),
            }
            try:
                await self.store.append_revisioned_proposal(
                    family="iam",
                    operation="handover.invitation.claim",
                    principal_id=subject_ref,
                    idempotency_key=f"handover-week:{subject_hash}:{week}:{session_hash}",
                    payload={
                        "week": week,
                        "session_hash": session_hash,
                        "execution_authority": False,
                    },
                    state_key=key,
                    state_value=updated,
                    expected_revision=revision,
                )
                return True
            except PostgresProposalConflict:
                continue
            except PostgresFamilyStoreUnavailable as exc:
                raise IamUnavailableError("handover invitation state is unavailable") from exc
        raise IamConflictError("handover invitation budget changed concurrently")

    async def _read(self, key: str) -> dict[str, object] | None:
        try:
            return await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("handover state is unavailable") from exc

    async def _read_required(self, key: str) -> dict[str, object]:
        value = await self._read(key)
        if value is None:
            raise IamUnavailableError("handover state is incomplete")
        return value

    async def _create(self, key: str, value: Mapping[str, object]) -> bool:
        try:
            return await self.store.create_state(key, value)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("handover state is unavailable") from exc


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
        "prompt_ref": "handover.goal.default-v1",
        "priority": 100,
        "state": "not_started",
        "revision": 1,
        "evidence": [],
        "not_applicable_reason_ref": None,
        "snoozed_until": None,
        "created_at": now.isoformat(),
        "execution_authority": False,
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
    elif operation == "not-applicable":
        if not command.reason_ref:
            raise IamConflictError("not-applicable requires a reason reference")
        updated.update(
            state="ready_for_review",
            not_applicable_reason_ref=command.reason_ref,
            snoozed_until=None,
        )
    elif operation == "evidence":
        if not command.evidence_ref or not command.digest or not command.kind:
            raise IamConflictError("evidence requires reference, digest, and kind")
        if (
            command.kind != "document"
            or _DOCUMENT_REF.fullmatch(command.evidence_ref) is None
            or _SHA256.fullmatch(command.digest) is None
        ):
            raise IamConflictError("handover evidence is not a canonical document receipt")
        evidence = _sequence(current.get("evidence"), "handover goal evidence")
        if any(
            isinstance(item, Mapping) and item.get("evidence_ref") == command.evidence_ref
            for item in evidence
        ):
            raise IamConflictError("handover evidence reference already exists")
        updated.update(
            state="ready_for_review",
            evidence=[
                *evidence,
                {
                    "evidence_ref": command.evidence_ref,
                    "digest": command.digest,
                    "kind": command.kind,
                },
            ],
            snoozed_until=None,
        )
    elif operation == "accept":
        if current.get("state") != "ready_for_review":
            raise IamConflictError("handover goal is not ready for review")
        updated.update(state="accepted", snoozed_until=None)
    else:
        raise IamNotFoundError("unknown handover goal command")
    return updated


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


__all__ = ["ProactiveHandoverRuntime"]
