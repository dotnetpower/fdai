"""Shared safeguard lifecycle adapter for tool-call provider invocations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import SafeguardRefusal, evaluate_pre_dispatch
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPreconditionError,
    ToolPromotionError,
)

if TYPE_CHECKING:
    from fdai.core.executor.tool_call import (
        ToolCallExecutionOutcome,
        ToolCallExecutionResult,
        ToolReceiptObserver,
    )

_LOGGER = logging.getLogger(__name__)


class ToolSafeguardLifecycleOwner(Protocol):
    """Narrow executor callbacks needed by the tool lifecycle adapter."""

    _executor: ToolExecutor
    _receipt_observer: ToolReceiptObserver | None
    _safeguard_coordinator: SafeguardLifecycleCoordinator | None

    def _check_blast_radius(self, action: Action) -> str | None: ...

    async def _write_audit_intent(
        self,
        *,
        action: Action,
        dry_run_receipt: str,
    ) -> None: ...

    async def _finish_from_receipt(
        self,
        *,
        action: Action,
        receipt: ToolCallReceipt,
        dry_run_receipt: str,
        safeguard_bundle_digest: str | None = None,
    ) -> ToolCallExecutionResult: ...

    async def _finish(
        self,
        *,
        action: Action,
        outcome: ToolCallExecutionOutcome,
        reason: str | None,
        receipt_ref: str | None = None,
        safeguard_bundle_digest: str | None = None,
        rollback_succeeded: bool | None = None,
        remember: bool = True,
        dry_run_receipt: str | None = None,
    ) -> ToolCallExecutionResult: ...


class ToolLifecycleDispatchPort:
    """Call one tool adapter and retain its typed receipt."""

    def __init__(
        self,
        *,
        owner: ToolSafeguardLifecycleOwner,
        action: Action,
        request: ToolCallRequest,
        dry_run_receipt: str,
    ) -> None:
        self._owner = owner
        self._action = action
        self._request = request
        self._dry_run_receipt = dry_run_receipt
        self.receipt: ToolCallReceipt | None = None
        self.error: BaseException | None = None

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
        try:
            await self._owner._write_audit_intent(
                action=self._action,
                dry_run_receipt=self._dry_run_receipt,
            )
            bound_request = replace(
                self._request,
                metadata={
                    **dict(self._request.metadata),
                    "safeguard_bundle_digest": (evidence_record.bundle.bundle_digest),
                },
            )
            self.receipt = await self._owner._executor.execute(bound_request)
            if self._owner._receipt_observer is not None and self.receipt.outcome in {
                ToolCallOutcome.SUCCEEDED,
                ToolCallOutcome.ALREADY_APPLIED,
            }:
                await self._owner._receipt_observer(bound_request, self.receipt)
        except asyncio.CancelledError as exc:
            self.error = exc
            return _unknown()
        except (ToolPromotionError, ToolPreconditionError) as exc:
            self.error = exc
            return (
                DispatchTransportState.FAILED,
                AuthoritativeSinkState.NOT_ACCEPTED,
                None,
                content_digest(
                    {
                        "domain": "tool-call-refusal",
                        "kind": exc.kind,
                        "bundle_digest": evidence_record.bundle.bundle_digest,
                    }
                ),
            )
        except ToolError as exc:
            self.error = exc
            return _unknown()
        except Exception as exc:
            self.error = exc
            return _unknown()
        receipt = self.receipt
        if receipt is None:  # pragma: no cover - assignment above is exact
            raise RuntimeError("tool adapter returned no receipt")
        accepted = receipt.outcome in {
            ToolCallOutcome.SUCCEEDED,
            ToolCallOutcome.ALREADY_APPLIED,
        }
        sink_state = (
            AuthoritativeSinkState.COMMITTED
            if accepted
            else AuthoritativeSinkState.NOT_ACCEPTED
            if receipt.outcome is ToolCallOutcome.PRECONDITION_FAILED
            else AuthoritativeSinkState.NOT_COMMITTED
        )
        return (
            DispatchTransportState.ACKNOWLEDGED,
            sink_state,
            (
                content_digest(
                    {
                        "domain": "tool-operation-reference",
                        "receipt_ref": receipt.receipt_ref,
                    }
                )
                if accepted
                else None
            ),
            content_digest(
                {
                    "domain": "tool-call-status",
                    "receipt_ref": receipt.receipt_ref,
                    "outcome": receipt.outcome.value,
                    "bundle_digest": evidence_record.bundle.bundle_digest,
                }
            ),
        )


async def execute_tool_with_safeguard_lifecycle(
    owner: ToolSafeguardLifecycleOwner,
    *,
    action: Action,
) -> ToolCallExecutionResult:
    """Invoke one tool only through the shared evidence lifecycle."""

    from fdai.core.executor.tool_call import (
        ToolCallExecutionOutcome,
        _build_tool_call_request,
        _tool_call_plan_digest,
    )

    blast_reason = owner._check_blast_radius(action)
    if blast_reason is not None:
        return await owner._finish(
            action=action,
            outcome=ToolCallExecutionOutcome.ABSTAINED_BLAST_RADIUS,
            reason=blast_reason,
        )
    request = _build_tool_call_request(action)
    safeguards = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.TOOL_CALL,
        plan_digest=_tool_call_plan_digest(request),
        plan_kind="tool_call_request",
    )
    if isinstance(safeguards, SafeguardRefusal):
        return await owner._finish(
            action=action,
            outcome=ToolCallExecutionOutcome.REJECTED_INVARIANT,
            reason=safeguards.reason,
        )
    port = ToolLifecycleDispatchPort(
        owner=owner,
        action=action,
        request=request,
        dry_run_receipt=safeguards.dry_run_receipt,
    )
    coordinator = owner._safeguard_coordinator
    if coordinator is None:  # pragma: no cover - caller narrows this branch
        raise RuntimeError("safeguard lifecycle coordinator is unavailable")
    coordinated = await coordinator.dispatch(
        action=action,
        safeguard_receipt=safeguards,
        dispatch_port=port,
        correlation_id=str(action.event_id),
        attempt=action.workflow_action.attempt if action.workflow_action is not None else 1,
    )
    if not coordinated.dispatch_performed:
        return await owner._finish(
            action=action,
            outcome=(
                ToolCallExecutionOutcome.ALREADY_APPLIED
                if coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                and coordinated.bundle_digest is not None
                else ToolCallExecutionOutcome.REJECTED_INVARIANT
            ),
            reason=coordinated.reason,
            safeguard_bundle_digest=coordinated.bundle_digest,
            remember=False,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    if port.error is not None:
        return await _finish_error(
            owner,
            action=action,
            error=port.error,
            safeguard_bundle_digest=coordinated.bundle_digest,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    receipt = port.receipt
    if receipt is None:
        return await owner._finish(
            action=action,
            outcome=ToolCallExecutionOutcome.REJECTED_INVARIANT,
            reason="tool adapter returned no lifecycle-bound receipt",
            safeguard_bundle_digest=coordinated.bundle_digest,
            remember=False,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED:
        return await owner._finish(
            action=action,
            outcome=ToolCallExecutionOutcome.FAILED,
            reason=coordinated.reason or "dispatch continuity is quarantined",
            receipt_ref=receipt.receipt_ref,
            safeguard_bundle_digest=coordinated.bundle_digest,
            rollback_succeeded=receipt.rollback_succeeded,
            remember=False,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    return await owner._finish_from_receipt(
        action=action,
        receipt=receipt,
        safeguard_bundle_digest=coordinated.bundle_digest,
        dry_run_receipt=safeguards.dry_run_receipt,
    )


async def _finish_error(
    owner: ToolSafeguardLifecycleOwner,
    *,
    action: Action,
    error: BaseException,
    safeguard_bundle_digest: str | None,
    dry_run_receipt: str,
) -> ToolCallExecutionResult:
    from fdai.core.executor.tool_call import ToolCallExecutionOutcome

    if isinstance(error, asyncio.CancelledError):
        await owner._finish(
            action=action,
            outcome=ToolCallExecutionOutcome.FAILED,
            reason="tool-call execution cancelled",
            safeguard_bundle_digest=safeguard_bundle_digest,
            rollback_succeeded=False,
            remember=False,
            dry_run_receipt=dry_run_receipt,
        )
        raise error
    if isinstance(error, ToolPromotionError):
        outcome = ToolCallExecutionOutcome.REJECTED_MODE
        reason = f"adapter refused promotion: {error}"
    elif isinstance(error, ToolPreconditionError):
        outcome = ToolCallExecutionOutcome.ABSTAINED_PRECONDITION
        reason = str(error)
    elif isinstance(error, ToolError):
        outcome = ToolCallExecutionOutcome.FAILED
        reason = f"adapter error [{error.kind}]: {error}"
    else:
        _LOGGER.error(
            "tool_call_adapter_uncontrolled",
            extra={"error_kind": type(error).__name__},
        )
        outcome = ToolCallExecutionOutcome.FAILED
        reason = f"uncontrolled adapter error: {error!r}"
    return await owner._finish(
        action=action,
        outcome=outcome,
        reason=reason,
        safeguard_bundle_digest=safeguard_bundle_digest,
        rollback_succeeded=False,
        remember=False,
        dry_run_receipt=dry_run_receipt,
    )


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


__all__ = [
    "ToolSafeguardLifecycleOwner",
    "execute_tool_with_safeguard_lifecycle",
]
