"""Shared safeguard lifecycle adapter for direct-API provider calls."""

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
from fdai.core.executor.safeguard_evidence_lifecycle import DispatchBoundaryGuard
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import SafeguardRefusal, evaluate_pre_dispatch
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.direct_api import (
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
    DirectApiRetryableError,
)

if TYPE_CHECKING:
    from fdai.core.executor.direct_api import (
        DirectApiExecutionOutcome,
        DirectApiExecutionResult,
    )

_LOGGER = logging.getLogger(__name__)


class DirectApiSafeguardLifecycleOwner(Protocol):
    """Narrow executor callbacks needed by the direct-API adapter."""

    _executor: DirectApiExecutor
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
        receipt: DirectApiReceipt,
        dry_run_receipt: str,
        safeguard_bundle_digest: str | None = None,
    ) -> DirectApiExecutionResult: ...

    async def _finish(
        self,
        *,
        action: Action,
        outcome: DirectApiExecutionOutcome,
        reason: str | None,
        receipt_ref: str | None = None,
        safeguard_bundle_digest: str | None = None,
        rollback_succeeded: bool | None = None,
        remember: bool = True,
        dry_run_receipt: str | None = None,
    ) -> DirectApiExecutionResult: ...


class DirectApiLifecycleDispatchPort:
    """Call one direct-API adapter and retain its typed result."""

    def __init__(
        self,
        *,
        owner: DirectApiSafeguardLifecycleOwner,
        action: Action,
        request: DirectApiRequest,
        dry_run_receipt: str,
    ) -> None:
        self._owner = owner
        self._action = action
        self._request = request
        self._dry_run_receipt = dry_run_receipt
        self.receipt: DirectApiReceipt | None = None
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
        await self._owner._write_audit_intent(
            action=self._action,
            dry_run_receipt=self._dry_run_receipt,
        )
        await pre_invoke_guard()
        try:
            self.receipt = await self._owner._executor.execute(
                replace(
                    self._request,
                    metadata={
                        **dict(self._request.metadata),
                        "safeguard_bundle_digest": (evidence_record.bundle.bundle_digest),
                    },
                )
            )
        except asyncio.CancelledError as exc:
            self.error = exc
            return _unknown()
        except (
            DirectApiPromotionError,
            DirectApiPreconditionError,
            DirectApiAuthenticationError,
            DirectApiPermissionDeniedError,
            DirectApiPolicyDeniedError,
            DirectApiNetworkDeniedError,
            DirectApiRetryableError,
        ) as exc:
            self.error = exc
            return (
                DispatchTransportState.FAILED,
                AuthoritativeSinkState.NOT_ACCEPTED,
                None,
                content_digest(
                    {
                        "domain": "direct-api-refusal",
                        "kind": exc.kind,
                        "bundle_digest": evidence_record.bundle.bundle_digest,
                    }
                ),
            )
        except DirectApiError as exc:
            self.error = exc
            return _unknown()
        except Exception as exc:
            self.error = exc
            return _unknown()
        receipt = self.receipt
        if receipt is None:  # pragma: no cover - assignment above is exact
            raise RuntimeError("direct-API adapter returned no receipt")
        accepted = receipt.outcome in {
            DirectApiOutcome.SUCCEEDED,
            DirectApiOutcome.ALREADY_APPLIED,
        }
        rolled_back = (
            receipt.outcome in {DirectApiOutcome.STOPPED, DirectApiOutcome.FAILED}
            and receipt.rollback_succeeded is True
        )
        sink_state = (
            AuthoritativeSinkState.COMMITTED
            if accepted
            else AuthoritativeSinkState.NOT_ACCEPTED
            if receipt.outcome is DirectApiOutcome.PRECONDITION_FAILED
            else AuthoritativeSinkState.NOT_COMMITTED
            if rolled_back
            else AuthoritativeSinkState.UNKNOWN
        )
        known_status = (
            accepted or receipt.outcome is DirectApiOutcome.PRECONDITION_FAILED or rolled_back
        )
        return (
            DispatchTransportState.ACKNOWLEDGED,
            sink_state,
            (
                content_digest(
                    {
                        "domain": "direct-api-operation-reference",
                        "receipt_ref": receipt.receipt_ref,
                    }
                )
                if accepted
                else None
            ),
            (
                content_digest(
                    {
                        "domain": "direct-api-status",
                        "receipt_ref": receipt.receipt_ref,
                        "outcome": receipt.outcome.value,
                        "bundle_digest": evidence_record.bundle.bundle_digest,
                    }
                )
                if known_status
                else None
            ),
        )


