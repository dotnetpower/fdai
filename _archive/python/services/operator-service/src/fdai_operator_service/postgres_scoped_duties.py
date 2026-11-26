"""Persist scoped requests through the existing immutable Operator assignment outbox."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.assignment_transport import assignment_content_digest
from fdai_service_contracts.scoped_duty import ScopedDutyRequest

from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)


@dataclass(frozen=True, slots=True)
class PostgresScopedDuties:
    """Projection reader and proposal writer only; Core remains the single scoped case writer."""

    store: PostgresFamilyStore

    async def create(
        self,
        *,
        principal: IamPrincipal,
        idempotency_key: str,
        request: ScopedDutyRequest,
        justification: str,
    ) -> Mapping[str, object]:
        """Queue exact typed intent without converting its group or schedule into personal IAM."""
        if not 1 <= len(idempotency_key) <= 160 or idempotency_key != idempotency_key.strip():
            raise ValueError("scoped duty idempotency key MUST be exact and at most 160 characters")
        key = "scoped-create:" + assignment_content_digest(
            {"actor": principal.oid, "key": idempotency_key}
        )
        return await self._proposal(
            principal,
            "assignments.create",
            key,
            {
                "idempotency_key": idempotency_key,
                "request": request.model_dump(mode="json"),
                "justification": justification,
            },
        )

    async def get(self, case_id: str) -> Mapping[str, object]:
        """Join exact immutable creation and Core alias without trusting a displayed approval."""
        if re.fullmatch(r"operator-[a-f0-9]{32}", case_id) is None:
            raise ValueError("scoped duty request id is invalid")
        try:
            source = await self.store.find_state(
                prefix="operator-proposal:iam:",
                field="proposal_id",
                value=case_id,
            )
            if source is None:
                raise IamNotFoundError("scoped duty request was not found")
            record = source
            payload = record.get("payload")
            if (
                record.get("operation") != "assignments.create"
                or not isinstance(payload, Mapping)
                or payload.get("case_kind") != "scoped_duty"
            ):
                raise IamNotFoundError("request is not an ownership-only scoped case")
            alias = await self.store.read_state("human_assignment:operator-case:" + case_id)
            if alias is None:
                return {
                    "case_id": case_id,
                    "state": "awaiting_core",
                    "revision": None,
                    "request": payload["request"],
                }
            if alias.get("case_kind") != "scoped_duty" or alias.get("request_digest") != record.get(
                "request_digest"
            ):
                raise IamUnavailableError("scoped duty source identity is inconsistent")
            core_id = alias.get("case_id")
            if not isinstance(core_id, str):
                raise IamUnavailableError("scoped duty Core identity is unavailable")
            case = await self.store.read_state("human_assignment:scoped-case:" + core_id)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("scoped duty current state is unavailable") from exc
        if (
            case is None
            or case.get("kind") != "scoped_duty_case"
            or case.get("case_id") != core_id
            or case.get("execution_authority") is not False
            or type(case.get("revision")) is not int
            or case.get("request") != payload.get("request")
        ):
            raise IamUnavailableError("scoped duty current state is inconsistent")
        plan = case.get("plan_json")
        if not isinstance(plan, str) or len(plan) > 1_048_576:
            raise IamUnavailableError("scoped duty plan is unavailable")
        try:
            decoded = json.loads(plan)
        except ValueError as exc:
            raise IamUnavailableError("scoped duty plan is invalid") from exc
        if (
            not isinstance(decoded, dict)
            or decoded.get("kind") != "scoped_duty_review"
            or decoded.get("schema_version") != "1.0.0"
            or decoded.get("source_revision")
            != ScopedDutyRequest.model_validate(payload["request"]).source_revision
            or decoded.get("execution_authority") is not False
            or decoded.get("review_required") is not True
            or decoded.get("digest")
            != hashlib.sha256(
                json.dumps(
                    {k: v for k, v in decoded.items() if k != "digest"},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
        ):
            raise IamUnavailableError("scoped duty plan is invalid")
        commands = case.get("commands")
        if (
            not isinstance(commands, list)
            or not 1 <= len(commands) <= 100
            or not any(
                isinstance(item, dict)
                and item.get("proposal_id") == case_id
                and item.get("request_digest") == record["request_digest"]
                for item in commands
            )
        ):
            raise IamUnavailableError("scoped duty source has no exact Core command receipt")
        return {
            "case_id": case_id,
            "core_case_id": core_id,
            "state": case["state"],
            "revision": case["revision"],
            "requester_ref": case["requester_ref"],
            "request": case["request"],
            "plan": decoded,
            "reviews": case["reviews"],
            "pr_ref": case.get("pr_ref"),
            "candidate_digest": case.get("candidate_digest"),
            "merge_commit_sha": case.get("merge_commit_sha"),
            "execution_authority": False,
        }

    async def transition(
        self,
        *,
        principal: IamPrincipal,
        case_id: str,
        expected_revision: int,
        decision: str | None = None,
        plan_digest: str | None = None,
    ) -> Mapping[str, object]:
        """Fence HTTP input, then retain only proposal intent; Var/Core own actual review."""
        current = await self.get(case_id)
        if current["revision"] != expected_revision:
            raise IamConflictError("scoped duty case revision is stale")
        fields: dict[str, object] = {"case_id": case_id, "expected_revision": expected_revision}
        operation = "assignments.submit"
        if decision is None:
            if principal.oid != current["requester_ref"] or current["state"] != "draft":
                raise IamConflictError("only the requester may submit an exact scoped draft")
        else:
            if (
                current["state"] != "pending_review"
                or decision not in {"approve", "reject"}
                or principal.oid == current["requester_ref"]
            ):
                raise IamConflictError("scoped review requires an independent current pending case")
            if (
                not isinstance(plan_digest, str)
                or re.fullmatch(r"[a-f0-9]{64}", plan_digest) is None
            ):
                raise ValueError("scoped review requires the exact plan digest")
            fields.update(decision=decision, plan_digest=plan_digest)
            operation = "assignments.review"
        key = "scoped-command:" + assignment_content_digest(
            {"actor": principal.oid, "operation": operation, **fields}
        )
        return await self._proposal(principal, operation, key, fields)

    async def projection(self, *, agent_name: str, scope_ref: str) -> Mapping[str, object]:
        """Read an exact scope observation with its original non-sliding expiry."""
        value = await self._observation("human_assignment:scoped-observation", None, None)
        items = value.get("items")
        if not isinstance(items, list) or len(items) > 600:
            raise IamUnavailableError("scoped duty observation is malformed")
        matches = [
            row
            for row in items
            if isinstance(row, dict)
            and (row.get("agent_name"), row.get("scope_ref")) == (agent_name, scope_ref)
        ]
        if len(matches) != 1:
            raise IamUnavailableError("exact scoped duty evidence is unavailable")
        return {
            **matches[0],
            "observed_at": value["observed_at"],
            "expires_at": value["expires_at"],
            "source_revision": value["source_revision"],
            "partial": value["partial"],
            "invalid_cases": value["invalid_cases"],
            "execution_authority": False,
        }

    async def catalog(self) -> Mapping[str, object]:
        """Read only the bounded Core-materialized scope catalog, never local guessed config."""
        value = await self._observation("human_assignment:scoped-observation", None, None)
        return {
            key: value[key]
            for key in (
                "source_revision",
                "scopes",
                "observed_at",
                "expires_at",
                "execution_authority",
                "artifact_delivery_available",
            )
        }

    async def _observation(
        self, key: str, agent: str | None, scope: str | None
    ) -> Mapping[str, object]:
        try:
            value = await self.store.read_state(key)
            if value is None:
                raise IamUnavailableError("scoped duty observation is not currently available")
            start = datetime.fromisoformat(str(value["observed_at"]))
            end = datetime.fromisoformat(str(value["expires_at"]))
            if (
                start.tzinfo is None
                or end.tzinfo is None
                or not start <= datetime.now(UTC) < end
                or (end - start).total_seconds() > 300
                or value.get("execution_authority") is not False
                or (
                    agent is not None
                    and (value.get("agent_name"), value.get("scope_ref")) != (agent, scope)
                )
            ):
                raise IamUnavailableError("scoped duty observation is expired or inconsistent")
            return value
        except (KeyError, TypeError, ValueError, PostgresFamilyStoreUnavailable) as exc:
            raise IamUnavailableError("scoped duty observation is invalid or unavailable") from exc

    async def _proposal(
        self,
        principal: IamPrincipal,
        operation: str,
        key: str,
        fields: Mapping[str, object],
    ) -> Mapping[str, object]:
        try:
            stored = await self.store.append_proposal(
                family="iam",
                operation=operation,
                principal_id=principal.oid,
                idempotency_key=key,
                payload={
                    "principal": {
                        "oid": principal.oid,
                        "roles": sorted(role.value for role in principal.roles),
                    },
                    "case_kind": "scoped_duty",
                    **fields,
                },
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError("scoped duty request conflicts with an earlier payload") from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("scoped duty request outbox is unavailable") from exc
        return {
            "case_id": (
                stored.proposal_id if operation == "assignments.create" else fields["case_id"]
            ),
            "proposal_id": stored.proposal_id,
            "accepted_at": stored.accepted_at,
            "state": "awaiting_core",
            "execution_authority": False,
        }


__all__ = ["PostgresScopedDuties"]
