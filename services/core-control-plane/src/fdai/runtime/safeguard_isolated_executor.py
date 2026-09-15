"""Shared safeguard lifecycle wrapper for the isolated Executor client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    _build_direct_api_request,
    _direct_api_plan_digest,
)
from fdai.core.executor.execution_provenance import SafeguardExecutionVenue
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchBoundaryGuard,
    DispatchNotAttemptedError,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.runtime.isolated_executor_client import (
    EventBusDirectApiExecutionClient,
)
from fdai.shared.contracts.models import (
    Action,
    ExecutionPath,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError
from fdai.shared.providers.executor_receipt_journal import BoundExecutorCommandContext


class _RemoteDirectApiLifecycleDispatchPort:
    """Send one safeguard-bound command while Core retains the target lock."""

    def __init__(
        self,
        *,
        client: EventBusDirectApiExecutionClient,
        action: Action,
        source_revision: str,
        source_guard: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._action = action
        self._source_revision = source_revision
        self._source_guard = source_guard
        self.command: SafeguardBoundExecutorCommand | None = None
        self.error: BaseException | None = None

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        del started_at
        identity = evidence_record.identity
        attempt = identity.reservation_attempt

        async def guarded_publish() -> datetime:
            await pre_invoke_guard()
            if self._source_guard is not None:
                await self._source_guard()
            return await pre_invoke_guard()

        try:
            self.command = await self._client.publish_bound(
                action=self._action,
                safeguard_bundle_digest=evidence_record.bundle.bundle_digest,
                source_revision=self._source_revision,
                attempt=attempt,
                pre_publish_guard=guarded_publish,
                correlation_context=BoundExecutorCommandContext(
                    action_id=identity.action_id,
                    reservation_attempt=identity.reservation_attempt,
                    source_revision=identity.source_revision,
                    execution_path=identity.execution_path,
                    safeguard_bundle_digest=identity.safeguard_bundle_digest,
                    reservation_identity_digest=identity.reservation_identity_digest,
                    evidence_identity_digest=identity.identity_digest,
                    target_digest=identity.target_digest,
                    target_fence_generation=identity.target_fence_generation,
                ),
            )
            if (
                self.command.action_id != self._action.action_id
                or self.command.execution_path is not ExecutionPath.DIRECT_API
                or self.command.attempt != attempt
                or self.command.source_revision != self._source_revision
                or self.command.safeguard_proof_bundle_digest
                != evidence_record.bundle.bundle_digest
            ):
                raise RuntimeError("isolated Executor command binding mismatched")
        except EventPublishNotAttemptedError as exc:
            raise DispatchNotAttemptedError(
                "isolated Executor command publication was not attempted"
            ) from exc
        except asyncio.CancelledError as exc:
            self.error = exc
            return _unknown()
        except Exception as exc:  # noqa: BLE001 - post-guard publication is ambiguous
            self.error = exc
            return _unknown()
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.UNOBSERVED,
            None,
            None,
        )


@dataclass(frozen=True, slots=True)
class SafeguardBoundEventBusDirectApiExecutionClient:
    """Run Core evidence lifecycle before publishing an isolated command."""

    client: EventBusDirectApiExecutionClient
    coordinator: SafeguardLifecycleCoordinator

    async def execute(
        self, *, action: Action, source_guard: Callable[[], Awaitable[None]] | None = None
    ) -> DirectApiExecutionResult:
        """Return only a result retaining the exact finalized bundle digest."""

        request = _build_direct_api_request(action)
        safeguards = evaluate_pre_dispatch(
            action,
            execution_path=ExecutionPath.DIRECT_API,
            plan_digest=_direct_api_plan_digest(request),
            plan_kind="isolated_executor_command",
        )
        if not isinstance(safeguards, SafeguardReceipt):
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=DirectApiExecutionOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason=safeguards.reason,
            )
        attempt = action.workflow_action.attempt if action.workflow_action is not None else 1
        port = _RemoteDirectApiLifecycleDispatchPort(
            client=self.client,
            action=action,
            source_revision=self.coordinator.source_revision,
            source_guard=source_guard,
        )
        coordinated = await self.coordinator.dispatch(
            action=action,
            safeguard_receipt=safeguards,
            dispatch_port=port,
            correlation_id=str(action.event_id),
            attempt=attempt,
            execution_venue=SafeguardExecutionVenue.ISOLATED_EXECUTOR,
        )
        if isinstance(port.error, asyncio.CancelledError):
            raise port.error
        if port.error is not None:
            effect_possible = coordinated.dispatch_performed
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=(
                    DirectApiExecutionOutcome.EXECUTION_UNKNOWN
                    if effect_possible
                    else DirectApiExecutionOutcome.DISPATCH_NOT_ATTEMPTED
                ),
                mode=action.mode,
                safeguard_bundle_digest=coordinated.bundle_digest,
                reason=f"isolated Executor client error: {type(port.error).__name__}",
                audit_context={
                    "effect_possible": effect_possible,
                    "reconciliation_required": effect_possible,
                    "continuity_quarantined": effect_possible,
                },
            )
        if coordinated.dispatch_performed:
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
                mode=action.mode,
                safeguard_bundle_digest=coordinated.bundle_digest,
                reason="isolated Executor command awaits independent effect evidence",
                audit_context={
                    "dispatch_status": "pending",
                    "command_id": (
                        str(port.command.command_id) if port.command is not None else None
                    ),
                    "effect_possible": True,
                    "reconciliation_required": True,
                    "continuity_quarantined": (
                        coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED
                    ),
                },
            )
        if not coordinated.dispatch_performed:
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=(
                    DirectApiExecutionOutcome.ALREADY_APPLIED
                    if coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                    and coordinated.bundle_digest is not None
                    else DirectApiExecutionOutcome.EXECUTION_UNKNOWN
                    if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED
                    else DirectApiExecutionOutcome.DISPATCH_NOT_ATTEMPTED
                ),
                mode=action.mode,
                safeguard_bundle_digest=coordinated.bundle_digest,
                reason=coordinated.reason,
            )
        raise AssertionError("safeguard dispatch result was not classified")


def _unknown() -> tuple[
    DispatchTransportState,
    AuthoritativeSinkState,
    None,
    None,
]:
    return (
        DispatchTransportState.UNKNOWN,
        AuthoritativeSinkState.UNKNOWN,
        None,
        None,
    )


__all__ = ["SafeguardBoundEventBusDirectApiExecutionClient"]
