"""Direct durable execution orchestration for read investigations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.read_investigation import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    ReadInvestigationExecutionMode,
    ReadInvestigationPlan,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunStore,
    ReadInvestigationService,
)


class ReadInvestigationRunLedgerSettings(Protocol):
    @property
    def lease_seconds(self) -> int: ...

    @property
    def lease_max_window_seconds(self) -> int: ...

    @property
    def lease_budget_margin_seconds(self) -> int: ...

    @property
    def renew_interval_seconds(self) -> float: ...

    @property
    def retention_seconds(self) -> int: ...

    @property
    def retry_after_seconds(self) -> int: ...

    @property
    def reconcile_limit(self) -> int: ...

    @property
    def purge_limit(self) -> int: ...


class ReadInvestigationExecutionConfig(Protocol):
    @property
    def service(self) -> ReadInvestigationService: ...

    @property
    def run_store(self) -> ReadInvestigationRunStore: ...

    @property
    def run_ledger(self) -> ReadInvestigationRunLedgerSettings: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...

    @property
    def monotonic(self) -> Callable[[], float]: ...


class ExecuteClaimed(Protocol):
    def __call__(
        self,
        *,
        config: ReadInvestigationExecutionConfig,
        plan: ReadInvestigationPlan,
        claimed: ReadInvestigationRunRecord,
        lease_token: str,
        lease_seconds: int,
        lease_ceiling_at: datetime,
        failure_state: ReadInvestigationRunState,
        cancellation_state: ReadInvestigationRunState,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> Awaitable[ReadInvestigationResult]: ...


@dataclass(frozen=True, slots=True)
class ReadInvestigationDirectExecution:
    result: ReadInvestigationResult
    replayed: bool


class ReadInvestigationRunRejectedError(RuntimeError):
    def __init__(self, detail: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


async def execute_direct_idempotent(
    config: ReadInvestigationExecutionConfig,
    plan: ReadInvestigationPlan,
    *,
    owner_principal_id: str,
    execute_claimed: ExecuteClaimed,
    progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
) -> ReadInvestigationDirectExecution:
    request = plan.request
    if request.requester_ref != owner_principal_id:
        raise ReadInvestigationRunRejectedError(
            "read investigation requester does not match the authenticated principal"
        )
    now = config.clock()
    await preflight_run_ledger(config, now=now)
    lease_seconds = effective_lease_seconds(config, request=request)
    lease_ceiling = lease_ceiling_at(config, request=request, now=now)
    lease_token = make_lease_token(request, now=now)
    try:
        claimed, created = await config.run_store.claim(
            owner_principal_id=owner_principal_id,
            request=request,
            mode=ReadInvestigationRunMode.DIRECT,
            lease_owner="operator-api",
            lease_token=lease_token,
            now=now,
            lease_seconds=lease_seconds,
            retention_seconds=config.run_ledger.retention_seconds,
        )
    except ReadInvestigationRunConflictError as exc:
        raise ReadInvestigationRunRejectedError(
            "idempotency key conflicts with another request payload"
        ) from exc

    if (
        not created
        and claimed.state in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}
        and claimed.attempt_count < MAX_READ_INVESTIGATION_ATTEMPTS
    ):
        try:
            claimed = await config.run_store.reclaim(
                owner_principal_id=owner_principal_id,
                idempotency_key=request.idempotency_key,
                request_digest=claimed.request_digest,
                mode=ReadInvestigationRunMode.DIRECT,
                expected_revision=claimed.revision,
                lease_owner="operator-api",
                lease_token=lease_token,
                now=now,
                lease_seconds=lease_seconds,
                retention_seconds=config.run_ledger.retention_seconds,
            )
            created = True
        except (LookupError, ReadInvestigationRunConflictError) as exc:
            latest = await config.run_store.get(
                owner_principal_id=owner_principal_id,
                idempotency_key=request.idempotency_key,
            )
            if latest is None:
                raise ReadInvestigationRunRejectedError(
                    "read investigation run could not be reclaimed"
                ) from exc
            claimed = latest

    if not created:
        if claimed.state is ReadInvestigationRunState.COMPLETED and claimed.result is not None:
            return ReadInvestigationDirectExecution(result=claimed.result, replayed=True)
        _reject_existing_direct(
            claimed,
            now=now,
            retry_after_seconds=config.run_ledger.retry_after_seconds,
        )

    result = await execute_claimed(
        config=config,
        plan=plan,
        claimed=claimed,
        lease_token=lease_token,
        lease_seconds=lease_seconds,
        lease_ceiling_at=lease_ceiling,
        failure_state=ReadInvestigationRunState.FAILED,
        cancellation_state=ReadInvestigationRunState.EXPIRED,
        progress_observer=progress_observer,
    )
    return ReadInvestigationDirectExecution(result=result, replayed=False)


def _reject_existing_direct(
    claimed: ReadInvestigationRunRecord,
    *,
    now: datetime,
    retry_after_seconds: int,
) -> None:
    if claimed.state in {ReadInvestigationRunState.CLAIMED, ReadInvestigationRunState.RUNNING}:
        retry_after = retry_after_seconds
        if claimed.lease is not None:
            remaining = max(1, math.ceil((claimed.lease.expires_at - now).total_seconds()))
            retry_after = min(retry_after_seconds, remaining)
        raise ReadInvestigationRunRejectedError(
            "read investigation with this idempotency key is already in progress",
            retry_after_seconds=retry_after,
        )
    if claimed.state in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}:
        if claimed.attempt_count >= MAX_READ_INVESTIGATION_ATTEMPTS:
            retention_remaining = max(
                1,
                math.ceil((claimed.retention_until - now).total_seconds()),
            )
            raise ReadInvestigationRunRejectedError(
                "read investigation retry attempts are exhausted for this idempotency key",
                retry_after_seconds=min(retry_after_seconds, retention_remaining),
            )
        raise ReadInvestigationRunRejectedError(
            "read investigation idempotency key is terminal and pending reclaim",
            retry_after_seconds=retry_after_seconds,
        )
    raise ReadInvestigationRunRejectedError(
        "read investigation idempotency key is terminal and not replayable"
    )


async def preflight_run_ledger(
    config: ReadInvestigationExecutionConfig,
    *,
    now: datetime,
) -> None:
    try:
        await config.run_store.reconcile_expired(
            now=now,
            limit=config.run_ledger.reconcile_limit,
        )
        await config.run_store.purge_retained(
            now=now,
            limit=config.run_ledger.purge_limit,
        )
    except Exception:
        # Opportunistic cleanup MUST NOT block read investigations.
        return


def run_mode(mode: ReadInvestigationExecutionMode) -> ReadInvestigationRunMode:
    return {
        ReadInvestigationExecutionMode.DIRECT: ReadInvestigationRunMode.DIRECT,
        ReadInvestigationExecutionMode.STREAMED: ReadInvestigationRunMode.STREAMED,
    }[mode]


def make_lease_token(request: ReadInvestigationRequest, *, now: datetime) -> str:
    material = json.dumps(
        {
            "idempotency_key": request.idempotency_key,
            "correlation_ref": request.correlation_ref,
            "created_at": now.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:64]


def _effective_lease_window_seconds(
    config: ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
) -> int:
    budget_window = request.budget.max_wall_seconds + config.run_ledger.lease_budget_margin_seconds
    return max(1, min(config.run_ledger.lease_max_window_seconds, budget_window))


def effective_lease_seconds(
    config: ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
) -> int:
    return min(
        config.run_ledger.lease_seconds,
        _effective_lease_window_seconds(config, request=request),
    )


def lease_ceiling_at(
    config: ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
    now: datetime,
) -> datetime:
    return now + timedelta(seconds=_effective_lease_window_seconds(config, request=request))