async def execute_direct_api_with_safeguard_lifecycle(
    owner: DirectApiSafeguardLifecycleOwner,
    *,
    action: Action,
) -> DirectApiExecutionResult:
    """Dispatch one provider request only through the shared lifecycle."""

    from fdai.core.executor.direct_api import (
        DirectApiExecutionOutcome,
        _build_direct_api_request,
        _direct_api_plan_digest,
    )

    blast_reason = owner._check_blast_radius(action)
    if blast_reason is not None:
        return await owner._finish(
            action=action,
            outcome=DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS,
            reason=blast_reason,
        )
    request = _build_direct_api_request(action)
    safeguards = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest=_direct_api_plan_digest(request),
        plan_kind="direct_api_request",
    )
    if isinstance(safeguards, SafeguardRefusal):
        return await owner._finish(
            action=action,
            outcome=DirectApiExecutionOutcome.REJECTED_INVARIANT,
            reason=safeguards.reason,
        )
    port = DirectApiLifecycleDispatchPort(
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
    if port.error is not None:
        return await _finish_error(
            owner,
            action=action,
            error=port.error,
            safeguard_bundle_digest=coordinated.bundle_digest,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED:
        receipt = port.receipt
        return await owner._finish(
            action=action,
            outcome=DirectApiExecutionOutcome.FAILED,
            reason=coordinated.reason or "dispatch continuity is quarantined",
            receipt_ref=receipt.receipt_ref if receipt is not None else None,
            safeguard_bundle_digest=coordinated.bundle_digest,
            rollback_succeeded=(receipt.rollback_succeeded if receipt is not None else False),
            remember=False,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    if not coordinated.dispatch_performed:
        return await owner._finish(
            action=action,
            outcome=(
                DirectApiExecutionOutcome.ALREADY_APPLIED
                if coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                and coordinated.bundle_digest is not None
                else DirectApiExecutionOutcome.REJECTED_INVARIANT
            ),
            reason=coordinated.reason,
            safeguard_bundle_digest=coordinated.bundle_digest,
            remember=False,
            dry_run_receipt=safeguards.dry_run_receipt,
        )
    receipt = port.receipt
    if receipt is None:
        return await owner._finish(
            action=action,
            outcome=DirectApiExecutionOutcome.REJECTED_INVARIANT,
            reason="direct-API adapter returned no lifecycle-bound receipt",
            safeguard_bundle_digest=coordinated.bundle_digest,
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
    owner: DirectApiSafeguardLifecycleOwner,
    *,
    action: Action,
    error: BaseException,
    safeguard_bundle_digest: str | None,
    dry_run_receipt: str,
) -> DirectApiExecutionResult:
    from fdai.core.executor.direct_api import DirectApiExecutionOutcome

    if isinstance(error, asyncio.CancelledError):
        try:
            await owner._finish(
                action=action,
                outcome=DirectApiExecutionOutcome.FAILED,
                reason="direct-API execution cancelled",
                safeguard_bundle_digest=safeguard_bundle_digest,
                rollback_succeeded=False,
                remember=False,
                dry_run_receipt=dry_run_receipt,
            )
        except Exception as audit_error:
            _LOGGER.exception(
                "direct_api_cancellation_terminal_audit_failed",
                extra={"action_id": str(action.action_id)},
            )
            raise error from audit_error
        raise error
    if isinstance(error, DirectApiPromotionError):
        outcome = DirectApiExecutionOutcome.REJECTED_MODE
        reason = f"adapter refused promotion: {error}"
    elif isinstance(error, DirectApiPreconditionError):
        outcome = DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
        reason = str(error)
    elif isinstance(error, DirectApiAuthenticationError):
        outcome = DirectApiExecutionOutcome.AUTHENTICATION_FAILED
        reason = str(error)
    elif isinstance(error, DirectApiPermissionDeniedError):
        outcome = DirectApiExecutionOutcome.PERMISSION_DENIED
        reason = str(error)
    elif isinstance(error, DirectApiPolicyDeniedError):
        outcome = DirectApiExecutionOutcome.POLICY_DENIED
        reason = str(error)
    elif isinstance(error, DirectApiNetworkDeniedError):
        outcome = DirectApiExecutionOutcome.NETWORK_DENIED
        reason = str(error)
    elif isinstance(error, DirectApiRetryableError):
        outcome = DirectApiExecutionOutcome.FAILED
        reason = f"retryable adapter error: {error}"
    elif isinstance(error, DirectApiError):
        outcome = DirectApiExecutionOutcome.FAILED
        reason = f"adapter error [{error.kind}]: {error}"
    else:
        _LOGGER.error(
            "direct_api_adapter_uncontrolled",
            extra={"error_kind": type(error).__name__},
        )
        outcome = DirectApiExecutionOutcome.FAILED
        reason = f"uncontrolled adapter error: {type(error).__name__}"
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
    "DirectApiSafeguardLifecycleOwner",
    "execute_direct_api_with_safeguard_lifecycle",
]
