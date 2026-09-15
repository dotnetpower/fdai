"""Server-owned proactive handover invitations and revisioned goal state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
)
from fdai_operator_service.families.iam.contracts import (
    HandoverGoalCommand,
    HumanIdentityDirectory,
    IamPrincipal,
    JsonMapping,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.families.iam.handover_command_guard import (
    authorize_goal_command,
    goal_command_digest,
)
from fdai_operator_service.families.iam.handover_contribution import HandoverContributionGuard
from fdai_operator_service.families.iam.handover_postgres import (
    PostgresHandoverActivityGuard,
    PostgresHandoverEvidenceVerifier,
)
from fdai_operator_service.families.iam.handover_review_eligibility import (
    reader_evidence_current,
    revalidate_goal_reviews,
)
from fdai_operator_service.families.iam.handover_session_budget import HandoverSessionBudget
from fdai_operator_service.families.iam.handover_state import _DOCUMENT_REF as _DOCUMENT_REF
from fdai_operator_service.families.iam.handover_state import _SHA256 as _SHA256
from fdai_operator_service.families.iam.handover_state import _aware as _aware
from fdai_operator_service.families.iam.handover_state import _digest as _digest
from fdai_operator_service.families.iam.handover_state import _document_receipt as _document_receipt
from fdai_operator_service.families.iam.handover_state import (
    _goal_is_invitable as _goal_is_invitable,
)
from fdai_operator_service.families.iam.handover_state import _mapping as _mapping
from fdai_operator_service.families.iam.handover_state import _new_goal as _new_goal
from fdai_operator_service.families.iam.handover_state import _non_negative_int as _non_negative_int
from fdai_operator_service.families.iam.handover_state import _positive_int as _positive_int
from fdai_operator_service.families.iam.handover_state import _sequence as _sequence
from fdai_operator_service.families.iam.handover_state import _string_list as _string_list
from fdai_operator_service.families.iam.handover_state import _transition as _transition
from fdai_operator_service.families.operations.contracts import ProjectionQuery, ProjectionReader
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.handover_checklist import (
    acceptance_complete,
    checklist_digest,
    project_checklist,
)
from fdai_service_contracts.handover_readiness import (
    HANDOVER_READINESS_KEY,
    HandoverReadinessReport,
)

_GOAL_PREFIX = "operator-handover-goal:"
_INVITATION_PREFIX = "operator-handover-invitation:"
_WEEK_PREFIX = "operator-handover-week:"
_MAX_WEEKLY_INVITATIONS = 2
_MAX_CAS_ATTEMPTS = 4
_MAX_GOALS = 15


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


class HandoverEvidenceVerifier(Protocol):
    """Verify one immutable document receipt against authoritative metadata."""

    async def verify(
        self,
        *,
        principal_id: str,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
    ) -> bool: ...


class HandoverActivityGuard(Protocol):
    """Report whether proactive handover can interrupt the current workload."""

    async def may_invite(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProactiveHandoverRuntime:
    """Create one bounded invitation from the authoritative ownership projection."""

    store: HandoverStateStore
    ownership: ProjectionReader
    directory: HumanIdentityDirectory
    evidence_verifier: HandoverEvidenceVerifier
    activity_guard: HandoverActivityGuard
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    contribution_guard: HandoverContributionGuard | None = None

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        roles: frozenset[OperatorRole],
        session_id: str,
    ) -> JsonMapping | None:
        if not await self.activity_guard.may_invite():
            return None
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
        try:
            projected = project_checklist(goal)
        except (TypeError, ValueError) as exc:
            raise IamUnavailableError("handover checklist state is unavailable") from exc
        return await self._refresh_evidence(projected)

    async def lifecycle_readiness(self) -> JsonMapping:
        """Read a current, consistent Core observation; missing evidence never implies health."""
        try:
            report = HandoverReadinessReport.model_validate(
                await self._read(HANDOVER_READINESS_KEY)
            )
            report.require_current(_aware(self.clock()))
        except (TypeError, ValueError) as exc:
            raise IamUnavailableError("handover lifecycle readiness is unavailable") from exc
        return report.model_dump(mode="json")

    async def submit(self, command: HandoverGoalCommand) -> JsonMapping:
        current = dict(await self.get_goal(command.goal_id))
        subject_ref = authorize_goal_command(current, command)
        agents, source_revision = await self._mapped_agents(
            subject_ref=subject_ref,
            roles=command.principal.roles,
            reader_ref=command.principal.oid,
        )
        if (
            current.get("agent_name") not in agents
            or not source_revision
            or source_revision == "unversioned"
            or current.get("source_revision") != source_revision
        ):
            raise IamConflictError("handover goal ownership is no longer current")
        if command.operation == "acknowledge" and not await self.may_review_goal(
            current, command.principal
        ):
            raise IamConflictError("handover acknowledgement requires the current distinct backup")
        if command.operation in {"accept", "acknowledge"}:
            await revalidate_goal_reviews(
                current,
                command,
                directory=self.directory,
                backup_eligible=self.may_review_goal,
                at=_aware(self.clock()),
            )
        reused: JsonMapping | None = None
        if command.operation == "reuse":
            if not command.source_goal_id or command.source_goal_id == command.goal_id:
                raise IamConflictError("handover reuse requires a distinct source goal")
            reused = await self.get_goal(command.source_goal_id)
            if (
                reused.get("subject_ref") != subject_ref
                or reused.get("scope_ref") != current.get("scope_ref")
                or reused.get("source_revision") != source_revision
                or reused.get("state") != "accepted"
                or reused.get("agent_name") not in agents
                or not acceptance_complete(reused)
            ):
                raise IamConflictError(
                    "handover reuse requires current accepted same-scope evidence"
                )
        command_digest = goal_command_digest(command)
        if (
            current.get("revision") == command.expected_revision + 1
            and current.get("last_operation") == command.operation
            and current.get("last_expected_revision") == command.expected_revision
            and str(current.get("last_actor") or "").casefold() == command.principal.oid.casefold()
        ):
            if current.get("last_command_digest") != command_digest:
                raise IamConflictError("handover command replay payload conflicts")
            return current
        if _positive_int(current, "revision") != command.expected_revision:
            raise IamConflictError("handover goal revision is stale")
        if command.operation == "evidence":
            document_id, version_id = _document_receipt(command)
            if not await self.evidence_verifier.verify(
                principal_id=command.principal.oid,
                document_id=document_id,
                version_id=version_id,
                source_sha256=command.digest or "",
            ):
                raise IamConflictError("handover evidence is not an admitted document")
        if current.get("state") in {"accepted", "stale", "declined", "superseded"}:
            raise IamConflictError("handover goal is closed to commands")
        if command.operation in {"accept", "acknowledge"}:
            # Bound the final human checks after document I/O, rather than reusing a check made
            # before an arbitrarily slow source read.
            final_agents, final_revision = await self._mapped_agents(
                subject_ref=subject_ref,
                roles=command.principal.roles,
                reader_ref=command.principal.oid,
            )
            if current.get("agent_name") not in final_agents or final_revision != source_revision:
                raise IamConflictError("handover ownership changed during evidence review")
        updated = _transition(current, command=command, now=_aware(self.clock()))
        if reused is not None:
            if current.get("evidence") or current.get("slot_exemptions"):
                raise IamConflictError("handover reuse cannot overwrite existing evidence")
            updated.update(
                evidence=list(reused["evidence"]),
                slot_exemptions=dict(reused["slot_exemptions"]),
                owner_review=None,
                backup_review=None,
                state="ready_for_review",
                reused_from={
                    "goal_id": reused["goal_id"],
                    "revision": reused["revision"],
                    "digest": checklist_digest(reused),
                },
            )
        updated["last_command_digest"] = command_digest
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
                    "command_digest": command_digest,
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

    async def may_review_goal(self, goal: JsonMapping, principal: IamPrincipal) -> bool:
        """Check the exact current backup duty and ownership revision, never infer a role."""
        if str(goal.get("subject_ref", "")).casefold() == principal.oid.casefold():
            return False
        if not principal.roles - {OperatorRole.BREAK_GLASS}:
            return False
        agents, revision = await self._mapped_agents(
            subject_ref=principal.oid,
            roles=principal.roles,
            required_duties=frozenset({"backup", "escalation"}),
        )
        if goal.get("agent_name") not in agents or goal.get("source_revision") != revision:
            return False
        if goal.get("evidence") and not principal.roles.intersection(
            {OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER, OperatorRole.OWNER}
        ):
            return await reader_evidence_current(
                goal, principal, directory=self.directory, verifier=self.evidence_verifier
            )
        return True

    async def bind_conversation(self, proposal: ConversationProposal) -> ConversationProposal:
        """Resolve an optional handover goal and inject its server-owned agent target."""
        goal_id = proposal.body.get("handover_goal_id")
        if goal_id is None:
            return proposal
        if not isinstance(goal_id, str) or _SHA256.fullmatch(goal_id) is None:
            raise ConversationBoundaryError(
                400, "handover_binding_invalid", "handover goal binding is malformed"
            )
        try:
            goal = await self.get_goal(goal_id)
        except IamNotFoundError as exc:
            raise ConversationBoundaryError(
                404,
                "handover_goal_not_found",
                "handover goal was not found",
            ) from exc
        except IamUnavailableError as exc:
            raise ConversationBoundaryError(
                503,
                "handover_state_unavailable",
                "handover state is unavailable",
            ) from exc
        if goal.get("subject_ref") != proposal.scope.subject_id:
            raise ConversationBoundaryError(
                404, "handover_goal_not_found", "handover goal was not found"
            )
        if goal.get("state") in {"accepted", "declined", "stale", "superseded"}:
            raise ConversationBoundaryError(
                409,
                "handover_goal_closed",
                "handover goal is no longer conversational",
            )
        agent_name = goal.get("agent_name")
        prompt = proposal.body.get("prompt")
        session_id = proposal.body.get("session_id")
        if (
            not isinstance(agent_name, str)
            or not agent_name
            or not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(session_id, str)
            or not session_id.strip()
        ):
            raise ConversationBoundaryError(
                400,
                "handover_binding_incomplete",
                "handover conversation binding is incomplete",
            )
        requested_agent = proposal.body.get("target_agent")
        if requested_agent is not None and requested_agent != agent_name:
            raise ConversationBoundaryError(
                409,
                "handover_agent_mismatch",
                "handover agent does not match the verified goal",
            )
        try:
            agents, revision = await self._mapped_agents(
                subject_ref=proposal.scope.subject_id,
                roles=frozenset(OperatorRole(role) for role in proposal.scope.roles),
            )
            if (
                agent_name not in agents
                or revision == "unversioned"
                or goal.get("source_revision") != revision
            ):
                raise IamConflictError("handover conversation ownership is no longer current")
            if not await self.activity_guard.may_invite():
                raise IamConflictError("handover session is held during incident or approval work")
            snoozed = goal.get("snoozed_until")
            if isinstance(snoozed, str) and _aware(datetime.fromisoformat(snoozed)) > _aware(
                self.clock()
            ):
                raise IamConflictError("handover session is snoozed")
            deadline = await HandoverSessionBudget(self.store).claim(
                proposal, goal_id=goal_id, now=_aware(self.clock())
            )
            if _aware(self.clock()) >= datetime.fromisoformat(deadline):
                raise IamConflictError("handover turn deadline expired during admission")
        except (IamConflictError, ValueError) as exc:
            raise ConversationBoundaryError(409, "handover_session_held", str(exc)) from exc
        except (IamUnavailableError, PostgresFamilyStoreUnavailable) as exc:
            raise ConversationBoundaryError(
                503,
                "handover_state_unavailable",
                "handover state is unavailable",
            ) from exc
        binding_key = (
            f"operator-handover-conversation:{proposal.scope.subject_id}:"
            f"{goal_id}:{_digest(session_id)}"
        )
        binding = {
            "goal_id": goal_id,
            "subject_ref": proposal.scope.subject_id,
            "agent_name": agent_name,
            "session_id": session_id,
            "execution_authority": False,
        }
        try:
            await self._create(binding_key, binding)
            durable_binding = await self._read_required(binding_key)
        except IamUnavailableError as exc:
            raise ConversationBoundaryError(
                503,
                "handover_state_unavailable",
                "handover state is unavailable",
            ) from exc
        if durable_binding != binding:
            raise ConversationBoundaryError(
                409,
                "handover_session_conflict",
                "handover goal is already bound to another conversation",
            )
        return replace(
            proposal,
            body={
                **proposal.body,
                "prompt": f"@{agent_name} {prompt.strip()}",
                "target_agent": agent_name,
                "deadline_at": deadline,
            },
        )

    async def _mapped_agents(
        self,
        *,
        subject_ref: str,
        roles: frozenset[OperatorRole],
        reader_ref: str | None = None,
        required_duties: frozenset[str] | None = None,
    ) -> tuple[tuple[str, ...], str]:
        try:
            payload = await self.ownership.read(
                ProjectionQuery(
                    operation="stewardship.coverage",
                    principal_id=reader_ref or subject_ref,
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
        if (
            identity is None
            or not identity.active
            or identity.provider != "entra"
            or identity.principal_type != "person"
            or identity.subject_id.casefold() != subject_ref.casefold()
        ):
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
                    and (required_duties is None or subject.get("duty") in required_duties)
                ):
                    matched.append((duty_order.get(str(subject.get("duty")), 3), name))
                    break
        matched.sort(key=lambda item: (item[0], item[1]))
        allowed = []
        for _duty, name in matched:
            if self.contribution_guard is None or await self.contribution_guard.may_contribute(
                subject_ref=subject_ref, agent_name=name
            ):
                allowed.append(name)
        return tuple(allowed), source_revision

    async def _refresh_evidence(self, goal: dict[str, object]) -> dict[str, object]:
        evidence = _sequence(goal.get("evidence"), "handover goal evidence")
        if not evidence or goal.get("state") == "stale":
            return goal
        subject_ref = goal.get("subject_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            raise IamUnavailableError("handover goal subject is malformed")
        for raw in evidence:
            item = _mapping(raw, "handover goal evidence")
            evidence_ref = item.get("evidence_ref")
            digest = item.get("digest")
            if (
                not isinstance(evidence_ref, str)
                or _DOCUMENT_REF.fullmatch(evidence_ref) is None
                or not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None
            ):
                raise IamUnavailableError("handover goal evidence is malformed")
            _, document_id, version_id = evidence_ref.split(":", 2)
            admitted = await self.evidence_verifier.verify(
                principal_id=subject_ref,
                document_id=UUID(document_id),
                version_id=UUID(version_id),
                source_sha256=digest,
            )
            if admitted:
                continue
            revision = _positive_int(goal, "revision")
            updated = {
                **goal,
                "state": "stale",
                "revision": revision + 1,
                "stale_reason": "document_evidence_unavailable",
                "updated_at": _aware(self.clock()).isoformat(),
            }
            try:
                await self.store.append_revisioned_proposal(
                    family="iam",
                    operation="handover.evidence.stale",
                    principal_id=None,
                    idempotency_key=f"handover-stale:{goal['goal_id']}:{revision}",
                    payload={
                        "goal_id": goal["goal_id"],
                        "reason": "document_evidence_unavailable",
                        "execution_authority": False,
                    },
                    state_key=f"{_GOAL_PREFIX}{goal['goal_id']}",
                    state_value=updated,
                    expected_revision=revision,
                )
                return updated
            except PostgresProposalConflict:
                return await self._read_required(f"{_GOAL_PREFIX}{goal['goal_id']}")
            except PostgresFamilyStoreUnavailable as exc:
                raise IamUnavailableError("handover goal state is unavailable") from exc
        return goal

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


__all__ = [
    "PostgresHandoverActivityGuard",
    "PostgresHandoverEvidenceVerifier",
    "ProactiveHandoverRuntime",
]
