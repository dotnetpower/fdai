"""Exact Executor-role readback of Core material and current HIL/promotion/preparation sources."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from fdai_service_contracts.executor_models import executor_action_payload_digest
from fdai_service_contracts.human_access_execution import (
    HumanAccessCurrentEvidence,
    HumanAccessExecutionMaterial,
    HumanAccessPreparation,
    canonical_human_access_json,
    human_access_record_digest,
)
from fdai_service_contracts.human_access_recovery import require_inverse_fence
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class PostgresHumanAccessSource:
    """Only exact material-bound reads; no case/HIL writes or unbounded private queries."""

    dsn: str
    role_groups: Mapping[str, str]

    async def material_for(
        self, *, action_id: UUID, action_digest: str
    ) -> HumanAccessExecutionMaterial | None:
        """Read and independently verify the exact original Action hash under the Executor role."""
        payload = await self._read(action_id, action_digest)
        if payload is None:
            return None
        return _material(payload, action_id=action_id, action_digest=action_digest)

    async def current(self, material: HumanAccessExecutionMaterial) -> HumanAccessCurrentEvidence:
        """Join current original records instead of trusting a positive snapshot alone."""
        action = material.action()
        payload = await self._read(action.action_id, material.action_digest)
        if (
            payload is None
            or _material(payload, action_id=action.action_id, action_digest=material.action_digest)
            != material
        ):
            raise ValueError("human access current material source changed")
        kill_switch = payload.get("kill_switch")
        if kill_switch is not None and (
            not isinstance(kill_switch, dict) or kill_switch.get("engaged") is not False
        ):
            raise ValueError("human access current emergency halt is engaged or unavailable")
        source_count = payload.get("source_count")
        if type(source_count) is not int or not 0 <= source_count <= 1000:
            raise ValueError("human access current assignment demand exceeds its bounded source")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise ValueError("human access current source observation is unavailable")
        evidence = HumanAccessCurrentEvidence.model_validate(current.get("evidence"))
        if human_access_record_digest(dict(self.role_groups)) != material.role_groups_digest:
            raise ValueError(
                "isolated human access role-group binding differs from the reviewed map"
            )
        case = payload.get("case")
        if not isinstance(case, dict):
            raise ValueError("human access current case is unavailable")
        preparation_field = (
            "iam_recovery_preparation" if material.inverse is not None else "iam_preparation"
        )
        preparation = HumanAccessPreparation.model_validate(case.get(preparation_field))
        if (
            preparation.material_digest != material.digest
            or preparation.source_case_digest != material.case_record_digest
            or preparation.reference != evidence.preparation_ref
            or preparation.prepared_revision != case.get("revision")
            or evidence.current_case_revision != case.get("revision")
            or evidence.current_case_state != case.get("state")
        ):
            raise ValueError("human access current preparation was changed or invalidated")
        original_case = dict(case)
        original_case.pop(preparation_field, None)
        original_case.update(
            revision=preparation.source_revision,
            state=(
                "degraded"
                if material.inverse is not None
                else "approved"
                if action.action_type == "ops.revoke-human-access"
                else "ownership_merged"
            ),
        )
        if human_access_record_digest(original_case) != material.case_record_digest:
            raise ValueError(
                "human access preparation changed fields outside the exact source transition"
            )
        intent = case.get("intent")
        if (
            not isinstance(intent, dict)
            or intent.get("requested_role") != material.requested_role
            or intent.get("requester_ref") != material.requester_ref
            or intent.get("subject") != {"provider": "entra", "subject_id": material.subject_id}
        ):
            raise ValueError("human access current case intent changed")
        if material.inverse is not None:
            _require_inverse_sources(payload, material)
        elif action.action_type == "ops.revoke-human-access":
            _require_current_replacements(payload, material=material, intent=intent)
        promotion = payload.get("promotion")
        if (
            not isinstance(promotion, dict)
            or promotion.get("mode") != "enforce"
            or promotion.get("action_type") != action.action_type
            or human_access_record_digest(promotion) != material.promotion_record_digest
        ):
            raise ValueError("human access current promotion was changed or revoked")
        parks, decisions = payload.get("parks"), payload.get("decisions")
        if not isinstance(parks, dict) or not isinstance(decisions, dict):
            raise ValueError("human access original human decision sources are unavailable")
        for observed in evidence.approvals:
            park, decision = parks.get(observed.approval_id), decisions.get(observed.approval_id)
            if not isinstance(park, dict) or not isinstance(decision, dict):
                raise ValueError("human access original human decision is missing")
            metadata, context = park.get("metadata"), park.get("approval_context")
            if (
                not isinstance(metadata, dict)
                or metadata.get("decision_route") != "human_access"
                or metadata.get("material_digest") != material.digest
                or metadata.get("required_role") != "Owner"
                or metadata.get("target_subject_ref") != material.subject_id
                or park.get("submitter_oid") != material.requester_ref
                or canonical_human_access_json(park.get("action")) != material.action_json
                or not isinstance(context, dict)
                or context.get("expires_at") != material.expires_at.isoformat()
            ):
                raise ValueError("human access original HIL context changed")
            original = {
                key: decision.get(key)
                for key in (
                    "approval_id",
                    "idempotency_key",
                    "decision",
                    "approver_oid",
                    "decided_at",
                    "receipt_ref",
                )
            }
            if (
                human_access_record_digest(original) != observed.source_record_digest
                or decision.get("decision") != observed.decision
                or decision.get("approver_oid") != observed.approver_ref
            ):
                raise ValueError("human access original HIL decision changed")
        at = payload.get("database_now")
        if not isinstance(at, str):
            raise ValueError("human access source database clock is unavailable")
        reason = evidence.refusal(material, now=datetime.fromisoformat(at))
        if reason is not None:
            raise ValueError(reason)
        return evidence

    async def _read(self, action_id: UUID, action_digest: str) -> dict[str, object] | None:
        async with asyncio.timeout(5):
            async with await psycopg.AsyncConnection.connect(
                self.dsn, row_factory=dict_row, connect_timeout=3
            ) as connection:
                await connection.execute("SET TRANSACTION READ ONLY")
                await connection.execute("SET LOCAL statement_timeout = '3000ms'")
                role = await (await connection.execute("SELECT current_user AS role")).fetchone()
                if role is None or role["role"] != "fdai_executor":
                    raise PermissionError(
                        "human access source read requires the exact Executor role"
                    )
                row = await (
                    await connection.execute(
                        "SELECT fdai_executor_human_access_source(%s, %s) AS source",
                        (str(action_id), action_digest),
                    )
                ).fetchone()
                if row is None or row["source"] is None:
                    return None
                if not isinstance(row["source"], dict):
                    raise ValueError("human access source function returned malformed evidence")
                return row["source"]


def _material(
    payload: Mapping[str, object], *, action_id: UUID, action_digest: str
) -> HumanAccessExecutionMaterial:
    material = HumanAccessExecutionMaterial.model_validate(payload.get("material"))
    action = material.action()
    if (
        action.action_id != action_id
        or executor_action_payload_digest(action.model_dump(mode="json")) != action_digest
    ):
        raise ValueError("human access material does not match the original isolated command")
    return material


def _require_inverse_sources(
    payload: Mapping[str, object], material: HumanAccessExecutionMaterial
) -> None:
    """Require exact Executor-owned originals and the shared generation, never a flag."""
    inverse = material.inverse
    if inverse is None:
        raise ValueError("human access inverse binding is missing")
    original = HumanAccessExecutionMaterial.model_validate(payload.get("inverse_original"))
    intent, result, fence, demand = (
        payload.get(name)
        for name in ("inverse_intent", "inverse_result", "target_fence", "recovery_demand")
    )
    if (
        original.inverse is not None
        or original.digest != inverse.original_material_digest
        or original.action_digest != inverse.original_action_digest
        or original.subject_id != material.subject_id
        or original.group_id != material.group_id
        or not isinstance(intent, dict)
        or not isinstance(result, dict)
        or not isinstance(fence, dict)
        or not isinstance(demand, dict)
    ):
        raise ValueError("human access inverse original evidence changed")
    inverse.require_owned(intent, result)
    require_inverse_fence(inverse, fence, inverse_key=material.action().idempotency_key)
    if human_access_record_digest(demand) != inverse.demand_digest:
        raise ValueError("human access inverse current membership demand changed")
    if not inverse.original_before_membership:
        for value in demand.values():
            if not isinstance(value, dict) or not isinstance(value.get("intent"), dict):
                raise ValueError("human access inverse demand is malformed")
            item = value["intent"]
            if (
                item.get("subject") == {"provider": "entra", "subject_id": material.subject_id}
                and item.get("requested_role") == material.requested_role
                and "revocation" not in item
                and value.get("state") in {"active", "iam_applying", "degraded"}
            ):
                raise ValueError(
                    "human access inverse membership is required by another assignment"
                )


def _require_current_replacements(
    payload: Mapping[str, object],
    *,
    material: HumanAccessExecutionMaterial,
    intent: Mapping[str, object],
) -> None:
    """Recheck original hold and exact live replacement/demand sources at every provider fence."""
    revocation, related = intent.get("revocation"), payload.get("related_cases")
    if (
        not isinstance(revocation, dict)
        or not isinstance(related, dict)
        or payload.get("other_demand") is not False
    ):
        raise ValueError("human access current removal sources are incomplete or still demanded")
    original = related.get("human_assignment:case:" + str(revocation.get("case_id")))
    if (
        not isinstance(original, dict)
        or original.get("revocation_case_id") != material.action().params["case_id"]
        or original.get("state") != "degraded"
        or type(original.get("revision")) is not int
        or original["revision"] != revocation.get("revision", 0) + 1
    ):
        raise ValueError("human access original assignment is not the exact retained removal hold")
    replacements = material.action().params["replacement_revisions"]
    if replacements != revocation.get("replacement_revisions"):
        raise ValueError("human access replacement intent changed")
    slots: dict[tuple[str, str], dict[str, set[str]]] = {}
    for case_id, revision in replacements.items():
        replacement = related.get("human_assignment:case:" + case_id)
        if (
            not isinstance(replacement, dict)
            or replacement.get("revision") != revision
            or replacement.get("state") != "active"
        ):
            raise ValueError("human access replacement is no longer its exact active revision")
        other_intent, receipts = replacement.get("intent"), replacement.get("effect_receipts")
        if (
            not isinstance(other_intent, dict)
            or "revocation" in other_intent
            or replacement.get("revocation_case_id") is not None
            or not isinstance(receipts, list)
            or len(receipts) != 2
            or {r.get("kind") for r in receipts if isinstance(r, dict)} != {"iam", "ownership"}
        ):
            raise ValueError("human access replacement effects are incomplete")
        for receipt in receipts:
            if (
                not isinstance(receipt, dict)
                or any(
                    not isinstance(receipt.get(field), str) or not receipt[field]
                    for field in ("receipt_ref", "digest", "received_at")
                )
                or re.fullmatch(r"[a-f0-9]{64}", receipt["digest"]) is None
            ):
                raise ValueError("human access replacement effect evidence is malformed")
            recorded_at = datetime.fromisoformat(receipt["received_at"])
            if recorded_at.utcoffset() is None:
                raise ValueError("human access replacement effect time is unavailable")
        person, bindings = other_intent.get("subject"), other_intent.get("duty_bindings")
        if (
            not isinstance(person, dict)
            or person.get("provider") != "entra"
            or not isinstance(person.get("subject_id"), str)
            or person["subject_id"].casefold() == material.subject_id
            or not isinstance(bindings, list)
        ):
            raise ValueError("human access replacement subject is not independently observed")
        for binding in bindings:
            if not isinstance(binding, dict) or not isinstance(binding.get("scope_ref"), str):
                raise ValueError("human access replacement duty binding is malformed")
            pair = (str(binding.get("agent_name")), binding["scope_ref"].casefold())
            slots.setdefault(pair, {}).setdefault(str(binding.get("duty")), set()).add(
                person["subject_id"].casefold()
            )
    original_intent = original.get("intent")
    if not isinstance(original_intent, dict) or not isinstance(
        original_intent.get("duty_bindings"), list
    ):
        raise ValueError("human access original duty coverage is unavailable")
    for binding in original_intent["duty_bindings"]:
        current = slots.get((binding["agent_name"], binding["scope_ref"].casefold()), {})
        primary = current.get("primary", set())
        fallback = current.get("backup", set()) | current.get("escalation", set())
        if len(primary) != 1 or not fallback - primary:
            raise ValueError("human access current replacement coverage is incomplete")


__all__ = ["PostgresHumanAccessSource"]
