"""Bind original approved acceptance Actions to Thor's existing isolated safeguard transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fdai.core.executor.direct_api import DirectApiExecutionOutcome
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import Action, Mode

from fdai_aks_commerce.acceptance_action import AcceptanceGuardedExecutor
from fdai_aks_commerce.acceptance_material import AcceptanceDispatchMaterial


class AcceptanceIsolatedDispatch:
    """Dispatch retained material only; neither construct an Action nor grant current authority.

    The Forseti-owned material reader and current authorization checker are mandatory. The
    latter rechecks the exact independent human approval, promotion, risk and kill state.
    The existing transport retains dry-run, rollback, target lock, idempotency and audit.
    Broker acceptance remains verification-pending; ambiguous outcomes are never retried here.
    """

    def __init__(
        self,
        *,
        guard: AcceptanceGuardedExecutor,
        read_material: Callable[[str], Awaitable[AcceptanceDispatchMaterial | None]],
        check_authority: Callable[[Action, dict[str, Any]], Awaitable[None]],
        client: SafeguardBoundEventBusDirectApiExecutionClient,
        clock: Callable[[], datetime] | None = None,
        record_command: Callable[[Action, str], Awaitable[None]] | None = None,
    ) -> None:
        self._guard = guard
        self._read_material = read_material
        self._check_authority = check_authority
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._record_command = record_command

    async def __call__(self, context: dict[str, Any]) -> bool:
        """Use the original Action and repeat all current source checks at publication time."""
        evidence_guard = self._guard.bind(context)
        run = context["run"]
        bound_run_json = json.dumps(run.to_dict(), sort_keys=True, allow_nan=False)
        action_id = run.action_id
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("acceptance dispatch requires the original prepared Action id")
        async with asyncio.timeout(5):
            original = await self._read_material(action_id)
        if original is None:
            raise ValueError("acceptance original Action is unavailable")
        original_json = original.action_json
        action = Action.model_validate_json(original_json)

        async def current() -> None:
            async with asyncio.timeout(5):
                await evidence_guard()
                retained = await self._read_material(action_id)
                expires_at = run.approval_expires_at
                if (
                    retained is None
                    or retained != original
                    or action.model_dump_json() != original_json
                    or str(action.action_id) != run.action_id
                    or action.action_type != "ops.scale-out"
                    or action.action_type != run.action_type
                    or action.target_resource_ref != run.resource_id
                    or action.params != run.params
                    or original.action_run_idempotency_key != run.idempotency_key
                    or original.correlation_id != run.correlation_id
                    or action.rollback_ref.kind.value != run.rollback_contract
                    or action.mode is not Mode.ENFORCE
                    or run.shadow_mode
                    or run.verdict != "hil"
                    or run.resolved_autonomy_ceiling.value not in {"enforce_hil", "enforce_auto"}
                    or run.state.value != "executing"
                    or not run.execution_audit_receipt
                    or expires_at is None
                    or expires_at.tzinfo is None
                    or not self._clock() < expires_at
                ):
                    raise ValueError("acceptance original Action or current approval changed")
                await self._check_authority(Action.model_validate_json(original_json), context)
                if (
                    context["run"] is not run
                    or json.dumps(run.to_dict(), sort_keys=True, allow_nan=False) != bound_run_json
                    or not self._clock() < expires_at
                ):
                    raise ValueError("acceptance approval changed or expired during admission")

        await current()
        try:
            result = await self._client.execute(action=action, source_guard=current)
            command_id = result.audit_context.get("command_id")
            if self._record_command is not None and isinstance(command_id, str):
                await self._record_command(action, command_id)
        except Exception as exc:
            raise TimeoutError(
                "acceptance transport result requires independent reconciliation"
            ) from exc
        if (
            result.action_id != action_id
            or result.mode is not Mode.ENFORCE
            or result.outcome is DirectApiExecutionOutcome.EXECUTION_UNKNOWN
            or result.audit_context.get("continuity_quarantined") is True
        ):
            raise TimeoutError("acceptance dispatch outcome requires independent reconciliation")
        if result.outcome is DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE:
            if (
                result.audit_context.get("dispatch_status") != "pending"
                or not result.audit_context.get("command_id")
                or not result.safeguard_bundle_digest
            ):
                raise TimeoutError("acceptance dispatch receipt is incomplete")
            return True
        if result.audit_context.get("effect_possible") is True:
            raise TimeoutError("acceptance dispatch may have been accepted")
        return False
