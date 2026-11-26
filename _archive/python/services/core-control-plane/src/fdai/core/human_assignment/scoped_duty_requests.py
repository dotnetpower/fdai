"""Resolve immutable Operator scoped requests inside the existing fixed-agent handoff."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.assignment_transport import AssignmentRequestNotice
from fdai_service_contracts.scoped_duty import ScopedDutyRequest

from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.scoped_duty_case_model import ScopedDutyCase, ScopedDutyCommand
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService

_ALIAS = "human_assignment:operator-case:"
_RESULT = "human_assignment:command-result:"


@dataclass(frozen=True, slots=True)
class ScopedDutyRequestProcessor:
    """Separate Forseti validation, Var review, and Saga-sealed Muninn state materialization.

    Version 1.2 is exclusively ownership-only. A personal assignment cannot borrow this
    branch, and an old consumer cannot reinterpret a group or schedule as an IAM subject.
    """

    intake: AssignmentRequestIntake
    cases: ScopedDutyCaseService

    async def source(self, notice: AssignmentRequestNotice) -> tuple[Mapping[str, Any], str]:
        """Resolve the exact insert-only Operator receipt, not its editable presentation."""
        raw = await self.intake.receipts.read_state(notice.proposal_ref)
        if (
            self.intake.receipt_reason(notice, raw, at=self.cases.clock())
            != "verified_operator_receipt"
        ):
            raise PermissionError("scoped duty request receipt is unavailable or changed")
        if raw is None or notice.schema_version != "1.2.0":
            raise ValueError("scoped duty requests require transport 1.2.0")
        payload = raw["payload"]
        base = {"principal", "case_kind"}
        allowed = base | (
            {"idempotency_key", "request", "justification"}
            if notice.operation == "assignments.create"
            else {"case_id", "expected_revision"}
            | ({"decision", "plan_digest"} if notice.operation == "assignments.review" else set())
        )
        if set(payload) != allowed or payload.get("case_kind") != "scoped_duty":
            raise ValueError("scoped duty request fields do not match the ownership-only contract")
        actor = text(payload["principal"], "oid")
        if actor != actor.casefold():
            raise ValueError("scoped duty actor MUST already be normalized")
        return payload, actor

    async def case(
        self, notice: AssignmentRequestNotice, payload: Mapping[str, Any]
    ) -> ScopedDutyCase:
        """Bind a case alias to its exact sealed creation command and distinct namespace."""
        alias = await self.cases.store.read_state(_ALIAS + notice.case_id)
        if alias is None or alias.get("case_kind") != "scoped_duty":
            raise ValueError("scoped duty creation has not converged")
        current = await self.cases.get(text(alias, "case_id"))
        original = ScopedDutyCommand(
            proposal_id=notice.case_id, request_digest=text(alias, "request_digest")
        )
        if current.command_receipt(original) is None or text(payload, "case_id") != notice.case_id:
            raise ValueError("scoped duty alias does not match its sealed creation")
        return current

    async def validate(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Forseti reads current scope, identity, and immutable command shape without writes."""
        # Each I/O boundary uses the explicitly injected current clock, not a stale caller time.
        del at
        async with asyncio.timeout(self.cases.planner.policy.total_timeout_seconds):
            payload, actor = await self.source(notice)
            await self.cases.require_owner(actor)
            if notice.operation == "assignments.create":
                ScopedDutyRequest.model_validate(payload["request"])
            else:
                current = await self.case(notice, payload)
                if (
                    current.revision != revision(payload)
                    and current.command_receipt(receipt(notice)) is None
                ):
                    raise ValueError("scoped duty command revision is stale")
                if notice.operation == "assignments.submit" and actor != current.requester_ref:
                    raise PermissionError("only the scoped requester may submit")
            await self.source(notice)

    async def validate_review(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Var rechecks every independent current Owner and the exact human-reviewed plan."""
        del at
        if notice.operation != "assignments.review":
            raise ValueError("scoped human review requires a review command")
        async with asyncio.timeout(self.cases.planner.policy.total_timeout_seconds):
            payload, actor = await self.source(notice)
            current = await self.case(notice, payload)
            if text(payload, "decision") not in {"approve", "reject"}:
                raise ValueError("scoped duty review decision is invalid")
            await self.cases.check_review(
                current, actor=actor, plan_digest=text(payload, "plan_digest")
            )
            await self.source(notice)

    async def apply(self, notice: AssignmentRequestNotice, *, at: datetime) -> Mapping[str, object]:
        """Materialize Saga's seal; original command receipts repair interrupted results."""
        async with asyncio.timeout(self.cases.planner.policy.total_timeout_seconds):
            await self.validate(notice, at=at)
            payload, actor = await self.source(notice)
            if notice.operation == "assignments.create":
                current = await self.cases.create(
                    actor=actor,
                    idempotency_key=text(payload, "idempotency_key"),
                    request=ScopedDutyRequest.model_validate(payload["request"]),
                    justification=text(payload, "justification"),
                    command=receipt(notice),
                    accepted_at=notice.accepted_at,
                )
                alias = {
                    "case_id": current.case_id,
                    "case_kind": "scoped_duty",
                    "request_digest": notice.proposal_digest,
                }
                created = await self.cases.store.write_state_with_audit_if_absent(
                    _ALIAS + notice.case_id,
                    alias,
                    self.cases.audit(current, "operator_reference_bound", actor),
                )
                if (
                    not created
                    and await self.cases.store.read_state(_ALIAS + notice.case_id) != alias
                ):
                    raise ValueError("scoped duty creation reference conflicts")
            else:
                current = await self.case(notice, payload)
                if notice.operation == "assignments.submit":
                    current = await self.cases.submit(
                        case_id=current.case_id,
                        actor=actor,
                        expected_revision=revision(payload),
                        command=receipt(notice),
                        accepted_at=notice.accepted_at,
                    )
                else:
                    current = await self.cases.review(
                        case_id=current.case_id,
                        actor=actor,
                        expected_revision=revision(payload),
                        decision=text(payload, "decision"),
                        plan_digest=text(payload, "plan_digest"),
                        command=receipt(notice),
                        accepted_at=notice.accepted_at,
                    )
            key = _RESULT + notice.proposal_id
            retained = current.command_receipt(receipt(notice))
            if (
                retained is None
                or retained.result_state is None
                or retained.result_revision is None
            ):
                raise ValueError("scoped duty original command result is unavailable")
            result: dict[str, object] = {
                "schema_version": "1.2.0",
                "proposal_id": notice.proposal_id,
                "request_digest": notice.proposal_digest,
                "operator_case_id": notice.case_id,
                "case_id": current.case_id,
                "state": retained.result_state,
                "revision": retained.result_revision,
                "execution_authority": False,
            }
            previous = await self.cases.store.read_state(key)
            if previous is not None:
                if previous != result:
                    raise ValueError(
                        "scoped duty result differs from the original command transition"
                    )
                return previous
            if await self.cases.store.write_state_with_audit_if_absent(
                key, result, self.cases.audit(current, "command_materialized", actor)
            ):
                return result
            winner = await self.cases.store.read_state(key)
            if winner != result:
                raise ValueError("scoped duty result conflicts after a concurrent command")
            return result


def receipt(notice: AssignmentRequestNotice) -> ScopedDutyCommand:
    """Bind the complete authenticated payload digest, not just case revision or timestamp."""
    return ScopedDutyCommand(proposal_id=notice.proposal_id, request_digest=notice.proposal_digest)


def text(value: Mapping[str, Any], key: str) -> str:
    """Reject malformed source fields without including private values in the error."""
    item = value.get(key)
    if not isinstance(item, str) or not item or item != item.strip():
        raise ValueError("scoped duty command requires exact nonempty text")
    return item


def revision(value: Mapping[str, Any]) -> int:
    """Revision fences accept only explicit positive integers."""
    item = value.get("expected_revision")
    if type(item) is not int or item < 1:
        raise ValueError("scoped duty command revision MUST be a positive integer")
    return item


__all__ = ["ScopedDutyRequestProcessor"]
