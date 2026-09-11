"""Shared safeguard lifecycle wrapper for the isolated Executor client."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.direct_api import (
    _build_direct_api_request,
    _direct_api_plan_digest,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.runtime.isolated_executor_client import (
    EventBusDirectApiExecutionClient,
    RemoteDirectApiExecutionOutcome,
    RemoteDirectApiExecutionResult,
)
from fdai.shared.contracts.models import Action, ExecutionPath


class _RemoteDirectApiLifecycleDispatchPort:
    """Send one safeguard-bound command while Core retains the target lock."""

    def __init__(
        self,
        *,
        client: EventBusDirectApiExecutionClient,
        action: Action,
        source_revision: str,
        attempt: int,
    ) -> None:
        self._client = client
        self._action = action
        self._source_revision = source_revision
        self._attempt = attempt
        self.result: RemoteDirectApiExecutionResult | None = None

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        del started_at
        self.result = await self._client.execute_bound(
            action=self._action,
            safeguard_bundle_digest=evidence_record.bundle.bundle_digest,
            source_revision=self._source_revision,
            attempt=self._attempt,
        )
        result = self.result
        if result.audit_context.get("transport_failure") is True:
            return (
                DispatchTransportState.UNKNOWN,
                AuthoritativeSinkState.UNKNOWN,
                None,
                None,
            )
        accepted = result.outcome in {
            RemoteDirectApiExecutionOutcome.DISPATCHED,
            RemoteDirectApiExecutionOutcome.ALREADY_APPLIED,
        }
        not_accepted = result.outcome in {
            RemoteDirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS,
            RemoteDirectApiExecutionOutcome.ABSTAINED_PRECONDITION,
            RemoteDirectApiExecutionOutcome.AUTHENTICATION_FAILED,
            RemoteDirectApiExecutionOutcome.PERMISSION_DENIED,
            RemoteDirectApiExecutionOutcome.POLICY_DENIED,
            RemoteDirectApiExecutionOutcome.NETWORK_DENIED,
            RemoteDirectApiExecutionOutcome.REJECTED_MODE,
            RemoteDirectApiExecutionOutcome.REJECTED_INVARIANT,
            RemoteDirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT,
            RemoteDirectApiExecutionOutcome.EXPIRED,
        }
        sink_state = (
            AuthoritativeSinkState.COMMITTED
            if accepted
            else AuthoritativeSinkState.NOT_ACCEPTED
            if not_accepted
            else AuthoritativeSinkState.NOT_COMMITTED
        )
        return (
            DispatchTransportState.ACKNOWLEDGED,
            sink_state,
            (
                content_digest(
                    {
                        "domain": "isolated-executor-operation-reference",
                        "receipt_ref": result.receipt_ref,
                    }
                )
                if accepted
                else None
            ),
            content_digest(
                {
                    "domain": "isolated-executor-status",
                    "outcome": result.outcome.value,
                    "executor_receipt_ref": result.audit_context.get("executor_receipt_ref"),
                    "bundle_digest": evidence_record.bundle.bundle_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class SafeguardBoundEventBusDirectApiExecutionClient:
    """Run Core evidence lifecycle before publishing an isolated command."""

    client: EventBusDirectApiExecutionClient
    coordinator: SafeguardLifecycleCoordinator

    async def execute(self, *, action: Action) -> RemoteDirectApiExecutionResult:
        """Return only a result retaining the exact finalized bundle digest."""

        request = _build_direct_api_request(action)
        safeguards = evaluate_pre_dispatch(
            action,
            execution_path=ExecutionPath.DIRECT_API,
            plan_digest=_direct_api_plan_digest(request),
            plan_kind="isolated_executor_command",
        )
        if not isinstance(safeguards, SafeguardReceipt):
            return RemoteDirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=RemoteDirectApiExecutionOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason=safeguards.reason,
            )
        attempt = action.workflow_action.attempt if action.workflow_action is not None else 1
        port = _RemoteDirectApiLifecycleDispatchPort(
            client=self.client,
            action=action,
            source_revision=self.coordinator.source_revision,
            attempt=attempt,
        )
        coordinated = await self.coordinator.dispatch(
            action=action,
            safeguard_receipt=safeguards,
            dispatch_port=port,
            correlation_id=str(action.event_id),
            attempt=attempt,
        )
        if not coordinated.dispatch_performed:
            return RemoteDirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=(
                    RemoteDirectApiExecutionOutcome.ALREADY_APPLIED
                    if coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                    and coordinated.bundle_digest is not None
                    else RemoteDirectApiExecutionOutcome.REJECTED_INVARIANT
                ),
                mode=action.mode,
                safeguard_bundle_digest=coordinated.bundle_digest,
                reason=coordinated.reason,
            )
        if port.result is None:
            return RemoteDirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=RemoteDirectApiExecutionOutcome.FAILED,
                mode=action.mode,
                safeguard_bundle_digest=coordinated.bundle_digest,
                reason="isolated Executor returned no lifecycle-bound result",
            )
        result = replace(
            port.result,
            safeguard_bundle_digest=coordinated.bundle_digest,
            audit_context={
                **port.result.audit_context,
                "safeguard_bundle_digest": coordinated.bundle_digest,
            },
        )
        if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED:
            return replace(
                result,
                outcome=RemoteDirectApiExecutionOutcome.FAILED,
                reason=coordinated.reason or "dispatch continuity is quarantined",
            )
        return result


__all__ = ["SafeguardBoundEventBusDirectApiExecutionClient"]
