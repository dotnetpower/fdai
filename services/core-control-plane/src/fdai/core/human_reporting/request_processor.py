"""Apply authenticated report-line commands through the fixed assignment handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai_service_contracts.assignment_transport import AssignmentRequestNotice

from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_reporting.model import EndpointDecision, OwnerDecision, ReportingLineCase
from fdai.core.human_reporting.service import ReportingLineService, report_line_case_result
from fdai.core.human_reporting.source import ReportingLineDraftReader
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role

_ALIAS = "human_assignment:operator-case:"
_RESULT = "human_assignment:command-result:"


@dataclass(frozen=True, slots=True)
class ReportingLineRequestProcessor:
    """Separate source validation, endpoint confirmation, and Owner review."""

    intake: AssignmentRequestIntake
    cases: ReportingLineService
    drafts: ReportingLineDraftReader

    async def source(
        self,
        notice: AssignmentRequestNotice,
        *,
        at: datetime,
    ) -> tuple[Mapping[str, Any], Principal]:
        """Resolve the exact immutable Operator receipt and its authenticated principal."""

        raw = await self.intake.receipts.read_state(notice.proposal_ref)
        if self.intake.receipt_reason(notice, raw, at=at) != "verified_operator_receipt":
            raise PermissionError("reporting-line request receipt is unavailable or changed")
        if raw is None or notice.schema_version != "1.3.0":
            raise ValueError("reporting-line requests require transport 1.3.0")
        payload = raw.get("payload")
        if not isinstance(payload, Mapping) or payload.get("case_kind") != "report_line":
            raise ValueError("reporting-line request payload is invalid")
        expected = {"principal", "case_kind"} | (
            {
                "idempotency_key",
                "upload_id",
                "candidate_id",
                "effective_from",
                "effective_until",
                "supersedes_case_id",
            }
            if notice.operation == "assignments.create"
            else {
                "case_id",
                "expected_revision",
                "decision",
                "edge_digest",
            }
        )
        if set(payload) != expected:
            raise ValueError("reporting-line request fields do not match the command")
        principal_value = payload.get("principal")
        if not isinstance(principal_value, Mapping):
            raise ValueError("reporting-line request principal is unavailable")
        oid = _text(principal_value, "oid")
        if oid != oid.casefold():
            raise ValueError("reporting-line principal MUST already be normalized")
        roles_value = principal_value.get("roles")
        if not isinstance(roles_value, list):
            raise ValueError("reporting-line principal roles MUST be an array")
        try:
            roles = frozenset(Role(str(item)) for item in roles_value)
        except ValueError as exc:
            raise ValueError("reporting-line principal role is invalid") from exc
        return payload, Principal(oid=oid, roles=roles)

    async def validate(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Forseti validates current source and command shape without writing state."""

        payload, principal = await self.source(notice, at=at)
        if notice.operation == "assignments.create":
            artifact = await self.drafts.get(UUID(_text(payload, "upload_id")))
            candidate_id = _text(payload, "candidate_id")
            if not any(item.candidate_id == candidate_id for item in artifact.candidates):
                raise ValueError("reporting-line candidate is not reviewable")
            if Role.CONTRIBUTOR not in principal.roles and not {
                Role.APPROVER,
                Role.OWNER,
            }.intersection(principal.roles):
                raise PermissionError("reporting-line import requires Contributor or higher")
            return
        if notice.operation not in {"assignments.confirm", "assignments.review"}:
            raise ValueError("reporting-line validation requires create, confirm, or review")
        current = await self.case(notice, payload)
        if _revision(payload) != current.revision:
            raise ValueError("reporting-line command revision is stale")
        if _text(payload, "edge_digest") != current.edge_digest:
            raise ValueError("reporting-line command digest is stale")
        if notice.operation == "assignments.review":
            OwnerDecision(_text(payload, "decision"))
            return
        if principal.oid not in {current.subject_ref, current.manager_ref}:
            raise PermissionError("only a reporting-line endpoint may confirm")
        EndpointDecision(_text(payload, "decision"))

    async def validate_review(self, notice: AssignmentRequestNotice, *, at: datetime) -> None:
        """Var rechecks an endpoint confirmation or independent Owner review."""

        if notice.operation == "assignments.confirm":
            await self.validate(notice, at=at)
            return
        if notice.operation != "assignments.review":
            raise ValueError("reporting-line Owner review requires a review command")
        payload, principal = await self.source(notice, at=at)
        current = await self.case(notice, payload)
        if Role.OWNER not in principal.roles:
            raise PermissionError("reporting-line review requires Owner")
        if current.confirmation is None or principal.oid in {
            current.requester_ref,
            current.subject_ref,
            current.manager_ref,
            current.confirmation.principal_ref,
        }:
            raise PermissionError("reporting-line Owner review is not independent")
        if _revision(payload) != current.revision:
            raise ValueError("reporting-line Owner review revision is stale")
        OwnerDecision(_text(payload, "decision"))
        if _text(payload, "edge_digest") != current.edge_digest:
            raise ValueError("reporting-line Owner review digest is stale")

    async def case(
        self,
        notice: AssignmentRequestNotice,
        payload: Mapping[str, Any],
    ) -> ReportingLineCase:
        """Resolve a Core case through the exact creation proposal alias."""

        if _text(payload, "case_id") != notice.case_id:
            raise ValueError("reporting-line command case identity is inconsistent")
        alias = await self.cases.store.read_state(_ALIAS + notice.case_id)
        if alias is None or alias.get("case_kind") != "report_line":
            raise ValueError("reporting-line creation has not converged")
        return await self.cases.get_case(_text(alias, "case_id"))

    async def apply(
        self,
        notice: AssignmentRequestNotice,
        *,
        at: datetime,
    ) -> Mapping[str, object]:
        """Materialize one Saga-sealed command and retain its exact result."""

        result_key = _RESULT + notice.proposal_id
        previous = await self.cases.store.read_state(result_key)
        if previous is not None:
            if previous.get("request_digest") != notice.proposal_digest:
                raise ValueError("reporting-line result does not match its command")
            return previous
        payload, principal = await self.source(notice, at=at)
        if notice.operation == "assignments.create":
            await self.validate(notice, at=at)
            artifact = await self.drafts.get(UUID(_text(payload, "upload_id")))
            current = await self.cases.create_case(
                principal=principal,
                artifact=artifact,
                candidate_id=_text(payload, "candidate_id"),
                effective_from=_optional_instant(payload, "effective_from"),
                effective_until=_optional_instant(payload, "effective_until"),
                supersedes_case_id=_optional_text(payload, "supersedes_case_id"),
                now=notice.accepted_at,
            )
            alias = {
                "case_id": current.case_id,
                "case_kind": "report_line",
                "request_digest": notice.proposal_digest,
            }
            created = await self.cases.store.write_state_with_audit_if_absent(
                _ALIAS + notice.case_id,
                alias,
                {
                    "actor": "Saga",
                    "action_kind": "human.reporting.operator_reference_bound",
                    "case_id": current.case_id,
                    "edge_digest": current.edge_digest,
                    "mode": "shadow",
                },
            )
            if not created and await self.cases.store.read_state(_ALIAS + notice.case_id) != alias:
                raise ValueError("reporting-line creation reference conflicts")
        else:
            current = await self.case(notice, payload)
            if notice.operation == "assignments.confirm":
                await self.validate(notice, at=at)
                current = await self.cases.confirm(
                    principal=principal,
                    case_id=current.case_id,
                    expected_revision=_revision(payload),
                    decision=EndpointDecision(_text(payload, "decision")),
                    edge_digest=_text(payload, "edge_digest"),
                    now=notice.accepted_at,
                )
            else:
                await self.validate_review(notice, at=at)
                current = await self.cases.review(
                    principal=principal,
                    case_id=current.case_id,
                    expected_revision=_revision(payload),
                    decision=OwnerDecision(_text(payload, "decision")),
                    edge_digest=_text(payload, "edge_digest"),
                    now=notice.accepted_at,
                )
        result = report_line_case_result(
            current,
            proposal_id=notice.proposal_id,
            request_digest=notice.proposal_digest,
            operator_case_id=notice.case_id,
        )
        created_result = await self.cases.store.write_state_with_audit_if_absent(
            result_key,
            result,
            {
                "actor": "Saga",
                "action_kind": "human.reporting.command_materialized",
                "proposal_id": notice.proposal_id,
                "case_id": current.case_id,
                "edge_digest": current.edge_digest,
                "mode": "shadow",
            },
        )
        if created_result:
            return result
        winner = await self.cases.store.read_state(result_key)
        if winner != result:
            raise ValueError("reporting-line result conflicts after materialization")
        return result


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or item != item.strip():
        raise ValueError("reporting-line command requires exact non-empty text")
    return item


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item or item != item.strip():
        raise ValueError("reporting-line optional reference is invalid")
    return item


def _revision(value: Mapping[str, Any]) -> int:
    item = value.get("expected_revision")
    if type(item) is not int or item < 1:
        raise ValueError("reporting-line command revision MUST be positive")
    return item


def _optional_instant(value: Mapping[str, Any], key: str) -> datetime | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError("reporting-line effective time MUST be timestamp text")
    parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reporting-line effective time MUST be timezone-aware")
    return parsed


__all__ = ["ReportingLineRequestProcessor"]
