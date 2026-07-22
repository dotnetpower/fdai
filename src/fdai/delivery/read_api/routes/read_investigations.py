"""Authenticated direct, streamed, and detached read investigations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from fdai.core.background_task import (
    BackgroundTaskBudget,
    BackgroundTaskConflictError,
    BackgroundTaskOrigin,
    BackgroundTaskQuotaExceededError,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.core.read_investigation import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    InvestigationExecutionPolicy,
    PlanLatencyEstimate,
    ReadInvestigationBudget,
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
    ReadInvestigationRunUsage,
    ReadInvestigationService,
    estimate_plan_latency,
    latency_profile,
    plan_read_investigation,
    read_investigation_request_digest,
    read_tool_spec,
)
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadLatencyProfileStore,
    ResourceSelector,
)

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY: Final = 16_000
_SSE_HEARTBEAT_INTERVAL_SECONDS: Final = 15.0
_DIRECT_REPLAY_HEADER: Final = "X-FDAI-Read-Investigation-Replay"
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunLedgerConfig:
    lease_seconds: int = 30
    lease_max_window_seconds: int = 300
    lease_budget_margin_seconds: int = 5
    renew_interval_seconds: float = 10.0
    retention_seconds: int = 3_600
    retry_after_seconds: int = 3
    reconcile_limit: int = 25
    purge_limit: int = 25

    def __post_init__(self) -> None:
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("run ledger lease_seconds MUST be in [1, 300]")
        if not 1 <= self.lease_max_window_seconds <= 3_600:
            raise ValueError("run ledger lease_max_window_seconds MUST be in [1, 3600]")
        if self.lease_max_window_seconds < self.lease_seconds:
            raise ValueError("run ledger lease_max_window_seconds MUST be >= lease_seconds")
        if not 0 <= self.lease_budget_margin_seconds <= 300:
            raise ValueError("run ledger lease_budget_margin_seconds MUST be in [0, 300]")
        if not 0.1 <= self.renew_interval_seconds <= 120:
            raise ValueError("run ledger renew_interval_seconds MUST be in [0.1, 120]")
        if self.renew_interval_seconds * 2 >= self.lease_seconds:
            raise ValueError("run ledger renew_interval_seconds MUST be < half of lease_seconds")
        if not 60 <= self.retention_seconds <= 604_800:
            raise ValueError("run ledger retention_seconds MUST be in [60, 604800]")
        if not 1 <= self.retry_after_seconds <= 60:
            raise ValueError("run ledger retry_after_seconds MUST be in [1, 60]")
        if not 1 <= self.reconcile_limit <= 10_000:
            raise ValueError("run ledger reconcile_limit MUST be in [1, 10000]")
        if not 1 <= self.purge_limit <= 10_000:
            raise ValueError("run ledger purge_limit MUST be in [1, 10000]")


@dataclass(frozen=True, slots=True)
class ReadInvestigationRoutesConfig:
    service: ReadInvestigationService
    run_store: ReadInvestigationRunStore
    latency_store: ReadLatencyProfileStore
    background: BackgroundTaskRoutesConfig
    scope_ref: str
    execution_policy: InvestigationExecutionPolicy = InvestigationExecutionPolicy()
    run_ledger: ReadInvestigationRunLedgerConfig = ReadInvestigationRunLedgerConfig()
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if not self.scope_ref.strip() or len(self.scope_ref) > 256:
            raise ValueError("read investigation scope_ref MUST be bounded")


class _ReadInvestigationExecutionConfig(Protocol):
    @property
    def service(self) -> ReadInvestigationService: ...

    @property
    def run_store(self) -> ReadInvestigationRunStore: ...

    @property
    def run_ledger(self) -> ReadInvestigationRunLedgerConfig: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...

    @property
    def monotonic(self) -> Callable[[], float]: ...


@dataclass(frozen=True, slots=True)
class ReadInvestigationExecutorConfig:
    service: ReadInvestigationService
    run_store: ReadInvestigationRunStore
    run_ledger: ReadInvestigationRunLedgerConfig = ReadInvestigationRunLedgerConfig()
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    monotonic: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True)
class ReadInvestigationDirectExecution:
    result: ReadInvestigationResult
    replayed: bool


class ReadInvestigationRunRejectedError(RuntimeError):
    def __init__(self, detail: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


class IdempotentReadInvestigationExecutor:
    """Execute direct investigations through the durable owner-scoped run ledger."""

    def __init__(self, config: _ReadInvestigationExecutionConfig) -> None:
        self._config = config

    @property
    def transport(self) -> str:
        return self._config.service.transport

    async def execute(
        self,
        plan: ReadInvestigationPlan,
        *,
        owner_principal_id: str,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> ReadInvestigationDirectExecution:
        return await _execute_direct_idempotent(
            self._config,
            plan,
            owner_principal_id=owner_principal_id,
            progress_observer=progress_observer,
        )


def make_read_investigation_routes(
    *,
    config: ReadInvestigationRoutesConfig,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def start(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.START_READ_INVESTIGATION):
            raise HTTPException(
                status_code=403,
                detail="start-read-investigation capability is required",
            )
        body = await _body(request)
        try:
            investigation = _request(body, principal=principal, scope_ref=config.scope_ref)
            plan = plan_read_investigation(investigation)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        profiles = {}
        for step in plan.steps:
            spec = read_tool_spec(step.tool_id)
            samples = await config.latency_store.recent(
                tool_id=step.tool_id,
                transport=config.service.transport,
                operation_class=spec.operation_class,
                limit=200,
            )
            profiles[step.tool_id] = latency_profile(samples)
        estimate = estimate_plan_latency(
            plan,
            profiles,
            minimum_samples=config.execution_policy.minimum_profile_samples,
        )
        mode = config.execution_policy.select(plan, estimate)
        if mode is ReadInvestigationExecutionMode.DETACHED:
            return await _detach(
                config,
                investigation,
                body,
                principal=principal,
                estimate=estimate,
            )
        if mode is ReadInvestigationExecutionMode.DIRECT:
            try:
                execution = await IdempotentReadInvestigationExecutor(config).execute(
                    plan,
                    owner_principal_id=principal.oid,
                )
            except ReadInvestigationRunRejectedError as exc:
                headers = (
                    {"Retry-After": str(exc.retry_after_seconds)}
                    if exc.retry_after_seconds is not None
                    else None
                )
                raise HTTPException(status_code=409, detail=exc.detail, headers=headers) from exc
            return JSONResponse(
                {
                    "mode": mode.value,
                    "estimate": _estimate(estimate),
                    "result": _result(execution.result),
                },
                headers={_DIRECT_REPLAY_HEADER: "1"} if execution.replayed else None,
            )
        now = config.clock()
        await _preflight_run_ledger(config, now=now)
        lease_seconds = _effective_lease_seconds(config, request=investigation)
        lease_ceiling_at = _lease_ceiling_at(config, request=investigation, now=now)
        lease_token = _lease_token(investigation, now=now)
        try:
            claimed, created = await config.run_store.claim(
                owner_principal_id=principal.oid,
                request=investigation,
                mode=_run_mode(mode),
                lease_owner="read-api",
                lease_token=lease_token,
                now=now,
                lease_seconds=lease_seconds,
                retention_seconds=config.run_ledger.retention_seconds,
            )
        except ReadInvestigationRunConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="idempotency key conflicts with another request payload",
            ) from exc

        if (
            not created
            and claimed.state
            in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}
            and claimed.attempt_count < MAX_READ_INVESTIGATION_ATTEMPTS
        ):
            try:
                claimed = await config.run_store.reclaim(
                    owner_principal_id=principal.oid,
                    idempotency_key=investigation.idempotency_key,
                    request_digest=claimed.request_digest,
                    mode=_run_mode(mode),
                    expected_revision=claimed.revision,
                    lease_owner="read-api",
                    lease_token=lease_token,
                    now=now,
                    lease_seconds=lease_seconds,
                    retention_seconds=config.run_ledger.retention_seconds,
                )
                created = True
            except (LookupError, ReadInvestigationRunConflictError) as exc:
                latest = await config.run_store.get(
                    owner_principal_id=principal.oid,
                    idempotency_key=investigation.idempotency_key,
                )
                if latest is None:
                    raise HTTPException(
                        status_code=409,
                        detail="read investigation run could not be reclaimed",
                    ) from exc
                claimed = latest

        if not created:
            return _existing_claimed_response(
                claimed=claimed,
                mode=mode,
                estimate=estimate,
                now=now,
                retry_after_seconds=config.run_ledger.retry_after_seconds,
            )

        if mode is ReadInvestigationExecutionMode.STREAMED:
            return _stream_claimed(
                config=config,
                plan=plan,
                estimate=estimate,
                claimed=claimed,
                lease_token=lease_token,
                lease_seconds=lease_seconds,
                lease_ceiling_at=lease_ceiling_at,
            )

        raise RuntimeError("streamed investigation did not return a streaming response")

    return (Route("/read-investigations", start, methods=["POST"]),)


async def _execute_direct_idempotent(
    config: _ReadInvestigationExecutionConfig,
    plan: ReadInvestigationPlan,
    *,
    owner_principal_id: str,
    progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
) -> ReadInvestigationDirectExecution:
    request = plan.request
    if request.requester_ref != owner_principal_id:
        raise ReadInvestigationRunRejectedError(
            "read investigation requester does not match the authenticated principal"
        )
    now = config.clock()
    await _preflight_run_ledger(config, now=now)
    lease_seconds = _effective_lease_seconds(config, request=request)
    lease_ceiling_at = _lease_ceiling_at(config, request=request, now=now)
    lease_token = _lease_token(request, now=now)
    try:
        claimed, created = await config.run_store.claim(
            owner_principal_id=owner_principal_id,
            request=request,
            mode=ReadInvestigationRunMode.DIRECT,
            lease_owner="read-api",
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
                lease_owner="read-api",
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

    result = await _execute_claimed(
        config=config,
        plan=plan,
        claimed=claimed,
        lease_token=lease_token,
        lease_seconds=lease_seconds,
        lease_ceiling_at=lease_ceiling_at,
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


async def _detach(
    config: ReadInvestigationRoutesConfig,
    request: ReadInvestigationRequest,
    body: dict[str, Any],
    *,
    principal: Principal,
    estimate: PlanLatencyEstimate,
) -> Response:
    prompt = _canonical_prompt(request)
    context_digest = hashlib.sha256(
        f"{principal.oid}:{read_investigation_request_digest(request)}".encode()
    ).hexdigest()
    try:
        attempt, created = await config.background.service.create(
            owner_principal_id=principal.oid,
            origin=BackgroundTaskOrigin(
                conversation_id=request.conversation_ref,
                channel_kind=_string(body, "channel_kind"),
                channel_id=_string(body, "channel_id"),
                thread_id=_optional_string(body, "thread_id"),
                message_id=_string(body, "message_id"),
            ),
            prompt=prompt,
            context_digest=f"sha256:{context_digest}",
            correlation_id=request.correlation_ref,
            idempotency_key=request.idempotency_key,
            budget=BackgroundTaskBudget(
                max_wall_seconds=request.budget.max_wall_seconds,
                max_cost_microusd=request.budget.max_cost_microusd,
                max_tool_calls=request.budget.max_tool_calls,
            ),
            retention_days=_integer(body, "retention_days", default=30),
        )
    except BackgroundTaskQuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except BackgroundTaskConflictError as exc:
        replay = await _detached_replay_attempt(
            config=config,
            principal_id=principal.oid,
            request=request,
            body=body,
            prompt=prompt,
            context_digest=f"sha256:{context_digest}",
        )
        if replay is None:
            raise HTTPException(
                status_code=409,
                detail="idempotency key conflicts with another detached request payload",
            ) from exc
        attempt = replay
        created = False
    if created:
        config.background.coordinator.wake()
    return JSONResponse(
        {
            "mode": ReadInvestigationExecutionMode.DETACHED.value,
            "estimate": _estimate(estimate),
            "task_id": attempt.task.task_id,
            "status": attempt.status.value,
        },
        status_code=202 if created else 200,
    )


def _stream_claimed(
    *,
    config: ReadInvestigationRoutesConfig,
    plan: ReadInvestigationPlan,
    claimed: ReadInvestigationRunRecord,
    lease_token: str,
    lease_seconds: int,
    lease_ceiling_at: datetime,
    estimate: PlanLatencyEstimate,
) -> Response:
    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)

        async def observe(kind: ReadInvestigationProgressKind) -> None:
            await queue.put(kind.value)

        execution = asyncio.create_task(
            _execute_claimed(
                config=config,
                plan=plan,
                claimed=claimed,
                lease_token=lease_token,
                lease_seconds=lease_seconds,
                lease_ceiling_at=lease_ceiling_at,
                progress_observer=observe,
                failure_state=ReadInvestigationRunState.FAILED,
                cancellation_state=ReadInvestigationRunState.EXPIRED,
            )
        )
        try:
            while not execution.done() or not queue.empty():
                try:
                    kind = await asyncio.wait_for(
                        queue.get(),
                        timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS,
                    )
                except TimeoutError:
                    if not execution.done():
                        yield ": heartbeat\n\n"
                    continue
                yield f"event: progress\ndata: {json.dumps({'kind': kind})}\n\n"
            result = await execution
            payload = {
                "mode": ReadInvestigationExecutionMode.STREAMED.value,
                "estimate": _estimate(estimate),
                "result": _result(result),
            }
            yield f"event: terminal\ndata: {json.dumps(payload)}\n\n"
        finally:
            if not execution.done():
                execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)

    return StreamingResponse(events(), media_type="text/event-stream")


async def _detached_replay_attempt(
    *,
    config: ReadInvestigationRoutesConfig,
    principal_id: str,
    request: ReadInvestigationRequest,
    body: dict[str, Any],
    prompt: str,
    context_digest: str,
) -> Any | None:
    attempts = await config.background.store.list(owner=principal_id, limit=100)
    for attempt in attempts:
        task = attempt.task
        if task.idempotency_key != request.idempotency_key:
            continue
        if task.owner_principal_id != principal_id:
            continue
        if task.prompt != prompt or task.context_digest != context_digest:
            return None
        if task.origin.conversation_id != request.conversation_ref:
            return None
        if task.origin.channel_kind != _string(body, "channel_kind"):
            return None
        if task.origin.channel_id != _string(body, "channel_id"):
            return None
        if task.origin.thread_id != _optional_string(body, "thread_id"):
            return None
        if task.origin.message_id != _string(body, "message_id"):
            return None
        if task.correlation_id != request.correlation_ref:
            return None
        return attempt
    return None


async def _execute_claimed(
    *,
    config: _ReadInvestigationExecutionConfig,
    plan: ReadInvestigationPlan,
    claimed: ReadInvestigationRunRecord,
    lease_token: str,
    lease_seconds: int,
    lease_ceiling_at: datetime,
    failure_state: ReadInvestigationRunState,
    cancellation_state: ReadInvestigationRunState,
    progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
) -> ReadInvestigationResult:
    started = config.monotonic()
    current = await config.run_store.start(
        owner_principal_id=claimed.owner_principal_id,
        idempotency_key=claimed.idempotency_key,
        expected_revision=claimed.revision,
        lease_token=lease_token,
        now=config.clock(),
    )
    execution = asyncio.create_task(
        config.service.execute(plan, progress_observer=progress_observer)
    )
    try:
        while True:
            done, _pending = await asyncio.wait(
                (execution,),
                timeout=config.run_ledger.renew_interval_seconds,
            )
            if done:
                result = execution.result()
                break
            current = await config.run_store.renew(
                owner_principal_id=current.owner_principal_id,
                idempotency_key=current.idempotency_key,
                expected_revision=current.revision,
                lease_token=lease_token,
                now=config.clock(),
                lease_seconds=lease_seconds,
                lease_ceiling_at=lease_ceiling_at,
            )
    except asyncio.CancelledError:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        await _fail_claimed(
            config=config,
            run=current,
            lease_token=lease_token,
            reason="client_stream_disconnected",
            state=cancellation_state,
            duration_ms=_duration_ms(config.monotonic() - started),
        )
        raise
    except Exception:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        await _fail_claimed(
            config=config,
            run=current,
            lease_token=lease_token,
            reason="service_execution_failed",
            state=failure_state,
            duration_ms=_duration_ms(config.monotonic() - started),
        )
        raise
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)

    usage = _run_usage(
        request=current.request,
        result=result,
        execution_duration_ms=_duration_ms(config.monotonic() - started),
    )
    try:
        completed = await config.run_store.complete(
            owner_principal_id=current.owner_principal_id,
            idempotency_key=current.idempotency_key,
            expected_revision=current.revision,
            lease_token=lease_token,
            result=result,
            usage=usage,
            now=config.clock(),
        )
    except (LookupError, ReadInvestigationRunConflictError):
        _LOG.warning(
            "read_investigation_completion_conflict_after_success",
            extra={
                "owner_principal_id": current.owner_principal_id,
                "idempotency_key": current.idempotency_key,
            },
        )
        return result
    if completed.result is None:
        _LOG.warning(
            "read_investigation_completion_missing_replay_result",
            extra={
                "owner_principal_id": completed.owner_principal_id,
                "idempotency_key": completed.idempotency_key,
            },
        )
        return result
    return completed.result


async def _fail_claimed(
    *,
    config: _ReadInvestigationExecutionConfig,
    run: ReadInvestigationRunRecord,
    lease_token: str,
    reason: str,
    state: ReadInvestigationRunState,
    duration_ms: int,
) -> None:
    try:
        await config.run_store.fail(
            owner_principal_id=run.owner_principal_id,
            idempotency_key=run.idempotency_key,
            expected_revision=run.revision,
            lease_token=lease_token,
            failure_reason=reason,
            usage=ReadInvestigationRunUsage(
                tool_calls=0,
                execution_duration_ms=duration_ms,
                reserved_cost_microusd=run.request.budget.max_cost_microusd,
            ),
            now=config.clock(),
            state=state,
        )
    except (LookupError, ReadInvestigationRunConflictError):
        _LOG.warning(
            "read_investigation_terminal_conflict",
            extra={
                "owner_principal_id": run.owner_principal_id,
                "idempotency_key": run.idempotency_key,
                "failure_reason": reason,
            },
        )
        # Best-effort terminal transition for cancellation/failure cleanup.
        return


def _existing_claimed_response(
    *,
    claimed: ReadInvestigationRunRecord,
    mode: ReadInvestigationExecutionMode,
    estimate: PlanLatencyEstimate,
    now: datetime,
    retry_after_seconds: int,
) -> Response:
    if claimed.state in {ReadInvestigationRunState.CLAIMED, ReadInvestigationRunState.RUNNING}:
        retry_after = retry_after_seconds
        if claimed.lease is not None:
            remaining = max(1, math.ceil((claimed.lease.expires_at - now).total_seconds()))
            retry_after = min(retry_after_seconds, remaining)
        raise HTTPException(
            status_code=409,
            detail="read investigation with this idempotency key is already in progress",
            headers={"Retry-After": str(retry_after)},
        )

    if claimed.state is ReadInvestigationRunState.COMPLETED and claimed.result is not None:
        if mode is ReadInvestigationExecutionMode.STREAMED:
            return _stream_existing_terminal(result=claimed.result, estimate=estimate)
        return JSONResponse(
            {
                "mode": ReadInvestigationExecutionMode.DIRECT.value,
                "estimate": _estimate(estimate),
                "result": _result(claimed.result),
            },
            headers={_DIRECT_REPLAY_HEADER: "1"},
        )

    if claimed.state in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}:
        if claimed.attempt_count >= MAX_READ_INVESTIGATION_ATTEMPTS:
            retention_remaining = max(
                1,
                math.ceil((claimed.retention_until - now).total_seconds()),
            )
            retry_after = min(retry_after_seconds, retention_remaining)
            raise HTTPException(
                status_code=409,
                detail="read investigation retry attempts are exhausted for this idempotency key",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=409,
            detail="read investigation idempotency key is terminal and pending reclaim",
            headers={"Retry-After": str(retry_after_seconds)},
        )

    raise HTTPException(
        status_code=409,
        detail="read investigation idempotency key is terminal and not replayable",
    )


def _stream_existing_terminal(
    *,
    result: ReadInvestigationResult,
    estimate: PlanLatencyEstimate,
) -> Response:
    async def events() -> AsyncIterator[str]:
        payload = {
            "mode": ReadInvestigationExecutionMode.STREAMED.value,
            "estimate": _estimate(estimate),
            "result": _result(result),
        }
        yield f"event: terminal\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


async def _preflight_run_ledger(
    config: _ReadInvestigationExecutionConfig,
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


def _run_mode(mode: ReadInvestigationExecutionMode) -> ReadInvestigationRunMode:
    return {
        ReadInvestigationExecutionMode.DIRECT: ReadInvestigationRunMode.DIRECT,
        ReadInvestigationExecutionMode.STREAMED: ReadInvestigationRunMode.STREAMED,
    }[mode]


def _lease_token(request: ReadInvestigationRequest, *, now: datetime) -> str:
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


def _duration_ms(seconds: float) -> int:
    return max(0, int(round(seconds * 1_000)))


def _run_usage(
    *,
    request: ReadInvestigationRequest,
    result: ReadInvestigationResult,
    execution_duration_ms: int,
) -> ReadInvestigationRunUsage:
    costs = tuple(receipt.cost_microusd for receipt in result.receipts)
    measured_cost = (
        sum(cost for cost in costs if cost is not None)
        if costs and all(cost is not None for cost in costs)
        else None
    )
    return ReadInvestigationRunUsage(
        tool_calls=len(result.receipts),
        execution_duration_ms=execution_duration_ms,
        reserved_cost_microusd=request.budget.max_cost_microusd,
        measured_cost_microusd=measured_cost,
    )


def _effective_lease_window_seconds(
    config: _ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
) -> int:
    budget_window = request.budget.max_wall_seconds + config.run_ledger.lease_budget_margin_seconds
    return max(1, min(config.run_ledger.lease_max_window_seconds, budget_window))


def _effective_lease_seconds(
    config: _ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
) -> int:
    return min(
        config.run_ledger.lease_seconds, _effective_lease_window_seconds(config, request=request)
    )


def _lease_ceiling_at(
    config: _ReadInvestigationExecutionConfig,
    *,
    request: ReadInvestigationRequest,
    now: datetime,
) -> datetime:
    return now + timedelta(seconds=_effective_lease_window_seconds(config, request=request))


def _request(
    body: dict[str, Any],
    *,
    principal: Principal,
    scope_ref: str,
) -> ReadInvestigationRequest:
    try:
        intent = ReadInvestigationIntent(_string(body, "intent"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="intent is unsupported") from exc
    budget = body.get("budget") or {}
    if not isinstance(budget, dict):
        raise HTTPException(status_code=400, detail="budget MUST be an object")
    explicit_deep = body.get("explicit_deep", False)
    if not isinstance(explicit_deep, bool):
        raise HTTPException(status_code=400, detail="explicit_deep MUST be boolean")
    return ReadInvestigationRequest(
        requester_ref=principal.oid,
        conversation_ref=_string(body, "conversation_id"),
        correlation_ref=_string(body, "correlation_id"),
        intent=intent,
        selector=ResourceSelector(
            name=_string(body, "resource_name", maximum=128),
            scope_ref=scope_ref,
            resource_type=_optional_string(body, "resource_type"),
            resource_group=_optional_string(body, "resource_group"),
        ),
        lookback_seconds=_integer(body, "lookback_seconds", default=3_600),
        requested_evidence=(),
        budget=ReadInvestigationBudget(
            max_wall_seconds=_mapping_int(budget, "max_wall_seconds", 60),
            max_cost_microusd=_mapping_int(budget, "max_cost_microusd", 100_000),
            max_tool_calls=_mapping_int(budget, "max_tool_calls", 5),
            max_results=_mapping_int(budget, "max_results", 32),
            max_output_bytes=_mapping_int(budget, "max_output_bytes", 256_000),
        ),
        idempotency_key=_string(body, "idempotency_key"),
        created_at=datetime.now(UTC),
        explicit_deep=explicit_deep,
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="request body exceeds cap")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def _canonical_prompt(request: ReadInvestigationRequest) -> str:
    phrase = {
        ReadInvestigationIntent.RESOURCE_STATE: "Check the current state of",
        ReadInvestigationIntent.CHANGE_ATTRIBUTION: "Who changed or stopped",
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY: "Show the change history of",
        ReadInvestigationIntent.PLATFORM_HEALTH: "Check the platform health of",
        ReadInvestigationIntent.GUEST_SHUTDOWN: "Find guest OS shutdown events for",
    }[request.intent]
    suffix = " with deep analysis" if request.explicit_deep else ""
    return f"{phrase} {request.selector.name}{suffix}."


def _result(result: ReadInvestigationResult) -> dict[str, object]:
    return {
        "outcome": result.outcome.value,
        "resolution": {
            "status": result.resolution.status.value,
            "resource": (
                {
                    "resource_ref": result.resolution.resource.resource_ref,
                    "name": result.resolution.resource.name,
                    "resource_type": result.resolution.resource.resource_type,
                    "resource_group": result.resolution.resource.resource_group,
                }
                if result.resolution.resource is not None
                else None
            ),
            "candidates": [
                {
                    "resource_ref": item.resource_ref,
                    "name": item.name,
                    "resource_type": item.resource_type,
                    "resource_group": item.resource_group,
                }
                for item in result.resolution.candidates
            ],
        },
        "evidence": [
            {
                "status": item.status.value,
                "authority": item.authority,
                "resource_ref": item.resource_ref,
                "observed_at": item.observed_at.isoformat(),
                "freshness": item.freshness.value,
                "truncated": item.truncated,
                "records": len(item.records),
                "evidence_refs": list(item.evidence_refs),
            }
            for item in result.evidence
        ],
        "evidence_refs": list(result.evidence_refs),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def _estimate(value: PlanLatencyEstimate) -> dict[str, object]:
    return {
        "lower_ms": value.lower_ms,
        "upper_ms": value.upper_ms,
        "measured": value.measured,
        "sample_count": value.sample_count,
    }


def _string(body: dict[str, Any], key: str, *, maximum: int = 256) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _integer(body: dict[str, Any], key: str, *, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def _mapping_int(body: dict[str, Any], key: str, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"budget.{key} MUST be an integer")
    return value


__all__ = [
    "ReadInvestigationRoutesConfig",
    "ReadInvestigationRunLedgerConfig",
    "make_read_investigation_routes",
]
