"""Durable proactive knowledge-transfer goal lifecycle."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai.core.human_assignment.fatigue import HandoverFatiguePolicy
from fdai.core.human_assignment.model import AssignmentState
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.stewardship.names import AGENT_NAME_SET
from fdai.shared.providers.state_store import StateStore

_GOAL_PREFIX = "handover_goal:goal:"
_INVITATION_PREFIX = "handover_goal:invitation:"
_WEEK_PREFIX = "handover_goal:week:"
_SAFE_REF = re.compile(r"^[A-Za-z0-9._:/-]{1,256}$")


class HandoverGoalState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    READY_FOR_REVIEW = "ready_for_review"
    ACCEPTED = "accepted"
    STALE = "stale"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class GoalEvidence:
    evidence_ref: str
    digest: str
    kind: str

    def __post_init__(self) -> None:
        _safe(self.evidence_ref, "evidence_ref")
        if not re.fullmatch(r"[a-f0-9]{64}", self.digest):
            raise ValueError("evidence digest MUST be a lowercase SHA-256 digest")
        _safe(self.kind, "evidence kind")

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_ref": self.evidence_ref,
            "digest": self.digest,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class HandoverGoal:
    goal_id: str
    assignment_case_id: str
    subject_ref: str
    agent_name: str
    scope_ref: str
    prompt_ref: str
    priority: int
    created_at: datetime
    state: HandoverGoalState = HandoverGoalState.NOT_STARTED
    revision: int = 1
    evidence: tuple[GoalEvidence, ...] = ()
    not_applicable_reason_ref: str | None = None
    snoozed_until: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.goal_id, "goal_id"),
            (self.assignment_case_id, "assignment_case_id"),
            (self.subject_ref, "subject_ref"),
            (self.scope_ref, "scope_ref"),
            (self.prompt_ref, "prompt_ref"),
        ):
            _safe(value, name)
        if self.agent_name not in AGENT_NAME_SET:
            raise ValueError("goal agent_name MUST be a pantheon agent")
        if not 1 <= self.priority <= 100:
            raise ValueError("goal priority MUST be in [1, 100]")
        _aware(self.created_at)
        if self.revision < 1:
            raise ValueError("goal revision MUST be positive")
        if self.snoozed_until is not None:
            _aware(self.snoozed_until)
        if self.not_applicable_reason_ref is not None:
            _safe(self.not_applicable_reason_ref, "not_applicable_reason_ref")

    @property
    def reviewable(self) -> bool:
        return bool(self.evidence or self.not_applicable_reason_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "assignment_case_id": self.assignment_case_id,
            "subject_ref": self.subject_ref,
            "agent_name": self.agent_name,
            "scope_ref": self.scope_ref,
            "prompt_ref": self.prompt_ref,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "revision": self.revision,
            "evidence": [item.to_dict() for item in self.evidence],
            "not_applicable_reason_ref": self.not_applicable_reason_ref,
            "snoozed_until": (self.snoozed_until.isoformat() if self.snoozed_until else None),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HandoverGoal:
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("goal evidence MUST be an array")
        snoozed = value.get("snoozed_until")
        return cls(
            goal_id=str(value["goal_id"]),
            assignment_case_id=str(value["assignment_case_id"]),
            subject_ref=str(value["subject_ref"]),
            agent_name=str(value["agent_name"]),
            scope_ref=str(value["scope_ref"]),
            prompt_ref=str(value["prompt_ref"]),
            priority=int(value["priority"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            state=HandoverGoalState(str(value["state"])),
            revision=int(value["revision"]),
            evidence=tuple(
                GoalEvidence(
                    evidence_ref=str(item["evidence_ref"]),
                    digest=str(item["digest"]),
                    kind=str(item["kind"]),
                )
                for item in evidence
                if isinstance(item, Mapping)
            ),
            not_applicable_reason_ref=(
                str(value["not_applicable_reason_ref"])
                if value.get("not_applicable_reason_ref") is not None
                else None
            ),
            snoozed_until=datetime.fromisoformat(str(snoozed)) if snoozed else None,
        )


@dataclass(frozen=True, slots=True)
class HandoverInvitation:
    invitation_id: str
    goal_id: str
    agent_name: str
    prompt_ref: str
    session_id: str
    max_questions: int
    max_minutes: int


class HandoverGoalService:
    def __init__(
        self,
        *,
        store: StateStore,
        assignments: AssignmentCaseService,
        fatigue: HandoverFatiguePolicy | None = None,
        actor: str = "fdai.core.human_assignment.goals",
    ) -> None:
        self._store = store
        self._assignments = assignments
        self._fatigue = fatigue or HandoverFatiguePolicy()
        self._actor = actor

    async def create_goal(
        self,
        *,
        assignment_case_id: str,
        agent_name: str,
        scope_ref: str,
        prompt_ref: str,
        priority: int,
        now: datetime | None = None,
    ) -> HandoverGoal:
        assignment = await self._assignments.get_case(assignment_case_id)
        if assignment.state is not AssignmentState.ACTIVE:
            raise ValueError("handover goal requires an active assignment")
        if not any(
            binding.agent_name == agent_name and binding.scope_ref == scope_ref
            for binding in assignment.intent.duty_bindings
        ):
            raise ValueError("handover goal is outside the active assignment")
        timestamp = _aware(now or datetime.now(UTC))
        material = f"{assignment.case_id}\0{agent_name}\0{scope_ref}\0{prompt_ref}"
        goal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fdai-handover:{material}"))
        goal = HandoverGoal(
            goal_id=goal_id,
            assignment_case_id=assignment.case_id,
            subject_ref=assignment.intent.subject.subject_id,
            agent_name=agent_name,
            scope_ref=scope_ref,
            prompt_ref=prompt_ref,
            priority=priority,
            created_at=timestamp,
        )
        created = await self._store.write_state_with_audit_if_absent(
            f"{_GOAL_PREFIX}{goal_id}",
            goal.to_dict(),
            self._audit("handover.goal.created", goal_id, timestamp),
        )
        if created:
            return goal
        existing = await self.get_goal(goal_id)
        if existing != goal:
            raise ValueError("handover goal id is bound to different content")
        return existing

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        session_id: str,
        incident_active: bool = False,
        approval_active: bool = False,
        now: datetime | None = None,
    ) -> HandoverInvitation | None:
        _safe(subject_ref, "subject_ref")
        _safe(session_id, "session_id")
        timestamp = _aware(now or datetime.now(UTC))
        if incident_active or approval_active:
            return None
        session_key = _digest(f"{subject_ref}\0{session_id}")
        if await self._store.read_state(f"{_INVITATION_PREFIX}session:{session_key}"):
            return None
        week = self._fatigue.week_key(timestamp)
        subject_hash = _digest(subject_ref)
        values = await self._store.read_states(_GOAL_PREFIX, limit=500)
        candidates = sorted(
            (
                HandoverGoal.from_mapping(value)
                for value in values
                if value.get("subject_ref") == subject_ref
                and value.get("state")
                in {HandoverGoalState.NOT_STARTED.value, HandoverGoalState.IN_PROGRESS.value}
            ),
            key=lambda item: (-item.priority, item.goal_id),
        )
        goal = None
        for item in candidates:
            if item.snoozed_until is not None and item.snoozed_until > timestamp:
                continue
            assignment = await self._assignments.get_case(item.assignment_case_id)
            if assignment.state is AssignmentState.ACTIVE:
                goal = item
                break
        if goal is None:
            return None
        if not await self._claim_weekly_budget(subject_hash, week, timestamp):
            return None
        invitation_id = _digest(f"{session_key}\0{goal.goal_id}")
        record = {
            "invitation_id": invitation_id,
            "goal_id": goal.goal_id,
            "subject_hash": subject_hash,
            "session_hash": _digest(session_id),
            "week": week,
            "invited_at": timestamp.isoformat(),
        }
        created = await self._store.write_state_with_audit_if_absent(
            f"{_INVITATION_PREFIX}session:{session_key}",
            record,
            self._audit("handover.invitation.sent", invitation_id, timestamp),
        )
        if not created:
            return None
        return HandoverInvitation(
            invitation_id=invitation_id,
            goal_id=goal.goal_id,
            agent_name=goal.agent_name,
            prompt_ref=goal.prompt_ref,
            session_id=session_id,
            max_questions=self._fatigue.max_questions_per_session,
            max_minutes=self._fatigue.max_session_minutes,
        )

    async def _claim_weekly_budget(
        self,
        subject_hash: str,
        week: str,
        now: datetime,
    ) -> bool:
        key = f"{_WEEK_PREFIX}{subject_hash}:{week}"
        for _attempt in range(4):
            current = await self._store.read_state(key)
            if current is None:
                if await self._store.write_state_if_absent(
                    key,
                    {"revision": 1, "count": 1, "week": week, "updated_at": now.isoformat()},
                ):
                    return True
                continue
            revision = current.get("revision")
            count = current.get("count")
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or isinstance(count, bool)
                or not isinstance(count, int)
            ):
                raise ValueError("handover fatigue state is malformed")
            if count >= self._fatigue.max_invitations_per_week:
                return False
            applied = await self._store.compare_and_set_state_with_audit(
                key,
                {
                    "revision": revision + 1,
                    "count": count + 1,
                    "week": week,
                    "updated_at": now.isoformat(),
                },
                expected_revision=revision,
                audit_entry=self._audit(
                    "handover.fatigue.claimed",
                    f"{subject_hash}:{week}:{revision + 1}",
                    now,
                ),
            )
            if applied:
                return True
        return False

    async def add_evidence(
        self,
        *,
        goal_id: str,
        expected_revision: int,
        evidence: GoalEvidence,
        now: datetime | None = None,
    ) -> HandoverGoal:
        current = await self.get_goal(goal_id)
        if any(item.evidence_ref == evidence.evidence_ref for item in current.evidence):
            return current
        candidate = replace(
            current,
            state=HandoverGoalState.READY_FOR_REVIEW,
            revision=current.revision + 1,
            evidence=(*current.evidence, evidence),
            snoozed_until=None,
        )
        return await self._persist(current, candidate, expected_revision, "evidence", now)

    async def snooze(
        self, *, goal_id: str, expected_revision: int, now: datetime | None = None
    ) -> HandoverGoal:
        current = await self.get_goal(goal_id)
        timestamp = _aware(now or datetime.now(UTC))
        candidate = replace(
            current,
            state=HandoverGoalState.IN_PROGRESS,
            revision=current.revision + 1,
            snoozed_until=timestamp + timedelta(hours=self._fatigue.snooze_hours),
        )
        return await self._persist(current, candidate, expected_revision, "snoozed", timestamp)

    async def decline(
        self, *, goal_id: str, expected_revision: int, now: datetime | None = None
    ) -> HandoverGoal:
        current = await self.get_goal(goal_id)
        candidate = replace(
            current,
            state=HandoverGoalState.DECLINED,
            revision=current.revision + 1,
        )
        return await self._persist(current, candidate, expected_revision, "declined", now)

    async def mark_not_applicable(
        self,
        *,
        goal_id: str,
        expected_revision: int,
        reason_ref: str,
        now: datetime | None = None,
    ) -> HandoverGoal:
        _safe(reason_ref, "reason_ref")
        current = await self.get_goal(goal_id)
        candidate = replace(
            current,
            state=HandoverGoalState.READY_FOR_REVIEW,
            revision=current.revision + 1,
            not_applicable_reason_ref=reason_ref,
        )
        return await self._persist(current, candidate, expected_revision, "not_applicable", now)

    async def accept(
        self, *, goal_id: str, expected_revision: int, now: datetime | None = None
    ) -> HandoverGoal:
        current = await self.get_goal(goal_id)
        if not current.reviewable or current.state is not HandoverGoalState.READY_FOR_REVIEW:
            raise ValueError("handover goal requires cited evidence or not-applicable reason")
        candidate = replace(
            current,
            state=HandoverGoalState.ACCEPTED,
            revision=current.revision + 1,
        )
        return await self._persist(current, candidate, expected_revision, "accepted", now)

    async def get_goal(self, goal_id: str) -> HandoverGoal:
        value = await self._store.read_state(f"{_GOAL_PREFIX}{_safe(goal_id, 'goal_id')}")
        if value is None:
            raise ValueError("handover goal was not found")
        return HandoverGoal.from_mapping(value)

    async def _persist(
        self,
        current: HandoverGoal,
        candidate: HandoverGoal,
        expected_revision: int,
        transition: str,
        now: datetime | None,
    ) -> HandoverGoal:
        if expected_revision != current.revision:
            raise ValueError("stale handover goal revision")
        timestamp = _aware(now or datetime.now(UTC))
        applied = await self._store.compare_and_set_state_with_audit(
            f"{_GOAL_PREFIX}{current.goal_id}",
            candidate.to_dict(),
            expected_revision=expected_revision,
            audit_entry=self._audit(
                f"handover.goal.{transition}",
                f"{current.goal_id}:{candidate.revision}",
                timestamp,
            ),
        )
        if not applied:
            raise ValueError("stale handover goal revision")
        return candidate

    def _audit(self, kind: str, identity: str, at: datetime) -> dict[str, str]:
        return {
            "actor": self._actor,
            "action_kind": kind,
            "idempotency_key": f"{kind}:{identity}",
            "goal_ref": identity,
            "recorded_at": at.isoformat(),
        }


def _safe(value: str, name: str) -> str:
    if not _SAFE_REF.fullmatch(value):
        raise ValueError(f"{name} MUST be a bounded safe reference")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("handover goal timestamp MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "GoalEvidence",
    "HandoverGoal",
    "HandoverGoalService",
    "HandoverGoalState",
    "HandoverInvitation",
]
