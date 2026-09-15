"""Durable proactive knowledge-transfer goal lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai_service_contracts.handover_checklist import (
    CHECKLIST_VERSION,
    HANDOVER_SLOTS,
    HandoverReview,
    HandoverSlot,
    acceptance_complete,
    checklist_complete,
    checklist_digest,
    project_checklist,
)

from fdai.core.human_assignment.fatigue import HandoverFatiguePolicy
from fdai.core.human_assignment.goal_admission import GoalEvidenceAdmission, GoalReviewerEligibility
from fdai.core.human_assignment.model import AssignmentState
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
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
    slot: str | None = None

    def __post_init__(self) -> None:
        _safe(self.evidence_ref, "evidence_ref")
        if not re.fullmatch(r"[a-f0-9]{64}", self.digest):
            raise ValueError("evidence digest MUST be a lowercase SHA-256 digest")
        _safe(self.kind, "evidence kind")
        if self.slot is not None:
            HandoverSlot(self.slot)

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_ref": self.evidence_ref,
            "digest": self.digest,
            "kind": self.kind,
            **({"slot": self.slot} if self.slot is not None else {}),
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
    checklist_version: str = CHECKLIST_VERSION
    high_impact: bool = True
    slot_exemptions: tuple[tuple[str, str], ...] = ()
    owner_review: HandoverReview | None = None
    backup_review: HandoverReview | None = None

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
        if type(self.priority) is not int or not 1 <= self.priority <= 100:
            raise ValueError("goal priority MUST be in [1, 100]")
        _aware(self.created_at)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("goal revision MUST be positive")
        if self.snoozed_until is not None:
            _aware(self.snoozed_until)
        if self.not_applicable_reason_ref is not None:
            _safe(self.not_applicable_reason_ref, "not_applicable_reason_ref")
        if type(self.high_impact) is not bool:
            raise ValueError("goal impact MUST be explicit")
        if len(dict(self.slot_exemptions)) != len(self.slot_exemptions):
            raise ValueError("goal exemptions MUST use distinct slots")

    @property
    def reviewable(self) -> bool:
        return checklist_complete(self.to_dict())

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
            "checklist_version": self.checklist_version,
            "required_slots": list(HANDOVER_SLOTS),
            "high_impact": self.high_impact,
            "slot_exemptions": dict(self.slot_exemptions),
            "owner_review": (
                self.owner_review.model_dump(mode="json") if self.owner_review else None
            ),
            "backup_review": (
                self.backup_review.model_dump(mode="json") if self.backup_review else None
            ),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HandoverGoal:
        value = project_checklist(value)
        evidence = value.get("evidence", [])
        if (
            not isinstance(evidence, list)
            or len(evidence) > 64
            or any(not isinstance(item, Mapping) for item in evidence)
        ):
            raise ValueError("goal evidence MUST be an array")
        if value.get("checklist_version") == CHECKLIST_VERSION and value.get(
            "required_slots"
        ) != list(HANDOVER_SLOTS):
            raise ValueError("goal required slots do not match its checklist version")
        snoozed = value.get("snoozed_until")
        return cls(
            goal_id=str(value["goal_id"]),
            assignment_case_id=str(value["assignment_case_id"]),
            subject_ref=str(value["subject_ref"]),
            agent_name=str(value["agent_name"]),
            scope_ref=str(value["scope_ref"]),
            prompt_ref=str(value["prompt_ref"]),
            priority=value["priority"],
            created_at=datetime.fromisoformat(str(value["created_at"])),
            state=HandoverGoalState(str(value["state"])),
            revision=value["revision"],
            evidence=tuple(
                GoalEvidence(
                    evidence_ref=str(item["evidence_ref"]),
                    digest=str(item["digest"]),
                    kind=str(item["kind"]),
                    slot=item.get("slot"),
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
            checklist_version=value.get("checklist_version", "legacy"),
            high_impact=value.get("high_impact", True),
            slot_exemptions=tuple(value.get("slot_exemptions", {}).items()),
            owner_review=(
                HandoverReview.model_validate(value["owner_review"])
                if value.get("owner_review")
                else None
            ),
            backup_review=(
                HandoverReview.model_validate(value["backup_review"])
                if value.get("backup_review")
                else None
            ),
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
        evidence_admission: GoalEvidenceAdmission | None = None,
        review_eligibility: GoalReviewerEligibility | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._assignments = assignments
        self._fatigue = fatigue or HandoverFatiguePolicy()
        self._actor = actor
        self._evidence_admission = evidence_admission
        self._review_eligibility = review_eligibility
        self._clock = clock

    async def create_goal(
        self,
        *,
        assignment_case_id: str,
        agent_name: str,
        scope_ref: str,
        prompt_ref: str,
        priority: int,
        high_impact: bool = True,
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
            high_impact=high_impact,
        )
        created = await self._store.write_state_with_audit_if_absent(
            f"{_GOAL_PREFIX}{goal_id}",
            goal.to_dict(),
            self._audit("handover.goal.created", goal_id, timestamp),
        )
        if created:
            return goal
        existing = await self.get_goal(goal_id)
        if any(
            getattr(existing, name) != getattr(goal, name)
            for name in (
                "assignment_case_id",
                "subject_ref",
                "agent_name",
                "scope_ref",
                "prompt_ref",
                "priority",
                "high_impact",
            )
        ):
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
        if not await self._claim_weekly_budget(subject_hash, week, session_key, timestamp):
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
        session_key: str,
        now: datetime,
    ) -> bool:
        key = f"{_WEEK_PREFIX}{subject_hash}:{week}"
        for _attempt in range(4):
            current = await self._store.read_state(key)
            if current is None:
                if await self._store.write_state_with_audit_if_absent(
                    key,
                    {
                        "revision": 1,
                        "count": 1,
                        "claimed_sessions": [session_key],
                        "week": week,
                        "updated_at": now.isoformat(),
                    },
                    self._audit(
                        "handover.fatigue.claimed",
                        f"{subject_hash}:{week}:1",
                        now,
                    ),
                ):
                    return True
                continue
            revision = current.get("revision")
            count = current.get("count")
            claimed_sessions = current.get("claimed_sessions", [])
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or not isinstance(claimed_sessions, list)
                or not all(isinstance(item, str) for item in claimed_sessions)
            ):
                raise ValueError("handover fatigue state is malformed")
            if session_key in claimed_sessions:
                return True
            if count >= self._fatigue.max_invitations_per_week:
                return False
            applied = await self._store.compare_and_set_state_with_audit(
                key,
                {
                    "revision": revision + 1,
                    "count": count + 1,
                    "claimed_sessions": [*claimed_sessions, session_key],
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
        await self._require_active(current)
        for item in current.evidence:
            if (item.evidence_ref, item.slot) != (evidence.evidence_ref, evidence.slot):
                continue
            if item == evidence:
                return current
            raise ValueError("handover evidence reference is bound to different content")
        candidate = replace(
            current,
            state=HandoverGoalState.IN_PROGRESS,
            revision=current.revision + 1,
            evidence=(*current.evidence, evidence),
            snoozed_until=None,
            checklist_version=CHECKLIST_VERSION,
            owner_review=None,
            backup_review=None,
        )
        if candidate.reviewable:
            candidate = replace(candidate, state=HandoverGoalState.READY_FOR_REVIEW)
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
        slot: str | None = None,
        now: datetime | None = None,
    ) -> HandoverGoal:
        _safe(reason_ref, "reason_ref")
        if slot is None:
            raise ValueError("not-applicable requires an explicit handover slot")
        HandoverSlot(slot)
        current = await self.get_goal(goal_id)
        if slot in dict(current.slot_exemptions) or any(
            item.slot == slot for item in current.evidence
        ):
            raise ValueError("handover slot is already satisfied")
        candidate = replace(
            current,
            state=HandoverGoalState.IN_PROGRESS,
            revision=current.revision + 1,
            slot_exemptions=(*current.slot_exemptions, (slot, reason_ref)),
            checklist_version=CHECKLIST_VERSION,
            owner_review=None,
            backup_review=None,
        )
        if candidate.reviewable:
            candidate = replace(candidate, state=HandoverGoalState.READY_FOR_REVIEW)
        return await self._persist(current, candidate, expected_revision, "not_applicable", now)

    async def accept(
        self,
        *,
        goal_id: str,
        expected_revision: int,
        now: datetime | None = None,
        principal: Principal | None = None,
        backup_case_id: str | None = None,
    ) -> HandoverGoal:
        """Record independent Owner acceptance or a current distinct backup acknowledgement.

        Current source and reviewer reads have one non-sliding two-minute deadline. The
        request timestamp never extends it. Missing human, source admission, complete
        slots, or backup evidence holds instead of accepting.
        """
        async with asyncio.timeout(120):
            return await self._accept(
                goal_id=goal_id,
                expected_revision=expected_revision,
                now=now,
                principal=principal,
                backup_case_id=backup_case_id,
                started_at=_aware(self._clock()),
            )

    async def _accept(
        self,
        *,
        goal_id: str,
        expected_revision: int,
        now: datetime | None,
        principal: Principal | None,
        backup_case_id: str | None,
        started_at: datetime,
    ) -> HandoverGoal:
        current = await self.get_goal(goal_id)
        if type(expected_revision) is not int or expected_revision != current.revision:
            raise ValueError("stale handover goal revision")
        if not current.reviewable or current.state is not HandoverGoalState.READY_FOR_REVIEW:
            raise ValueError("handover goal requires cited evidence in all six slots")
        if principal is None or principal.oid.strip().casefold() == current.subject_ref.casefold():
            raise ValueError("handover acceptance requires an independent authenticated human")
        actor = principal.oid.strip().casefold()
        if backup_case_id is None:
            if Role.OWNER not in principal.roles or current.owner_review is not None:
                raise ValueError("handover acceptance requires a new independent Owner review")
            other = current.backup_review
        else:
            backup = await self._assignments.get_case(backup_case_id)
            if (
                backup.state is not AssignmentState.ACTIVE
                or backup.intent.subject.provider != "entra"
                or not principal.roles.intersection(
                    {Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER}
                )
                or backup.intent.subject.subject_id.casefold() != actor
                or not any(
                    duty.agent_name == current.agent_name
                    and duty.scope_ref == current.scope_ref
                    and duty.duty in {Duty.BACKUP, Duty.ESCALATION}
                    for duty in backup.intent.duty_bindings
                )
                or current.backup_review is not None
            ):
                raise ValueError("handover acknowledgement requires the current backup assignment")
            other = current.owner_review
        if other is not None and other.reviewer_ref.casefold() == actor:
            raise ValueError("handover reviews require two distinct people")
        await self._require_evidence_access(current, {actor})
        timestamp = _aware(now or datetime.now(UTC))
        if self._review_eligibility is None:
            raise ValueError("current handover reviewer eligibility is unavailable")
        targets = [(actor, "owner" if backup_case_id is None else "backup")]
        for prior, role in ((current.owner_review, "owner"), (current.backup_review, "backup")):
            if prior is not None:
                if prior.reviewed_at > timestamp:
                    raise ValueError("prior handover review time is in the future")
                targets.append((prior.reviewer_ref, role))
        for reviewer_ref, review_role in targets:
            if not await self._review_eligibility.may_review(
                reviewer_ref=reviewer_ref,
                agent_name=current.agent_name,
                scope_ref=current.scope_ref,
                role="owner" if review_role == "owner" else "backup",
            ):
                raise ValueError("current handover reviewer eligibility is unavailable")
        await self._require_evidence_access(current, {item[0] for item in targets})
        review = HandoverReview(
            reviewer_ref=actor,
            goal_revision=expected_revision,
            evidence_digest=checklist_digest(current.to_dict()),
            reviewed_at=_aware(now or datetime.now(UTC)),
        )
        candidate = replace(
            current,
            revision=current.revision + 1,
            owner_review=review if backup_case_id is None else current.owner_review,
            backup_review=review if backup_case_id is not None else current.backup_review,
        )
        if acceptance_complete(candidate.to_dict()):
            candidate = replace(candidate, state=HandoverGoalState.ACCEPTED)
        return await self._persist(
            current, candidate, expected_revision, "accepted", now, review_started_at=started_at
        )

    async def get_goal(self, goal_id: str) -> HandoverGoal:
        value = await self._store.read_state(f"{_GOAL_PREFIX}{_safe(goal_id, 'goal_id')}")
        if value is None:
            raise ValueError("handover goal was not found")
        return HandoverGoal.from_mapping(value)

    async def require_current_evidence(self, goal: HandoverGoal) -> None:
        """Revalidate a retained goal for source consumers without rewriting its history.

        The current subject and all retained independent reviewers must remain eligible
        for the exact documents. Failure denies reuse; a persisted acceptance is not a
        substitute for current source, identity, role, or backup-duty evidence.
        """
        async with asyncio.timeout(120):
            started_at = _aware(self._clock())
            await self._require_current_evidence(goal)
            self._require_review_window(started_at)

    async def _require_current_evidence(self, goal: HandoverGoal) -> None:
        if (
            not goal.reviewable
            or goal.state not in {HandoverGoalState.READY_FOR_REVIEW, HandoverGoalState.ACCEPTED}
            or await self.get_goal(goal.goal_id) != goal
        ):
            raise ValueError("current handover goal is not eligible for source admission")
        await self._require_active(goal)
        reviewers = {goal.subject_ref}
        for review, role in ((goal.owner_review, "owner"), (goal.backup_review, "backup")):
            if review is None:
                continue
            if self._review_eligibility is None or not await self._review_eligibility.may_review(
                reviewer_ref=review.reviewer_ref,
                agent_name=goal.agent_name,
                scope_ref=goal.scope_ref,
                role="owner" if role == "owner" else "backup",
            ):
                raise ValueError("current handover reviewer eligibility is unavailable")
            reviewers.add(review.reviewer_ref)
        await self._require_evidence_access(goal, reviewers)
        await self._require_active(goal)
        if await self.get_goal(goal.goal_id) != goal:
            raise ValueError("current handover goal changed during source admission")

    async def _require_evidence_access(self, goal: HandoverGoal, reviewers: set[str]) -> None:
        if self._evidence_admission is None or not await self._evidence_admission.verify_subject(
            subject_ref=goal.subject_ref, assignment_case_id=goal.assignment_case_id
        ):
            raise ValueError("handover subject admission is unavailable")
        documents = {
            (item.evidence_ref, item.digest) for item in goal.evidence if item.slot is not None
        }
        for reference, digest in sorted(documents):
            for reviewer in sorted(reviewers):
                if self._evidence_admission is None or not await self._evidence_admission.verify(
                    subject_ref=goal.subject_ref,
                    evidence_ref=reference,
                    digest=digest,
                    reviewer_ref=reviewer,
                ):
                    raise ValueError("handover source admission and ACL are unavailable")

    async def _persist(
        self,
        current: HandoverGoal,
        candidate: HandoverGoal,
        expected_revision: int,
        transition: str,
        now: datetime | None,
        *,
        review_started_at: datetime | None = None,
    ) -> HandoverGoal:
        if type(expected_revision) is not int or expected_revision != current.revision:
            raise ValueError("stale handover goal revision")
        await self._require_active(current)
        if current.state in {
            HandoverGoalState.ACCEPTED,
            HandoverGoalState.DECLINED,
            HandoverGoalState.STALE,
        }:
            raise ValueError("handover goal is closed to commands")
        timestamp = _aware(now or datetime.now(UTC))
        if review_started_at is not None:
            self._require_review_window(review_started_at)
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

    def _require_review_window(self, started_at: datetime) -> None:
        if not timedelta(0) <= _aware(self._clock()) - started_at < timedelta(minutes=2):
            raise ValueError("handover review read window expired or the clock moved backwards")

    async def _require_active(self, current: HandoverGoal) -> None:
        assignment = await self._assignments.get_case(current.assignment_case_id)
        if (
            assignment.state is not AssignmentState.ACTIVE
            or assignment.intent.subject.subject_id.casefold() != current.subject_ref.casefold()
            or not any(
                binding.agent_name == current.agent_name and binding.scope_ref == current.scope_ref
                for binding in assignment.intent.duty_bindings
            )
        ):
            raise ValueError("handover goal requires an active assignment")

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
