"""PostgreSQL projections and no-authority proposals for human report lines."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts import OperatorRole
from fdai_service_contracts.ontology_query import content_digest

from fdai_operator_service.families.iam.contracts import (
    IamPrincipal,
    JsonMapping,
    ReportingLineCaseQuery,
    ReportingLineCreateCommand,
    ReportingLineTransitionCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
    StoredStatePage,
)

_IAM_PROPOSAL_PREFIX = "operator-proposal:iam:"
_IAM_PROPOSAL_SCAN_LIMIT = 1_000


@dataclass(frozen=True, slots=True)
class PostgresReportingLines:
    """Read reporting evidence and persist inert review and contact commands."""

    store: PostgresFamilyStore

    async def list_report_line_case_page(
        self,
        query: ReportingLineCaseQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        items = self._visible(await self._cases(), principal=query.principal)
        return items[query.offset : query.offset + query.limit], len(items)

    async def get_report_line_case(
        self,
        case_id: str,
        *,
        principal: IamPrincipal,
    ) -> JsonMapping:
        item = next(
            (
                candidate
                for candidate in self._visible(await self._cases(), principal=principal)
                if candidate.get("operator_case_id") == case_id
            ),
            None,
        )
        if item is None:
            raise IamNotFoundError("reporting-line case was not found")
        return item

    async def create_report_line_case(
        self,
        command: ReportingLineCreateCommand,
    ) -> JsonMapping:
        stored = await self._proposal(
            "assignments.create",
            command,
            command.idempotency_key,
        )
        return _case_from_proposal(stored.record)

    async def confirm_report_line(
        self,
        command: ReportingLineTransitionCommand,
    ) -> JsonMapping:
        current = await self.get_report_line_case(command.case_id, principal=command.principal)
        if current.get("can_confirm") is not True:
            raise IamPermissionError("only a reporting-line endpoint may confirm the relationship")
        _check_transition(current, command, allowed={"confirm", "reject"})
        stored = await self._proposal(
            "assignments.confirm",
            command,
            _idempotency_key(command),
        )
        return {
            **dict(current),
            "pending_command_id": stored.proposal_id,
            "pending_operation": "confirm",
        }

    async def review_report_line(
        self,
        command: ReportingLineTransitionCommand,
    ) -> JsonMapping:
        current = await self.get_report_line_case(command.case_id, principal=command.principal)
        if current.get("can_review") is not True:
            raise IamPermissionError("reporting-line Owner review is not independent")
        _check_transition(current, command, allowed={"approve", "reject"})
        stored = await self._proposal(
            "assignments.review",
            command,
            _idempotency_key(command),
        )
        return {
            **dict(current),
            "pending_command_id": stored.proposal_id,
            "pending_operation": "review",
        }

    async def report_line_projection(self, query: ReportingLineCaseQuery) -> JsonMapping:
        visible = self._visible(await self._cases(), principal=query.principal)
        page = visible[query.offset : query.offset + query.limit]
        active = [item for item in visible if item.get("state") == "active"]
        revision_material = [
            {
                "case_id": item.get("case_id"),
                "edge_digest": item.get("edge_digest"),
                "subject_ref": item.get("subject_ref"),
                "manager_ref": item.get("manager_ref"),
            }
            for item in sorted(active, key=lambda value: str(value.get("case_id") or ""))
        ]
        return {
            "schema_version": "1.0.0",
            "graph_revision": content_digest(revision_material),
            "items": [dict(item) for item in page],
            "total": len(visible),
            "next_cursor": (
                query.offset + len(page) if query.offset + len(page) < len(visible) else None
            ),
            "summary": {
                "active": len(active),
                "pending_confirmation": _count(visible, "pending_confirmation"),
                "pending_owner_review": _count(visible, "pending_owner_review"),
                "conflict": _count(visible, "conflict"),
                "awaiting_core": _count(visible, "awaiting_core"),
            },
            "execution_authority": False,
            "approval_authority": False,
        }

    async def _cases(self) -> list[dict[str, object]]:
        page = await self._proposal_page()
        cases: list[dict[str, object]] = []
        for record in page.records:
            value = record.value
            payload = value.get("payload")
            if (
                value.get("operation") != "assignments.create"
                or not isinstance(payload, Mapping)
                or payload.get("case_kind") != "report_line"
            ):
                continue
            projected = _case_from_proposal(value)
            operator_case_id = str(projected["operator_case_id"])
            alias = await self._state("human_assignment:operator-case:" + operator_case_id)
            if alias is None:
                cases.append(projected)
                continue
            if alias.get("case_kind") != "report_line":
                raise IamUnavailableError("reporting-line Core alias is malformed")
            core_case_id = alias.get("case_id")
            if not isinstance(core_case_id, str) or not core_case_id:
                raise IamUnavailableError("reporting-line Core case reference is malformed")
            core = await self._state("human_reporting:case:" + core_case_id)
            if core is None:
                raise IamUnavailableError("reporting-line Core case is unavailable")
            cases.append(_case_from_core(projected, core))
        superseded = {
            item.get("supersedes_case_id") for item in cases if item.get("state") == "active"
        }
        cases = [
            {**item, "state": "superseded"} if item.get("case_id") in superseded else item
            for item in cases
        ]
        cases.sort(key=lambda item: str(item.get("operator_case_id") or ""), reverse=True)
        return cases

    @staticmethod
    def _visible(
        cases: list[dict[str, object]],
        *,
        principal: IamPrincipal,
    ) -> list[dict[str, object]]:
        actor = principal.oid.casefold()
        visible = (
            cases
            if OperatorRole.OWNER in principal.roles
            else [
                item
                for item in cases
                if actor
                in {
                    str(item.get("subject_ref") or "").casefold(),
                    str(item.get("manager_ref") or "").casefold(),
                }
            ]
        )
        projected: list[dict[str, object]] = []
        for item in visible:
            confirmation = item.get("confirmation")
            confirmer = (
                str(confirmation.get("principal_ref") or "").casefold()
                if isinstance(confirmation, Mapping)
                else ""
            )
            projected.append(
                {
                    **item,
                    "can_confirm": (
                        item.get("state") in {"pending_confirmation", "pending_owner_review"}
                        and actor != confirmer
                        and actor
                        in {
                            str(item.get("subject_ref") or "").casefold(),
                            str(item.get("manager_ref") or "").casefold(),
                        }
                    ),
                    "can_review": (
                        item.get("state") == "pending_owner_review"
                        and OperatorRole.OWNER in principal.roles
                        and actor
                        not in {
                            str(item.get("requester_ref") or "").casefold(),
                            str(item.get("subject_ref") or "").casefold(),
                            str(item.get("manager_ref") or "").casefold(),
                            confirmer,
                        }
                    ),
                }
            )
        return projected

    async def _proposal(
        self,
        operation: str,
        command: object,
        idempotency_key: str,
    ) -> StoredProposal:
        payload = _command_payload(command)
        try:
            return await self.store.append_proposal(
                family="iam",
                operation=operation,
                principal_id=_principal_id(payload),
                idempotency_key=idempotency_key,
                payload=payload,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _state(self, key: str) -> dict[str, object] | None:
        try:
            return await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("reporting-line state is unavailable") from exc

    async def _proposal_page(self) -> StoredStatePage:
        try:
            page = await self.store.read_state_page(
                prefix=_IAM_PROPOSAL_PREFIX,
                limit=_IAM_PROPOSAL_SCAN_LIMIT,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("reporting-line proposals are unavailable") from exc
        if page.truncated:
            raise IamUnavailableError("reporting-line proposal coverage is incomplete")
        return page


def _case_from_proposal(value: Mapping[str, object]) -> dict[str, object]:
    payload = value.get("payload")
    if not isinstance(payload, Mapping) or payload.get("case_kind") != "report_line":
        raise IamUnavailableError("stored reporting-line proposal is malformed")
    principal = payload.get("principal")
    if not isinstance(principal, Mapping):
        raise IamUnavailableError("stored reporting-line principal is malformed")
    proposal_id = value.get("proposal_id")
    request_digest = value.get("request_digest")
    if not isinstance(proposal_id, str) or not isinstance(request_digest, str):
        raise IamUnavailableError("stored reporting-line identity is malformed")
    return {
        "schema_version": "1.0.0",
        "operator_case_id": proposal_id,
        "request_digest": request_digest,
        "case_id": None,
        "candidate_id": payload.get("candidate_id"),
        "upload_id": payload.get("upload_id"),
        "requester_ref": principal.get("oid"),
        "subject_ref": None,
        "manager_ref": None,
        "effective_from": payload.get("effective_from"),
        "effective_until": payload.get("effective_until"),
        "supersedes_case_id": payload.get("supersedes_case_id"),
        "state": "awaiting_core",
        "revision": 0,
        "edge_digest": None,
        "directory_comparison": "unknown",
        "confirmation": None,
        "owner_review": None,
        "can_confirm": False,
        "can_review": False,
        "execution_authority": False,
        "approval_authority": False,
    }


def _case_from_core(
    proposal: Mapping[str, object],
    core: Mapping[str, object],
) -> dict[str, object]:
    required = {
        "case_id",
        "candidate_id",
        "upload_id",
        "requester_ref",
        "subject_ref",
        "manager_ref",
        "effective_from",
        "effective_until",
        "state",
        "revision",
        "edge_digest",
        "directory_comparison",
        "confirmation",
        "owner_review",
        "execution_authority",
        "approval_authority",
    }
    if (
        not required.issubset(core)
        or core.get("candidate_id") != proposal.get("candidate_id")
        or core.get("upload_id") != proposal.get("upload_id")
        or core.get("requester_ref") != proposal.get("requester_ref")
        or core.get("execution_authority") is not False
        or core.get("approval_authority") is not False
    ):
        raise IamUnavailableError("reporting-line Core projection is malformed")
    return {
        **dict(proposal),
        **{key: core.get(key) for key in required},
        "supersedes_case_id": core.get("supersedes_case_id"),
    }


def _check_transition(
    current: Mapping[str, object],
    command: ReportingLineTransitionCommand,
    *,
    allowed: set[str],
) -> None:
    if current.get("revision") != command.expected_revision:
        raise IamConflictError("reporting-line case revision is stale")
    if current.get("edge_digest") != command.edge_digest:
        raise IamConflictError("reporting-line edge digest is stale")
    if command.decision not in allowed:
        raise IamConflictError("reporting-line decision is invalid")


def _count(items: Sequence[Mapping[str, object]], state: str) -> int:
    return sum(item.get("state") == state for item in items)


def _idempotency_key(command: object) -> str:
    payload = _command_payload(command)
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def _principal_id(payload: Mapping[str, object]) -> str | None:
    requester = payload.get("requester_ref")
    if isinstance(requester, str) and requester:
        return requester
    principal = payload.get("principal")
    return str(principal.get("oid")) if isinstance(principal, Mapping) else None


def _command_payload(command: object) -> dict[str, object]:
    value = asdict(cast(Any, command))
    normalized = json.loads(json.dumps(value, default=_json_default))
    if not isinstance(normalized, dict):
        raise ValueError("reporting-line command MUST serialize to an object")
    return cast(dict[str, object], normalized)


def _json_default(value: object) -> object:
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


__all__ = ["PostgresReportingLines"]
