"""Guarded direct-API effect application owned by the isolated Executor."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fdai_service_contracts.executor import (
    Action,
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiExecutor,
    DirectApiNetworkDeniedError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPolicyDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    IdempotencyStore,
    Mode,
    ResourceLock,
)

from fdai_executor_service.effect_safety import (
    action_fingerprint,
    blast_radius_refusal,
    build_direct_api_request,
    dedupe_key,
    idempotency_lock_key,
    missing_safety_invariant,
    resource_lock_key,
    target_binding_refusal,
)
from fdai_executor_service.ports import ExecutorStateStore

_LOGGER = logging.getLogger("fdai.isolated_executor.effect")


class DirectApiEffectOutcome(StrEnum):
    """Terminal outcomes produced by the isolated effect boundary."""

    DISPATCHED = "dispatched"
    ALREADY_APPLIED = "already_applied"
    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    ABSTAINED_PRECONDITION = "abstained_precondition"
    STOPPED = "stopped"
    FAILED = "failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    NETWORK_DENIED = "network_denied"
    REJECTED_MODE = "rejected_mode"
    REJECTED_INVARIANT = "rejected_invariant"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DirectApiEffectResult:
    """Audited result of one service-owned direct-API dispatch."""

    action_id: str
    outcome: DirectApiEffectOutcome
    mode: Mode = Mode.SHADOW
    receipt_ref: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DirectApiEffectConfig:
    """Hard ceilings enforced before the provider sees an effect request."""

    max_affected_resources: int = 10
    max_rate_per_minute: int = 30
    max_dedupe_entries: int = 10_000


_MUTATION_OUTCOMES = frozenset(
    {DirectApiEffectOutcome.DISPATCHED, DirectApiEffectOutcome.ALREADY_APPLIED}
)


@runtime_checkable
class DirectApiOperationStatusReader(Protocol):
    """Read durable provider operation status without dispatching a new effect."""

    async def operation_status(
        self,
        request: DirectApiRequest,
    ) -> DirectApiReceipt | None: ...


class ServiceDirectApiEffectExecutor:
    """Apply direct-API effects behind all executor-owned safety guards."""

    def __init__(
        self,
        *,
        executor: DirectApiExecutor,
        audit_store: ExecutorStateStore,
        resource_lock: ResourceLock,
        idempotency: IdempotencyStore | None,
        allow_enforce: bool,
        config: DirectApiEffectConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._executor = executor
        self._audit_store = audit_store
        self._resource_lock = resource_lock
        self._idempotency = idempotency
        self._allow_enforce = allow_enforce
        self._config = config or DirectApiEffectConfig()
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._dedupe: dict[str, DirectApiEffectResult] = {}

    async def execute(
        self,
        *,
        action: Action,
        deadline_at: datetime | None = None,
    ) -> DirectApiEffectResult:
        """Validate, lock, audit, dispatch, and durably deduplicate one effect."""

        if action.mode is not Mode.SHADOW and not self._allow_enforce:
            return await self._finish(
                action,
                DirectApiEffectOutcome.REJECTED_MODE,
                "enforce mode is unavailable before authority cutover",
            )
        invariant_reason = missing_safety_invariant(action)
        if invariant_reason is not None:
            return await self._finish(
                action,
                DirectApiEffectOutcome.REJECTED_INVARIANT,
                invariant_reason,
            )
        target_reason = target_binding_refusal(action)
        if target_reason is not None:
            return await self._finish(
                action,
                DirectApiEffectOutcome.REJECTED_INVARIANT,
                target_reason,
            )

        cache_key = dedupe_key(action)
        cached = self._dedupe.get(cache_key)
        if cached is not None:
            return await self._deduplicated_or_conflict(action, cached)

        async with AsyncExitStack() as locks:
            await locks.enter_async_context(
                self._resource_lock.acquire(idempotency_lock_key(action.idempotency_key))
            )
            cached = self._dedupe.get(cache_key)
            if cached is not None:
                return await self._deduplicated_or_conflict(action, cached)
            await locks.enter_async_context(
                self._resource_lock.acquire(resource_lock_key(action.target_resource_ref))
            )
            expired_reason: str | None = None
            if deadline_at is not None:
                now = self._clock()
                if now.tzinfo is None or deadline_at.tzinfo is None:
                    return await self._finish(
                        action,
                        DirectApiEffectOutcome.REJECTED_INVARIANT,
                        "effect deadline and executor clock MUST be timezone-aware",
                    )
                if now > deadline_at:
                    expired_reason = "command deadline expired while waiting for effect locks"

            if self._idempotency is not None:
                stored = await self._idempotency.seen(action.idempotency_key)
                if stored is not None:
                    stored_result = _result_from_payload(stored)
                    if not (action.mode is Mode.ENFORCE and stored_result.mode is Mode.SHADOW):
                        resolved = await self._deduplicated_or_conflict(action, stored_result)
                        if resolved is stored_result:
                            self._remember(cache_key, stored_result)
                        return resolved

            if expired_reason is not None:
                recovered = await self._recover_provider_status_locked(action)
                if recovered is not None:
                    return recovered
                return await self._finish(
                    action,
                    DirectApiEffectOutcome.EXPIRED,
                    expired_reason,
                )

            blast_reason = blast_radius_refusal(action, self._config)
            if blast_reason is not None:
                return await self._finish(
                    action,
                    DirectApiEffectOutcome.ABSTAINED_BLAST_RADIUS,
                    blast_reason,
                )
            if action.mode is Mode.ENFORCE:
                await self._write_audit_intent(action)
            try:
                receipt = await self._executor.execute(build_direct_api_request(action))
            except DirectApiError as exc:
                return await self._finish_provider_error(action, exc)
            except Exception:  # noqa: BLE001 - provider boundary
                _LOGGER.error(
                    "isolated_executor_provider_uncontrolled_error",
                    extra={"failure_kind": "uncontrolled_provider_error"},
                )
                return await self._finish(
                    action,
                    DirectApiEffectOutcome.FAILED,
                    "provider failed with an uncontrolled error",
                    rollback_succeeded=False,
                )
            return await self._finish_from_receipt(action, receipt)

    async def recover(self, *, action: Action) -> DirectApiEffectResult | None:
        """Recover a prior effect from local or provider status without re-effecting."""

        if action.mode is not Mode.ENFORCE or not self._allow_enforce:
            return None
        if missing_safety_invariant(action) is not None:
            return None
        target_reason = target_binding_refusal(action)
        if target_reason is not None:
            return await self._finish(
                action,
                DirectApiEffectOutcome.REJECTED_INVARIANT,
                target_reason,
            )

        cache_key = dedupe_key(action)
        cached = self._dedupe.get(cache_key)
        if cached is not None:
            return await self._deduplicated_or_conflict(action, cached)

        async with AsyncExitStack() as locks:
            await locks.enter_async_context(
                self._resource_lock.acquire(idempotency_lock_key(action.idempotency_key))
            )
            cached = self._dedupe.get(cache_key)
            if cached is not None:
                return await self._deduplicated_or_conflict(action, cached)
            await locks.enter_async_context(
                self._resource_lock.acquire(resource_lock_key(action.target_resource_ref))
            )

            if self._idempotency is not None:
                stored = await self._idempotency.seen(action.idempotency_key)
                if stored is not None:
                    stored_result = _result_from_payload(stored)
                    resolved = await self._deduplicated_or_conflict(action, stored_result)
                    if resolved is stored_result:
                        self._remember(cache_key, stored_result)
                    return resolved

            return await self._recover_provider_status_locked(action)

    async def _recover_provider_status_locked(
        self,
        action: Action,
    ) -> DirectApiEffectResult | None:
        if action.mode is not Mode.ENFORCE or not isinstance(
            self._executor, DirectApiOperationStatusReader
        ):
            return None
        try:
            receipt = await self._executor.operation_status(build_direct_api_request(action))
        except DirectApiError as exc:
            return await self._finish_provider_error(action, exc)
        except Exception:  # noqa: BLE001 - provider status boundary
            _LOGGER.error(
                "isolated_executor_provider_status_uncontrolled_error",
                extra={"failure_kind": "uncontrolled_provider_status_error"},
            )
            return await self._finish(
                action,
                DirectApiEffectOutcome.FAILED,
                "provider status failed with an uncontrolled error",
                rollback_succeeded=False,
            )
        if receipt is None:
            return None
        return await self._finish_from_receipt(action, receipt)

    async def _finish_provider_error(
        self,
        action: Action,
        error: DirectApiError,
    ) -> DirectApiEffectResult:
        outcome, failure_kind, reason, rollback_succeeded = _classified_provider_error(error)
        _LOGGER.warning(
            "isolated_executor_provider_classified_error",
            extra={"failure_kind": failure_kind},
        )
        return await self._finish(
            action,
            outcome,
            reason,
            rollback_succeeded=rollback_succeeded,
        )

    async def _deduplicated_or_conflict(
        self,
        action: Action,
        cached: DirectApiEffectResult,
    ) -> DirectApiEffectResult:
        if cached.audit_context.get("idempotency_fingerprint") == action_fingerprint(action):
            return cached
        return await self._finish(
            action,
            DirectApiEffectOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
            "idempotency key is already bound to a different action payload",
            remember=False,
        )

    async def _finish_from_receipt(
        self,
        action: Action,
        receipt: DirectApiReceipt,
    ) -> DirectApiEffectResult:
        outcomes = {
            DirectApiOutcome.SUCCEEDED: DirectApiEffectOutcome.DISPATCHED,
            DirectApiOutcome.ALREADY_APPLIED: DirectApiEffectOutcome.ALREADY_APPLIED,
            DirectApiOutcome.PRECONDITION_FAILED: (DirectApiEffectOutcome.ABSTAINED_PRECONDITION),
            DirectApiOutcome.STOPPED: DirectApiEffectOutcome.STOPPED,
            DirectApiOutcome.FAILED: DirectApiEffectOutcome.FAILED,
        }
        return await self._finish(
            action,
            outcomes[receipt.outcome],
            receipt.detail,
            receipt_ref=receipt.receipt_ref,
            rollback_succeeded=receipt.rollback_succeeded,
        )

    async def _finish(
        self,
        action: Action,
        outcome: DirectApiEffectOutcome,
        reason: str | None,
        *,
        receipt_ref: str | None = None,
        rollback_succeeded: bool | None = None,
        remember: bool = True,
    ) -> DirectApiEffectResult:
        result = DirectApiEffectResult(
            action_id=str(action.action_id),
            outcome=outcome,
            mode=action.mode,
            receipt_ref=receipt_ref,
            rollback_succeeded=rollback_succeeded,
            reason=reason,
            audit_context={
                "resource_ref": action.target_resource_ref,
                "action_type": action.action_type,
                "executor_identity_ref": action.executor_identity_ref,
                "operation": action.operation.value,
                "blast_radius_scope": action.blast_radius.scope.value,
                "idempotency_fingerprint": action_fingerprint(action),
            },
        )
        await self._write_terminal_audit(action, result)
        if remember:
            self._remember(dedupe_key(action), result)
        if (
            remember
            and action.mode is Mode.ENFORCE
            and self._idempotency is not None
            and outcome in _MUTATION_OUTCOMES
        ):
            await self._idempotency.record(action.idempotency_key, _result_payload(result))
        return result

    def _remember(self, key: str, result: DirectApiEffectResult) -> None:
        cap = max(1, self._config.max_dedupe_entries)
        if key in self._dedupe:
            del self._dedupe[key]
        elif len(self._dedupe) >= cap:
            self._dedupe.pop(next(iter(self._dedupe)))
        self._dedupe[key] = result

    async def _write_audit_intent(self, action: Action) -> None:
        await self._audit_store.append_audit_entry(_audit_entry(action, phase="intent"))

    async def _write_terminal_audit(
        self,
        action: Action,
        result: DirectApiEffectResult,
    ) -> None:
        await self._audit_store.append_audit_entry(
            _audit_entry(action, phase="terminal", result=result)
        )


def _audit_entry(
    action: Action,
    *,
    phase: str,
    result: DirectApiEffectResult | None = None,
) -> Mapping[str, Any]:
    outcome = "intent_persisted" if result is None else result.outcome.value
    return {
        "event_id": str(action.event_id),
        "action_id": str(action.action_id),
        "idempotency_key": action.idempotency_key,
        "actor": "fdai_executor_service.effect_executor",
        "action_kind": action.action_type if result is None else f"executor.direct_api.{outcome}",
        "audit_phase": phase,
        "mode": action.mode.value,
        "execution_path": "direct_api",
        "citing_rule_ids": list(action.citing_rules),
        "outcome": outcome,
        "receipt_ref": None if result is None else result.receipt_ref,
        "rollback_succeeded": None if result is None else result.rollback_succeeded,
        "reason": None if result is None else result.reason,
        "resource_ref": action.target_resource_ref,
        "operation": action.operation.value,
        "rollback_kind": action.rollback_ref.kind.value,
        "rollback_reference": action.rollback_ref.reference,
        "stop_condition": action.stop_condition,
        "stop_conditions": [item.model_dump(mode="json") for item in action.stop_conditions],
        "blast_radius": action.blast_radius.model_dump(mode="json"),
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


def _result_payload(result: DirectApiEffectResult) -> Mapping[str, Any]:
    return {
        "action_id": result.action_id,
        "outcome": result.outcome.value,
        "mode": result.mode.value,
        "receipt_ref": result.receipt_ref,
        "rollback_succeeded": result.rollback_succeeded,
        "reason": result.reason,
        "audit_context": dict(result.audit_context),
    }


def _result_from_payload(payload: Mapping[str, Any]) -> DirectApiEffectResult:
    context = payload.get("audit_context")
    return DirectApiEffectResult(
        action_id=str(payload["action_id"]),
        outcome=DirectApiEffectOutcome(str(payload["outcome"])),
        mode=Mode(str(payload.get("mode", Mode.SHADOW.value))),
        receipt_ref=None if payload.get("receipt_ref") is None else str(payload["receipt_ref"]),
        rollback_succeeded=(
            payload.get("rollback_succeeded")
            if isinstance(payload.get("rollback_succeeded"), bool)
            else None
        ),
        reason=None if payload.get("reason") is None else str(payload["reason"]),
        audit_context=dict(context) if isinstance(context, Mapping) else {},
    )


def _classified_provider_error(
    error: DirectApiError,
) -> tuple[DirectApiEffectOutcome, str, str, bool | None]:
    if isinstance(error, DirectApiPromotionError):
        return (
            DirectApiEffectOutcome.REJECTED_MODE,
            "promotion_rejected",
            "provider rejected effect promotion",
            None,
        )
    if isinstance(error, DirectApiPreconditionError):
        return (
            DirectApiEffectOutcome.ABSTAINED_PRECONDITION,
            "precondition_failed",
            "provider precondition was not satisfied",
            None,
        )
    if isinstance(error, DirectApiAuthenticationError):
        return (
            DirectApiEffectOutcome.AUTHENTICATION_FAILED,
            "authentication_failed",
            "provider authentication failed",
            None,
        )
    if isinstance(error, DirectApiPermissionDeniedError):
        return (
            DirectApiEffectOutcome.PERMISSION_DENIED,
            "permission_denied",
            "provider permission was denied",
            None,
        )
    if isinstance(error, DirectApiPolicyDeniedError):
        return (
            DirectApiEffectOutcome.POLICY_DENIED,
            "policy_denied",
            "provider policy denied the effect",
            None,
        )
    if isinstance(error, DirectApiNetworkDeniedError):
        return (
            DirectApiEffectOutcome.NETWORK_DENIED,
            "network_denied",
            "provider network policy denied the effect",
            None,
        )
    return (
        DirectApiEffectOutcome.FAILED,
        "classified_adapter_error",
        "provider failed with a classified adapter error",
        False,
    )


__all__ = [
    "DirectApiEffectConfig",
    "DirectApiEffectOutcome",
    "DirectApiEffectResult",
    "ServiceDirectApiEffectExecutor",
]
