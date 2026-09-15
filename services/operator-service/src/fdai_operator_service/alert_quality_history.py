"""Read bounded accepted requests and their exact authenticated terminal, without Core access."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, Self

from fdai_service_contracts.alert_noise import Ref
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.alert_noise_projection import AlertProposalDetail
from fdai_service_contracts.alert_noise_wire import SignedAlertResult, verify_alert_record
from pydantic import Field, StrictBool, model_validator

from fdai_operator_service.alert_quality_command import (
    ALERT_REQUEST_KEY,
    alert_request_ref,
    command_from_record,
)
from fdai_operator_service.alert_quality_records import (
    AlertQualityUnavailableError,
    _canonical,
    _contains_identity,
    alert_quality_binding_digest,
)


class AlertQualityRequest(AlertContractBase):
    """Original request and result facts only; missing closure remains explicitly unconfirmed."""

    request_ref: Ref
    request_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")]
    operation: Literal["alert_noise.assess", "alert_noise.propose"]
    accepted_at: AlertTime
    expires_at: AlertTime
    status: Literal["pending", "unconfirmed", "assessment_ready", "proposal_ready", "held"]
    reason: Ref | None = None
    result_recorded_at: AlertTime | None = None
    plan: AlertChangePlan | None = None
    detail: AlertProposalDetail | None = None
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if not 0 < (self.expires_at - self.accepted_at).total_seconds() <= 300:
            raise ValueError("alert request history deadline is invalid")
        terminal = self.status not in {"pending", "unconfirmed"}
        if terminal != (self.result_recorded_at is not None):
            raise ValueError("alert request history requires exact terminal chronology")
        if self.result_recorded_at is not None and self.result_recorded_at < self.accepted_at:
            raise ValueError("alert request history terminal precedes acceptance")
        if (self.status == "proposal_ready") != (self.plan is not None):
            raise ValueError("alert request history plan requires its proposal result")
        if self.detail is not None:
            if self.plan is None:
                raise ValueError("alert request history detail requires its plan")
            self.detail.require_plan(self.plan)
        return self


class AlertQualityRequestHistory(AlertContractBase):
    """One scoped bounded page; a truncated page is not proof of complete request history."""

    source: Literal["alert-noise-requests"] = "alert-noise-requests"
    scope_ref: Ref
    read_at: AlertTime
    requests: Annotated[tuple[AlertQualityRequest, ...], Field(max_length=25)]
    truncated: StrictBool
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def exact_page(self) -> Self:
        if len({row.request_ref for row in self.requests}) != len(self.requests) or any(
            row.accepted_at > self.read_at
            or (row.result_recorded_at is not None and row.result_recorded_at > self.read_at)
            for row in self.requests
        ):
            raise ValueError("alert request history contains duplicate or future records")
        return self


class AlertQualityRequestSource(Protocol):
    """Read only the authenticated principal and scope, optionally one original client key."""

    async def read(
        self, *, principal_id: str, scope_ref: str, request_key: str | None = None
    ) -> AlertQualityRequestHistory: ...


class AlertQualityRequestStore(Protocol):
    """Exact Operator-owned storage reads; no Core tables or caller-supplied SQL."""

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...

    async def recent_alert_quality_requests(
        self, *, principal_id: str, scope_ref: str, limit: int
    ) -> tuple[Mapping[str, Any], ...]: ...


class StateKvAlertQualityRequestSource:
    """Verify original acceptance and signed result on every read, including after restart."""

    def __init__(
        self,
        store: AlertQualityRequestStore,
        *,
        transport_key: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(transport_key) < 32:
            raise ValueError("alert request history requires the authenticated transport key")
        self._store, self._key, self._clock = store, transport_key, clock

    async def read(
        self, *, principal_id: str, scope_ref: str, request_key: str | None = None
    ) -> AlertQualityRequestHistory:
        """No writes, implicit resend or inferred no-effect on expiry or broker acceptance."""
        alert_quality_binding_digest(principal_id, scope_ref)
        records: tuple[Mapping[str, Any], ...]
        if request_key is not None:
            request_ref = alert_request_ref(principal_id, request_key)
            key = "operator-proposal:operations:" + hashlib.sha256(request_ref.encode()).hexdigest()
            record = await self._store.read_state(key)
            records = () if record is None else (record,)
        else:
            records = await self._store.recent_alert_quality_requests(
                principal_id=principal_id, scope_ref=scope_ref, limit=26
            )
        if len(records) > 26:
            raise AlertQualityUnavailableError("alert request history exceeds its bound")
        requests = tuple(
            [
                await self._entry(row, principal_id=principal_id, scope_ref=scope_ref)
                for row in records[:25]
            ]
        )
        if request_key is not None and any(row.request_key != request_key for row in requests):
            raise AlertQualityUnavailableError("alert request history selected key does not match")
        result = AlertQualityRequestHistory(
            scope_ref=scope_ref,
            read_at=self._clock(),
            requests=requests,
            truncated=len(records) > 25,
        )
        public = result.model_dump(mode="json")
        _canonical(public)
        if _contains_identity(public, principal_id):
            raise AlertQualityUnavailableError("alert request history disclosure is invalid")
        return result

    async def _entry(
        self, record: Mapping[str, Any], *, principal_id: str, scope_ref: str
    ) -> AlertQualityRequest:
        _canonical(dict(record))
        command = command_from_record(record)
        if record.get("principal_id") != principal_id or command.scope_ref != scope_ref:
            raise AlertQualityUnavailableError("alert request history binding is invalid")
        request_key = record["payload"]["payload"].get("request_idempotency_key")
        if (
            not isinstance(request_key, str)
            or ALERT_REQUEST_KEY.fullmatch(request_key) is None
            or command.request_ref != alert_request_ref(principal_id, request_key)
        ):
            raise AlertQualityUnavailableError("alert request history key is invalid")
        raw = await self._store.read_state("operator-alert-quality-result:" + command.request_ref)
        result = None
        if raw is not None:
            _canonical(dict(raw))
            signed = SignedAlertResult.model_validate(raw)
            verify_alert_record(signed.result, signed.signature, self._key)
            if signed.result.command != command:
                raise AlertQualityUnavailableError("alert request history terminal is mismatched")
            result = signed.result
        now = self._clock()
        if command.requested_at > now or (result is not None and result.recorded_at > now):
            raise AlertQualityUnavailableError("alert request history is future recorded")
        return AlertQualityRequest.model_validate(
            {
                "request_ref": command.request_ref,
                "request_key": request_key,
                "operation": command.operation,
                "accepted_at": command.requested_at,
                "expires_at": command.expires_at,
                "status": result.status
                if result is not None
                else (
                    "unconfirmed"
                    if now >= command.expires_at or record.get("dispatch_status") == "rejected"
                    else "pending"
                ),
                "reason": result.reason if result is not None else None,
                "result_recorded_at": result.recorded_at if result is not None else None,
                "plan": result.plan if result is not None else None,
                "detail": result.detail if result is not None else None,
            }
        )
