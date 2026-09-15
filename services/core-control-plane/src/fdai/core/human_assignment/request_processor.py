"""Apply audit-sealed Operator commands to the canonical assignment case lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.assignment_transport import AssignmentRequestNotice

from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
from fdai.core.human_assignment.coverage import (
    normalize_principal_ref,
    validate_duty_bindings,
    validate_reviewer,
)
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    ProviderSubject,
    ReviewDecision,
)
from fdai.core.human_assignment.repository import assignment_case_id
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.revocation_intent import AssignmentRevocation
from fdai.core.human_assignment.revocation_target import require_revocation_target
from fdai.core.human_assignment.scoped_duty_requests import ScopedDutyRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty

_ALIAS_PREFIX = "human_assignment:operator-case:"
_RESULT_PREFIX = "human_assignment:command-result:"


@dataclass(frozen=True, slots=True)
class AssignmentRequestProcessor:
    """Keep validation, human review, and sealed projection as separate agent operations.

    Only the audit-sealed materializer calls ``apply``. Source receipts are read-only evidence,
    not a mutable Operator approval projection. Actual IAM effects remain behind Thor's
    independently promoted ActionType and are never called by this processor.
    """

    intake: AssignmentRequestIntake
    cases: AssignmentCaseService
    scoped: ScopedDutyRequestProcessor | None = None

    async def validate(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Forseti validates exact source identity, command shape, and current case revision."""
        if notice.schema_version == "1.2.0":
            if self.scoped is None:
                raise ValueError("scoped duty current-source bindings are unavailable")
            await self.scoped.validate(notice, at=at)
            return
        payload, principal = await self._source(notice, at=at)
        if notice.operation == "assignments.create":
            intent = self._intent(payload, principal)
            validate_duty_bindings(intent.duty_bindings)
            if intent.revocation is not None:
                await require_revocation_target(
                    self.cases.store,
                    intent,
                    revocation_case_id=assignment_case_id(
                        intent.requester_ref, intent.idempotency_key
                    ),
                )
            return
        case = await self._case(payload)
        expected = _revision(payload)
        if case.revision != expected:
            # A completed exact command is replay, not a stale new transition.
            if _receipt(notice) not in case.command_receipts:
                raise ValueError("assignment command revision is stale")
            return
        if notice.operation == "assignments.submit":
            if case.intent.requester_ref.casefold() != principal.oid.casefold():
                raise PermissionError("only the requester may submit the assignment")
            if case.state is not AssignmentState.DRAFT:
                raise ValueError("assignment submission requires a draft")
        elif case.state is not AssignmentState.PENDING_REVIEW:
            raise ValueError("assignment review requires a pending case")

    async def validate_review(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Var rechecks the authenticated independent Owner; a notice never supplies roles."""
        if notice.schema_version == "1.2.0":
            if self.scoped is None:
                raise ValueError("scoped duty current-source bindings are unavailable")
            await self.scoped.validate_review(notice, at=at)
            return
        if notice.operation != "assignments.review":
            raise ValueError("human review requires a review command")
        payload, principal = await self._source(notice, at=at)
        case = await self._case(payload)
        decision = ReviewDecision(_text(payload, "decision"))
        actor = normalize_principal_ref(principal.oid)
        existing = next(
            (item for item in case.reviews if normalize_principal_ref(item.reviewer_ref) == actor),
            None,
        )
        if existing is not None and (
            existing.decision is not decision or existing.reviewed_at != notice.accepted_at
        ):
            raise ValueError("assignment review differs from the recorded command")
        prior = tuple(
            item for item in case.reviews if normalize_principal_ref(item.reviewer_ref) != actor
        )
        validate_reviewer(
            case.intent,
            reviewer_ref=principal.oid,
            reviewer_roles=principal.roles,
            prior_reviews=prior,
        )

    async def apply(self, notice: AssignmentRequestNotice, *, at: datetime) -> Mapping[str, object]:
        """Materialize a Saga-sealed command once, with recovery after an interrupted write."""
        if notice.schema_version == "1.2.0":
            if self.scoped is None:
                raise ValueError("scoped duty current-source bindings are unavailable")
            return await self.scoped.apply(notice, at=at)
        payload, principal = await self._source(notice, at=at)
        result_key = f"{_RESULT_PREFIX}{notice.proposal_id}"
        previous = await self.cases.store.read_state(result_key)
        if previous is not None:
            if previous.get("request_digest") != notice.proposal_digest:
                raise ValueError("assignment result does not match the exact command")
            return previous
        await self.validate(notice, at=at)
        if notice.operation == "assignments.create":
            case = await self.cases.create_case(
                principal=principal,
                intent=self._intent(payload, principal),
                now=notice.accepted_at,
                command_receipt=_receipt(notice),
            )
            alias_key = f"{_ALIAS_PREFIX}{notice.proposal_id}"
            alias = {"case_id": case.case_id, "request_digest": notice.proposal_digest}
            created_alias = await self.cases.store.write_state_with_audit_if_absent(
                alias_key,
                alias,
                {
                    "actor": "Saga",
                    "action_kind": "human.assignment.operator_reference_bound",
                    "proposal_id": notice.proposal_id,
                    "case_id": case.case_id,
                    "mode": "shadow",
                },
            )
            if not created_alias and await self.cases.store.read_state(alias_key) != alias:
                raise ValueError("assignment reference conflicts with an existing case")
            operator_case_id = notice.proposal_id
        else:
            case = await self._case(payload)
            operator_case_id = _text(payload, "case_id")
            if notice.operation == "assignments.submit":
                case = await self.cases.submit_for_review(
                    principal=principal,
                    case_id=case.case_id,
                    expected_revision=_revision(payload),
                    now=notice.accepted_at,
                    command_receipt=_receipt(notice),
                )
            else:
                await self.validate_review(notice, at=at)
                case = await self.cases.review(
                    principal=principal,
                    case_id=case.case_id,
                    expected_revision=_revision(payload),
                    decision=ReviewDecision(_text(payload, "decision")),
                    now=notice.accepted_at,
                    command_receipt=_receipt(notice),
                )
        result: dict[str, object] = {
            **({"schema_version": "1.1.0"} if case.intent.revocation is not None else {}),
            "proposal_id": notice.proposal_id,
            "request_digest": notice.proposal_digest,
            "operator_case_id": operator_case_id,
            "case_id": case.case_id,
            "state": case.state.value,
            "revision": case.revision,
            "execution_authority": False,
        }
        created_result = await self.cases.store.write_state_with_audit_if_absent(
            result_key,
            result,
            {"actor": "Saga", "action_kind": "human.assignment.command_materialized", **result},
        )
        if not created_result:
            winner = await self.cases.store.read_state(result_key)
            if winner is None or winner.get("request_digest") != notice.proposal_digest:
                raise ValueError("assignment command result conflicts after create race")
            return winner
        return result

    async def _source(
        self, notice: AssignmentRequestNotice, *, at: datetime
    ) -> tuple[Mapping[str, Any], Principal]:
        record = await self.intake.receipts.read_state(notice.proposal_ref)
        reason = self.intake.receipt_reason(notice, record, at=at)
        if reason != "verified_operator_receipt" or record is None:
            raise PermissionError(reason)
        payload = record["payload"]
        if notice.schema_version != "1.1.0":
            removal = payload.get("revocation") is not None
            if notice.operation != "assignments.create":
                removal = (await self._case(payload)).intent.revocation is not None
            if removal:
                raise ValueError("revocation commands require transport version 1.1.0")
        principal = payload["principal"]
        return payload, Principal(
            oid=principal["oid"],
            roles=frozenset(Role(role) for role in principal["roles"]),
        )

    async def _case(self, payload: Mapping[str, Any]) -> AssignmentCase:
        operator_case_id = _text(payload, "case_id")
        alias = await self.cases.store.read_state(f"{_ALIAS_PREFIX}{operator_case_id}")
        if alias is None:
            raise ValueError("assignment creation has not converged")
        case = await self.cases.get_case(_text(alias, "case_id"))
        creation = AssignmentCommandReceipt(operator_case_id, _text(alias, "request_digest"))
        if creation not in case.command_receipts:
            raise ValueError("assignment reference does not match its sealed creation")
        return case

    @staticmethod
    def _intent(payload: Mapping[str, Any], principal: Principal) -> AssignmentIntent:
        duties = payload.get("duty_bindings")
        goals = payload.get("goal_refs")
        if (
            not isinstance(duties, list)
            or not 1 <= len(duties) <= 30
            or any(not isinstance(item, Mapping) for item in duties)
            or not isinstance(goals, list)
            or len(goals) > 20
            or any(not isinstance(item, str) for item in goals)
        ):
            raise ValueError("assignment duties or goals are malformed")
        if _text(payload, "subject_provider") != "entra":
            raise ValueError("assignment subject provider is not supported")
        revocation = payload.get("revocation")
        if revocation is not None and not isinstance(revocation, Mapping):
            raise ValueError("assignment revocation MUST be an object")
        return AssignmentIntent(
            idempotency_key=_text(payload, "idempotency_key"),
            subject=ProviderSubject("entra", _text(payload, "subject_id")),
            requested_role=Role(_text(payload, "requested_role")),
            duty_bindings=tuple(
                DutyBinding(
                    _text(item, "agent_name"),
                    Duty(_text(item, "duty")),
                    _text(item, "scope_ref"),
                )
                for item in duties
            ),
            goal_refs=tuple(goals),
            requester_ref=principal.oid,
            justification=_text(payload, "justification"),
            revocation=(
                AssignmentRevocation.from_dict(revocation) if revocation is not None else None
            ),
        )


def _receipt(notice: AssignmentRequestNotice) -> AssignmentCommandReceipt:
    return AssignmentCommandReceipt(notice.proposal_id, notice.proposal_digest)


def _text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"assignment {key} MUST be non-empty text")
    return result


def _revision(value: Mapping[str, Any]) -> int:
    result = value.get("expected_revision")
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ValueError("assignment expected_revision MUST be a positive integer")
    return result


__all__ = ["AssignmentRequestProcessor"]
