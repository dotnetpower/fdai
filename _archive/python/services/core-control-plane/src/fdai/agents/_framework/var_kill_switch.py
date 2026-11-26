"""Var-owned verification and application of global kill-switch requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.kill_switch import KillSwitchRequestEvent
from pydantic import ValidationError

from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.core.rbac.kill_switch_command import KillSwitchCommandService, KillSwitchState

_ALLOWED_ROLES = frozenset({"Owner", "BreakGlass"})


class KillSwitchRequestRejectedError(ValueError):
    """A kill-switch request failed schema or authority verification."""


@dataclass(frozen=True, slots=True)
class VarKillSwitchRequestHandler:
    """Verify one Operator command and apply the fail-safe state transition."""

    service: KillSwitchCommandService
    receipt_gate: OperatorRequestReceiptGate
    operator_producer_service_identity: str
    clock: Callable[[], datetime]

    async def handle(self, payload: Mapping[str, Any]) -> KillSwitchState | None:
        try:
            request = KillSwitchRequestEvent.model_validate(dict(payload))
        except ValidationError as exc:
            raise KillSwitchRequestRejectedError("malformed_schema") from exc
        receipt = request.operator_request_receipt
        if receipt is None:
            raise KillSwitchRequestRejectedError("operator_request_receipt_missing")
        if receipt.schema_version != "1.2.0":
            raise KillSwitchRequestRejectedError("operator_request_receipt_version")
        if receipt.producer_service_identity != self.operator_producer_service_identity:
            raise KillSwitchRequestRejectedError("operator_request_receipt_producer")
        if request.correlation_id != f"kill-switch:{request.request_id}":
            raise KillSwitchRequestRejectedError("request_correlation_mismatch")
        if receipt.initiator_principal != request.initiator_principal:
            raise KillSwitchRequestRejectedError("initiator_principal_mismatch")
        if not _ALLOWED_ROLES.intersection(receipt.principal_roles):
            raise KillSwitchRequestRejectedError("operator_role_missing")
        authentication = request.authentication_receipt
        if authentication.principal_kind != "human":
            raise KillSwitchRequestRejectedError("human_principal_required")
        if authentication.subject_id != request.initiator_principal:
            raise KillSwitchRequestRejectedError("authentication_subject_mismatch")
        if authentication.roles != receipt.principal_roles:
            raise KillSwitchRequestRejectedError("authentication_roles_mismatch")
        if not _ALLOWED_ROLES.intersection(authentication.roles):
            raise KillSwitchRequestRejectedError("authentication_role_missing")
        if not authentication.valid_at(request.requested_at):
            raise KillSwitchRequestRejectedError("authentication_receipt_expired")
        authenticated_at = receipt.authenticated_at
        max_auth_age_seconds = receipt.max_auth_age_seconds
        if authenticated_at is None or max_auth_age_seconds is None or max_auth_age_seconds <= 0:
            raise KillSwitchRequestRejectedError("auth_time_missing")
        now_raw = self.clock()
        if now_raw.tzinfo is None or now_raw.utcoffset() is None:
            raise KillSwitchRequestRejectedError("clock_timezone_missing")
        now_utc = now_raw.astimezone(UTC)
        if authenticated_at > now_utc + timedelta(minutes=5):
            raise KillSwitchRequestRejectedError("auth_time_future")
        if now_utc > authenticated_at + timedelta(seconds=max_auth_age_seconds):
            raise KillSwitchRequestRejectedError("auth_time_stale")
        raw = KillSwitchRequestEvent.operator_receipt_event(
            body=request,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            initiator_principal=request.initiator_principal,
            requested_at=request.requested_at,
            authenticated_at=authenticated_at,
            principal_roles=frozenset(receipt.principal_roles),
        )
        raw["operator_request_receipt"] = receipt.model_dump(mode="json")
        try:
            verified = await self.receipt_gate.verify_or_committed(raw)
        except ValueError as exc:
            raise KillSwitchRequestRejectedError("operator_request_receipt_invalid") from exc
        if verified is None:
            return None
        state = await self.service.set_state(
            engaged=request.engaged,
            actor_oid=request.initiator_principal,
            reason=request.reason,
            request_id=request.request_id,
            now=self.clock(),
        )
        try:
            await self.receipt_gate.commit(verified)
        except ValueError as exc:
            if str(exc) != "replayed":
                raise KillSwitchRequestRejectedError("operator_request_receipt_commit") from exc
        return state


class VarKillSwitchMixin:
    """Keep optional kill-switch command wiring outside Var's approval logic."""

    _kill_switch_request_handler: VarKillSwitchRequestHandler | None

    def initialize_kill_switch_handler(self) -> None:
        self._kill_switch_request_handler = None

    def bind_kill_switch_request_handler(
        self,
        handler: VarKillSwitchRequestHandler | None,
    ) -> None:
        self._kill_switch_request_handler = handler

    def kill_switch_configured(self) -> bool:
        return self._kill_switch_request_handler is not None

    async def _kill_switch_message(
        self,
        topic: str,
        payload: Mapping[str, Any],
        record_behavior: Callable[[str], None],
    ) -> bool:
        if topic != "operator.kill-switch.requests":
            return False
        if self._kill_switch_request_handler is None:
            record_behavior("kill_switch:unconfigured")
            return True
        try:
            state = await self._kill_switch_request_handler.handle(payload)
        except KillSwitchRequestRejectedError:
            record_behavior("kill_switch:rejected")
            raise
        record_behavior("kill_switch:duplicate" if state is None else "kill_switch:applied")
        return True


__all__ = [
    "KillSwitchRequestRejectedError",
    "VarKillSwitchMixin",
    "VarKillSwitchRequestHandler",
]
