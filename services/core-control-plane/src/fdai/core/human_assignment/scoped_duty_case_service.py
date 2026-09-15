"""Revisioned independent review of current scoped duty plans, without IAM effects."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.scoped_duty import ScopedDutyRequest

from fdai.core.human_assignment.repository import assignment_case_id
from fdai.core.human_assignment.scoped_duties import utc_instant
from fdai.core.human_assignment.scoped_duty_case_model import (
    SCOPED_CASE_PREFIX,
    ScopedDutyCase,
    ScopedDutyCommand,
    ScopedDutyReview,
    ScopedDutyState,
    require_current_plan,
    resolved_targets_digest,
    scoped_input,
)
from fdai.core.human_assignment.scoped_duty_planning import (
    ScopedDutyPlanner,
    render_scoped_duty_review,
)
from fdai.shared.providers.state_store import StateStore


class ScopedDutyOwnerEligibility(Protocol):
    """Read current exact human Owner evidence; a token or duty alone is insufficient."""

    async def is_current_owner(self, person_ref: str, *, at: datetime) -> bool:
        """Return false on missing, inactive, ambiguous, or stale evidence; never grant a role."""
        ...


@dataclass(frozen=True, slots=True)
class ScopedDutyCaseService:
    """Muninn-owned CAS materialization after Forseti, Var, and Saga's typed handoffs.

    The immutable command receipt and each case transition share one atomic audit write.
    Current source reads may only hold a plan. They cannot merge an artifact or apply IAM.
    """

    store: StateStore
    planner: ScopedDutyPlanner
    owners: ScopedDutyOwnerEligibility
    clock: Callable[[], datetime]

    def require_current_command(self, accepted_at: datetime) -> None:
        """An accepted command cannot outlive its five-minute source window during I/O."""
        age = utc_instant(self.clock()) - utc_instant(accepted_at)
        if not timedelta(0) <= age < timedelta(minutes=5):
            raise ValueError("scoped duty command receipt expired during processing")

    async def get(self, case_id: str) -> ScopedDutyCase:
        """Load only the distinct Core-owned scoped namespace, never a personal IAM case."""
        raw = await self.store.read_state(SCOPED_CASE_PREFIX + case_id)
        if raw is None:
            raise ValueError("scoped duty case was not found")
        case = ScopedDutyCase.model_validate(raw)
        if case.case_id != case_id:
            raise ValueError("scoped duty case identity does not match its source key")
        return case

    async def require_owner(self, actor: str) -> None:
        """Require fresh Owner evidence through the injected current directory reader."""
        async with asyncio.timeout(self.planner.policy.read_timeout_seconds):
            if actor != actor.casefold() or not await self.owners.is_current_owner(
                actor, at=self.clock()
            ):
                raise PermissionError("current independent human Owner evidence is required")

    async def predecessor(self, request: ScopedDutyRequest) -> ScopedDutyCase | None:
        """Permit explicit replacement only of one retained reviewed case over identical scopes."""
        if request.supersedes_case_id is None:
            return None
        old = await self.get(request.supersedes_case_id)
        targets = {(row.agent_name, row.scope_ref) for row in request.bindings}
        if old.state != "ownership_pr_open" or targets != {
            (row.agent_name, row.scope_ref) for row in old.request.bindings
        }:
            raise ValueError(
                "scoped replacement requires a reviewed predecessor over identical scopes"
            )
        return old

    async def create(
        self,
        *,
        actor: str,
        idempotency_key: str,
        request: ScopedDutyRequest,
        justification: str,
        command: ScopedDutyCommand,
        accepted_at: datetime,
    ) -> ScopedDutyCase:
        """Create a reviewable immutable draft; an unresolved plan never becomes approval."""
        await self.require_owner(actor)
        await self.predecessor(request)
        case_id = assignment_case_id(actor, "scoped-duty:" + idempotency_key)
        if case_id == request.supersedes_case_id:
            raise ValueError("a scoped case cannot supersede itself")
        existing = await self.store.read_state(SCOPED_CASE_PREFIX + case_id)
        if existing is not None:
            current = ScopedDutyCase.model_validate(existing)
            if (
                current.request != request
                or current.justification != justification
                or current.requester_ref != actor
                or current.command_receipt(command) is None
            ):
                raise ValueError("scoped duty idempotency identity conflicts with retained intent")
            return current
        plan = await self.planner.plan(scoped_input(request))
        candidate = ScopedDutyCase(
            case_id=case_id,
            requester_ref=actor,
            idempotency_key=idempotency_key,
            justification=justification,
            request=request,
            state="draft",
            revision=1,
            plan_json=render_scoped_duty_review(plan),
            created_at=accepted_at,
            updated_at=self.clock(),
            commands=(command.materialized("draft", 1),),
        )
        self.require_current_command(accepted_at)
        if await self.store.write_state_with_audit_if_absent(
            SCOPED_CASE_PREFIX + case_id,
            candidate.model_dump(mode="json"),
            self.audit(candidate, "requested", actor),
        ):
            return candidate
        raced = await self.get(case_id)
        if raced != candidate:
            if (
                raced.request != request
                or raced.justification != justification
                or raced.requester_ref != actor
                or raced.command_receipt(command) is None
            ):
                raise ValueError("scoped duty creation conflicts after a concurrent request")
        return raced

    async def submit(
        self,
        *,
        case_id: str,
        actor: str,
        expected_revision: int,
        command: ScopedDutyCommand,
        accepted_at: datetime,
    ) -> ScopedDutyCase:
        """Refresh current sources before submitting this exact draft for independent review."""
        current = await self.get(case_id)
        await self.require_owner(actor)
        if actor != current.requester_ref:
            raise PermissionError("only the scoped duty requester may submit its draft")
        if current.command_receipt(command) is not None:
            await self.fresh_plan(current)
            return current
        if current.state != "draft" or current.revision != expected_revision:
            raise ValueError("scoped duty submission requires the exact draft revision")
        plan = await self.planner.plan(scoped_input(current.request))
        if not plan.has_current_coverage:
            raise ValueError("scoped duty current coverage is incomplete")
        candidate = self.changed(
            current,
            state="pending_review",
            plan_json=render_scoped_duty_review(plan),
            commands=(
                *current.commands,
                command.materialized("pending_review", current.revision + 1),
            ),
        )
        return await self.persist(
            current,
            candidate,
            "submitted",
            actor,
            observation=json.loads(render_scoped_duty_review(plan)),
            accepted_at=accepted_at,
        )

    async def check_review(
        self,
        current: ScopedDutyCase,
        *,
        actor: str,
        plan_digest: str,
    ) -> dict[str, Any]:
        """Verify new and prior reviewers independently against current scope and people."""
        plan = await self.fresh_plan(current)
        if plan_digest != current.plan()["digest"]:
            raise ValueError("scoped duty review MUST bind the exact retained plan")
        excluded = {current.requester_ref}
        predecessor = await self.predecessor(current.request)
        if predecessor is not None:
            for row in predecessor.plan()["bindings"]:
                if row["resolution"] is not None:
                    excluded.update(person["ref"] for person in row["resolution"]["people"])
                fallback = row["binding"].get("fallback")
                if fallback is not None:
                    excluded.add(fallback["ref"])
        for binding in current.request.bindings:
            if binding.subject.kind == "user":
                excluded.add(binding.subject.ref)
            if binding.fallback is not None:
                excluded.add(binding.fallback.ref)
        for row in plan["bindings"]:
            if row["resolution"] is not None:
                excluded.update(person["ref"] for person in row["resolution"]["people"])
        for reviewer in sorted({actor, *(row.reviewer_ref for row in current.reviews)}):
            if reviewer in excluded:
                raise PermissionError("scoped duty requester and target cannot review this plan")
            await self.require_owner(reviewer)
        require_current_plan(plan, at=self.clock())
        return plan

    async def review(
        self,
        *,
        case_id: str,
        actor: str,
        expected_revision: int,
        decision: str,
        plan_digest: str,
        command: ScopedDutyCommand,
        accepted_at: datetime,
    ) -> ScopedDutyCase:
        """Record one revision-bound review; rejection is terminal and approval requires two."""
        current = await self.get(case_id)
        observed = await self.check_review(current, actor=actor, plan_digest=plan_digest)
        if current.command_receipt(command) is not None:
            return current
        if current.state != "pending_review" or current.revision != expected_revision:
            raise ValueError("scoped duty review requires the exact pending revision")
        if actor in {row.reviewer_ref for row in current.reviews}:
            raise ValueError("scoped duty reviewer already has a decision")
        review = ScopedDutyReview.model_validate(
            {
                "reviewer_ref": actor,
                "decision": decision,
                "plan_digest": plan_digest,
                "reviewed_at": accepted_at,
            }
        )
        reviews = (*current.reviews, review)
        state: ScopedDutyState = (
            "rejected"
            if decision == "reject"
            else ("approved" if len(reviews) == 2 else "pending_review")
        )
        candidate = self.changed(
            current,
            state=state,
            reviews=reviews,
            commands=(*current.commands, command.materialized(state, current.revision + 1)),
        )
        return await self.persist(
            current, candidate, "reviewed", actor, observation=observed, accepted_at=accepted_at
        )

    async def fresh_plan(self, current: ScopedDutyCase) -> dict[str, Any]:
        """Reread exact catalog and directory facts; changed targets cannot reuse old reviews."""
        await self.predecessor(current.request)
        observed = await self.planner.plan(scoped_input(current.request))
        plan: dict[str, Any] = json.loads(render_scoped_duty_review(observed))
        if not observed.has_current_coverage or resolved_targets_digest(
            plan
        ) != resolved_targets_digest(current.plan()):
            raise ValueError("scoped duty sources changed or current coverage is incomplete")
        return plan

    def changed(self, current: ScopedDutyCase, **changes: Any) -> ScopedDutyCase:
        """Build a fully revalidated next revision; model_copy never bypasses case invariants."""
        return ScopedDutyCase.model_validate(
            {
                **current.model_dump(),
                "revision": current.revision + 1,
                "updated_at": self.clock(),
                **changes,
            }
        )

    async def persist(
        self,
        current: ScopedDutyCase,
        candidate: ScopedDutyCase,
        operation: str,
        actor: str,
        *,
        observation: dict[str, Any],
        accepted_at: datetime | None = None,
    ) -> ScopedDutyCase:
        """Commit one case and audit atomically; only exact concurrent replay is successful."""
        require_current_plan(observation, at=self.clock())
        if accepted_at is not None:
            self.require_current_command(accepted_at)
        if await self.store.compare_and_set_state_with_audit(
            SCOPED_CASE_PREFIX + current.case_id,
            candidate.model_dump(mode="json"),
            expected_revision=current.revision,
            audit_entry=self.audit(candidate, operation, actor),
        ):
            return candidate
        winner = await self.get(current.case_id)
        if winner == candidate:
            return winner
        raise ValueError("scoped duty revision changed during the command")

    @staticmethod
    def audit(case: ScopedDutyCase, operation: str, actor: str) -> dict[str, object]:
        """Record content-free Saga attribution without copying group membership or prose."""
        return {
            "actor": "Saga",
            "state_owner": "Muninn",
            "requester_digest": canonical_actor(actor),
            "action_kind": "human.scoped_duty." + operation,
            "case_id": case.case_id,
            "revision": case.revision,
            "state": case.state,
            "plan_digest": case.plan()["digest"],
            "recorded_at": case.updated_at.isoformat(),
            "mode": "shadow",
            "execution_authority": False,
        }


def canonical_actor(actor: str) -> str:
    """Hash the normalized human reference for content-free audit correlation."""
    from fdai.core.human_assignment.scoped_duties import canonical_digest

    return canonical_digest({"actor": actor})


__all__ = ["ScopedDutyCaseService", "ScopedDutyOwnerEligibility"]
