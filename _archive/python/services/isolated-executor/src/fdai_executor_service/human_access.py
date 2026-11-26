"""Isolated membership dispatch with immutable pre-state, intent and acknowledgement.

The surrounding service owns the shared safeguard bundle and normalized target
lock. This adapter owns one non-retrying Graph attempt, not assignment transitions,
promotion, human review, independent effect observation or automatic rollback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.executor import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
    Mode,
)
from fdai_service_contracts.human_access_execution import (
    HUMAN_ACCESS_ACTIONS,
    HumanAccessExecutionMaterial,
    HumanAccessExecutionSource,
    canonical_human_access_json,
    human_access_record_digest,
    require_human_access_time,
)
from fdai_service_contracts.human_access_recovery import membership_attempt_key

from fdai_executor_service.adapters.entra_membership import EntraMembershipClient
from fdai_executor_service.ports import ExecutorStateStore


@dataclass(frozen=True, slots=True)
class IsolatedHumanAccessExecutor:
    """Invoke once after exact current evidence; retain uncertainty instead of repeating effects."""

    source: HumanAccessExecutionSource
    graph: EntraMembershipClient
    store: ExecutorStateStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Validate current source and one acknowledged write, never claim operational success."""
        if request.action_type_name not in HUMAN_ACCESS_ACTIONS:
            raise DirectApiPreconditionError(
                "isolated human access received an unsupported ActionType"
            )
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                DirectApiOutcome.SUCCEEDED,
                "human-access:shadow",
                detail="shadow human access; no provider request",
            )
        deadline = self._deadline(request)
        start = require_human_access_time(self.clock())
        remaining = (deadline - start).total_seconds()
        if not 0 < remaining <= 120:
            raise DirectApiPreconditionError(
                "human access command deadline is expired or exceeds its bound"
            )
        async with asyncio.timeout(remaining):
            return await self._execute(request, start=start, deadline=deadline)

    async def _execute(
        self, request: DirectApiRequest, *, start: datetime, deadline: datetime
    ) -> DirectApiReceipt:
        material = await self._material(request)
        result = await self._stored_result(request, material)
        if result is not None:
            return result
        key = _attempt_key(request)
        if await self.store.read_state(key + ":intent") is not None:
            raise DirectApiPreconditionError(
                "human access prior dispatch is unobserved; no automatic retry"
            )

        async def guard() -> None:
            now = require_human_access_time(self.clock())
            if now < start or now >= deadline:
                raise DirectApiPreconditionError("human access deadline or clock continuity failed")
            async with asyncio.timeout(5):
                current = await self.source.current(material)
            now = require_human_access_time(self.clock())
            refusal = current.refusal(material, now=now)
            if now < start or now >= deadline or refusal is not None:
                raise DirectApiPreconditionError(
                    refusal or "human access command expired during current-source read"
                )
            if material.inverse is not None:
                original = membership_attempt_key(material.inverse.original_idempotency_key)
                intent = await self.store.read_state(original + ":intent")
                result = await self.store.read_state(original + ":result")
                if intent is None or result is None:
                    raise DirectApiPreconditionError(
                        "human access original mutation evidence is missing"
                    )
                material.inverse.require_owned(intent, result)

        plan = material.membership_plan()
        preflight = await self.graph.inspect(plan, guard=guard)
        await guard()
        if (
            material.inverse is not None
            and preflight.membership is material.inverse.original_before_membership
        ):
            raise DirectApiPreconditionError(
                "human access original membership changed before inverse dispatch"
            )
        identity = {
            "action_digest": material.action_digest,
            "material_digest": material.digest,
            "target_digest": plan.target_digest,
            "idempotency_key": request.idempotency_key,
        }
        intent = {
            **identity,
            "before_membership": preflight.membership,
            "recorded_at": self.clock().isoformat(),
        }
        claimed = await self.store.write_state_with_audit_if_absent(
            key + ":intent", intent, _audit(request, identity, phase="intent")
        )
        if not claimed:
            result = await self._stored_result(request, material)
            if result is not None:
                return result
            raise DirectApiPreconditionError(
                "human access dispatch is already reserved or unobserved"
            )
        already = preflight.membership is plan.desired_membership
        if not already:
            await self.graph.dispatch(plan, preflight, guard=guard)
        # A received204 is dispatch evidence even if later source admission expires.
        # Neither this record nor a provider self-read supplies independent effect proof.
        result_record = {
            **identity,
            "outcome": "already_applied" if already else "succeeded",
            "receipt_ref": "human-access-dispatch:" + human_access_record_digest(identity),
            "owned_mutation": not already,
            "recorded_at": self.clock().isoformat(),
        }
        written = await self.store.write_state_with_audit_if_absent(
            key + ":result", result_record, _audit(request, identity, phase="acknowledged")
        )
        if not written:
            existing = await self.store.read_state(key + ":result")
            if existing != result_record:
                raise DirectApiPreconditionError(
                    "human access acknowledgement persistence conflicted"
                )
        return _receipt(result_record)

    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        """Read only the original durable acknowledgement; never repeat Graph writes on recovery."""
        if request.mode is not Mode.ENFORCE:
            return None
        material = await self._material(request)
        return await self._stored_result(request, material)

    async def _material(self, request: DirectApiRequest) -> HumanAccessExecutionMaterial:
        digest = request.metadata.get("action_payload_digest")
        if not isinstance(digest, str):
            raise DirectApiPreconditionError("human access command lacks original Action digest")
        async with asyncio.timeout(5):
            material = await self.source.material_for(
                action_id=request.action_id, action_digest=digest
            )
        if material is None or material.action_digest != digest:
            raise DirectApiPreconditionError(
                "human access immutable execution material is unavailable"
            )
        action = material.action()
        if (
            str(action.action_id) != str(request.action_id)
            or action.idempotency_key != request.idempotency_key
            or action.action_type != request.action_type_name
            or action.target_resource_ref != request.resource_ref
            or action.mode is not request.mode
            or canonical_human_access_json(action.params)
            != canonical_human_access_json(dict(request.arguments))
            or tuple(action.citing_rules) != request.rule_ids
            or tuple(action.stop_conditions) != request.stop_conditions
            or request.metadata.get("executor_identity_ref") != action.executor_identity_ref
        ):
            raise DirectApiPreconditionError(
                "human access request differs from the reviewed original Action"
            )
        return material

    async def _stored_result(
        self, request: DirectApiRequest, material: HumanAccessExecutionMaterial
    ) -> DirectApiReceipt | None:
        result = await self.store.read_state(_attempt_key(request) + ":result")
        if result is None:
            return None
        identity = {
            "action_digest": material.action_digest,
            "material_digest": material.digest,
            "target_digest": material.membership_plan().target_digest,
            "idempotency_key": request.idempotency_key,
        }
        if (
            any(result.get(key) != value for key, value in identity.items())
            or type(result.get("owned_mutation")) is not bool
        ):
            raise DirectApiPreconditionError(
                "human access idempotency key was rebound to another material"
            )
        return _receipt(result)

    @staticmethod
    def _deadline(request: DirectApiRequest) -> datetime:
        value = request.metadata.get("command_deadline_at")
        if not isinstance(value, str):
            raise DirectApiPreconditionError("human access requires the original command deadline")
        try:
            return require_human_access_time(datetime.fromisoformat(value))
        except ValueError as exc:
            raise DirectApiPreconditionError("human access command deadline is invalid") from exc


def _attempt_key(request: DirectApiRequest) -> str:
    return membership_attempt_key(request.idempotency_key)


def _receipt(result: Mapping[str, Any]) -> DirectApiReceipt:
    if result.get("outcome") not in {"succeeded", "already_applied"} or not isinstance(
        result.get("receipt_ref"), str
    ):
        raise DirectApiPreconditionError("human access acknowledgement is malformed")
    return DirectApiReceipt(
        DirectApiOutcome(result["outcome"]),
        result["receipt_ref"],
        detail="membership dispatch recorded; independent effect observation is pending",
    )


def _audit(
    request: DirectApiRequest, identity: Mapping[str, str], *, phase: str
) -> dict[str, object]:
    return {
        "actor": "fdai_executor_service.effect_executor",
        "owner_agent": "Thor",
        "audit_phase": "intent" if phase == "intent" else "terminal",
        "action_kind": "human_access.dispatch." + phase,
        "action_id": str(request.action_id),
        "idempotency_key": request.idempotency_key,
        "mode": request.mode.value,
        **identity,
    }


__all__ = ["IsolatedHumanAccessExecutor"]
