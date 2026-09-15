"""Durable per-human handover session and turn budgets, before narration starts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from fdai_operator_service.families.conversation.contracts import ConversationProposal
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_operator_service.postgres_family_store import PostgresProposalConflict


class SessionBudgetStore(Protocol):
    """The owning Operator store atomically commits budget state and its proposal audit."""

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
class HandoverSessionBudget:
    """Reserve three turns, five non-sliding minutes, and two distinct sessions per ISO week.

    A failed or cancelled model turn still consumes its reservation. Historical session windows
    prevent reopening an expired session id. Source/identity checks belong to the caller and run
    before every admission, including an exact replay. This record grants no model authority.
    """

    store: SessionBudgetStore

    async def claim(self, proposal: ConversationProposal, *, goal_id: str, now: datetime) -> str:
        """Return this exact turn's fixed deadline, or hold without dispatching narration."""
        if now.utcoffset() is None:
            raise ValueError("handover budget clock MUST include a timezone")
        now = now.astimezone(UTC)
        subject = _hash(proposal.scope.subject_id.strip().casefold())
        session = _hash(str(proposal.body["session_id"]))
        request = _hash(proposal.idempotency_key)
        digest = _hash(
            json.dumps(
                {
                    "operation": proposal.operation,
                    "body": proposal.body,
                    "query": proposal.query,
                    "path": proposal.path_params,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        key = f"operator-handover-session-budget:{subject}"
        history_key = f"operator-handover-session-ended:{subject}:{session}"
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        requested_deadline = now + timedelta(seconds=90)
        if proposal.body.get("deadline_at") is not None:
            requested_deadline = min(requested_deadline, _time(proposal.body["deadline_at"]))
        for _ in range(4):
            current = cast(dict[str, Any] | None, await self.store.read_state(key))
            candidate: dict[str, Any]
            revision = 0
            sessions: list[str] = []
            if current is not None:
                _validate(current, subject)
                if now < _time(current["started_at"]):
                    raise IamConflictError("handover budget clock moved before session start")
                revision = int(current["revision"])
                if current["week"] == week:
                    sessions = list(current["sessions"])
                if current["session"] == session:
                    if now >= _time(current["deadline_at"]):
                        raise IamConflictError("handover session time budget is exhausted")
                    if current["goal_id"] != goal_id:
                        raise IamConflictError("handover session is bound to another goal")
                    records = dict(current["requests"])
                    if request in records:
                        record = records[request]
                        if record["digest"] != digest:
                            raise IamConflictError("handover turn replay payload conflicts")
                        if now >= _time(record["deadline_at"]):
                            raise IamConflictError("handover turn deadline is exhausted")
                        return str(record["deadline_at"])
                    if len(records) >= 3:
                        raise IamConflictError("handover session question budget is exhausted")
                    deadline = min(requested_deadline, _time(current["deadline_at"]))
                    candidate = {**current, "requests": records}
                else:
                    if now < _time(current["deadline_at"]):
                        raise IamConflictError("another handover session is active for this person")
                    old_key = f"operator-handover-session-ended:{subject}:{current['session']}"
                    await self.store.create_state(old_key, {"deadline_at": current["deadline_at"]})
                    candidate = {}
            else:
                candidate = {}
            if not candidate:
                if await self.store.read_state(history_key) is not None:
                    raise IamConflictError("handover session has already ended")
                if len(sessions) >= 2:
                    raise IamConflictError("handover weekly session budget is exhausted")
                deadline = min(requested_deadline, now + timedelta(minutes=5))
                candidate = {
                    "subject": subject,
                    "session": session,
                    "goal_id": goal_id,
                    "started_at": now.isoformat(),
                    "deadline_at": (now + timedelta(minutes=5)).isoformat(),
                    "week": week,
                    "sessions": [*sessions, session],
                    "requests": {},
                }
            if deadline <= now:
                raise IamConflictError("handover turn deadline is exhausted")
            candidate["requests"][request] = {"digest": digest, "deadline_at": deadline.isoformat()}
            candidate["revision"] = revision + 1
            try:
                await self.store.append_revisioned_proposal(
                    family="iam",
                    operation="handover.session.turn_claimed",
                    principal_id=proposal.scope.subject_id,
                    idempotency_key=f"handover-turn:{subject}:{session}:{request}",
                    payload={
                        "goal_id": goal_id,
                        "session": session,
                        "request": request,
                        "digest": digest,
                        "execution_authority": False,
                    },
                    state_key=key,
                    state_value=candidate,
                    expected_revision=revision,
                )
            except PostgresProposalConflict:
                continue
            saved = cast(dict[str, Any] | None, await self.store.read_state(key))
            if saved is None or saved.get("session") != session:
                raise IamConflictError("handover session reservation did not converge")
            _validate(saved, subject)
            recorded = saved["requests"].get(request)
            if not isinstance(recorded, Mapping) or recorded.get("digest") != digest:
                raise IamConflictError("handover turn reservation did not converge")
            return str(recorded["deadline_at"])
        raise IamConflictError("handover session budget changed concurrently")


def _validate(value: Mapping[str, Any], subject: str) -> None:
    if (
        value.get("subject") != subject
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or not isinstance(value.get("session"), str)
        or not isinstance(value.get("goal_id"), str)
        or not isinstance(value.get("week"), str)
        or not isinstance(value.get("sessions"), list)
        or not 1 <= len(value["sessions"]) <= 2
        or any(not isinstance(item, str) for item in value["sessions"])
        or len(set(value["sessions"])) != len(value["sessions"])
        or value["session"] not in value["sessions"]
        or not isinstance(value.get("requests"), dict)
        or not 1 <= len(value["requests"]) <= 3
    ):
        raise IamConflictError("handover session budget state is malformed")
    start, deadline = _time(value.get("started_at")), _time(value.get("deadline_at"))
    if deadline - start != timedelta(minutes=5):
        raise IamConflictError("handover session time budget was changed")
    for record in value["requests"].values():
        if (
            not isinstance(record, Mapping)
            or not isinstance(record.get("digest"), str)
            or not start < _time(record.get("deadline_at")) <= deadline
        ):
            raise IamConflictError("handover turn budget state is malformed")


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise IamConflictError("handover budget timestamp is malformed")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IamConflictError("handover budget timestamp is malformed") from exc
    if result.utcoffset() is None:
        raise IamConflictError("handover budget timestamp requires a timezone")
    return result.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["HandoverSessionBudget"]
