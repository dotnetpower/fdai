"""Shared safeguard lifecycle adapter for PR-native and PR-manual sinks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.renderer import RenderError, RenderRequest, TemplateRenderer
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.safeguards import (
    SafeguardRefusal,
    evaluate_pre_dispatch,
)
from fdai.shared.contracts.models import Action, ExecutionPath, Rule
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)

if TYPE_CHECKING:
    from fdai.core.executor.executor import ExecutionResult, ExecutorOutcome


class PrSafeguardLifecycleOwner(Protocol):
    """Narrow executor callbacks needed by the lifecycle adapter."""

    _publisher: RemediationPrPublisher
    _renderer: TemplateRenderer
    _safeguard_coordinator: SafeguardLifecycleCoordinator | None

    def _check_blast_radius(self, action: Action) -> str | None: ...

    async def _write_audit_intent(
        self,
        *,
        action: Action,
        rule: Rule,
        dry_run_receipt: str,
        execution_path: ExecutionPath,
    ) -> None: ...

    async def _finish(
        self,
        *,
        action: Action,
        rule: Rule,
        outcome: ExecutorOutcome,
        reason: str | None,
        pr_ref: str | None = None,
        pr_url: str | None = None,
        safeguard_bundle_digest: str | None = None,
        dry_run_receipt: str | None = None,
        execution_path: ExecutionPath | None = None,
        remember: bool = True,
    ) -> ExecutionResult: ...


class PrLifecycleDispatchPort:
    """Call the PR sink once and retain its path-specific receipt."""

    def __init__(
        self,
        *,
        owner: PrSafeguardLifecycleOwner,
        action: Action,
        rule: Rule,
        pr: RemediationPr,
        execution_path: ExecutionPath,
        dry_run_receipt: str,
    ) -> None:
        self._owner = owner
        self._action = action
        self._rule = rule
        self._pr = pr
        self._execution_path = execution_path
        self._dry_run_receipt = dry_run_receipt
        self.receipt: PublishReceipt | None = None
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
        bound_pr = replace(
            self._pr,
            metadata={
                **dict(self._pr.metadata),
                "safeguard_bundle_digest": evidence_record.bundle.bundle_digest,
            },
        )
        try:
            await self._owner._write_audit_intent(
                action=self._action,
                rule=self._rule,
                dry_run_receipt=self._dry_run_receipt,
                execution_path=self._execution_path,
            )
            self.receipt = await self._owner._publisher.publish(bound_pr)
        except (asyncio.CancelledError, Exception) as exc:
            self.error = exc
            return (
                DispatchTransportState.UNKNOWN,
                AuthoritativeSinkState.UNKNOWN,
                None,
                None,
            )
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.COMMITTED,
            content_digest(
                {
                    "domain": "pr-publish-reference",
                    "pr_ref": self.receipt.pr_ref,
                }
            ),
            content_digest(
                {
                    "domain": "pr-publish-status",
                    "pr_ref": self.receipt.pr_ref,
                    "state": self.receipt.state,
                    "already_existed": self.receipt.already_existed,
                }
            ),
        )


async def execute_pr_with_safeguard_lifecycle(
    owner: PrSafeguardLifecycleOwner,
    *,
    action: Action,
    rule: Rule,
    execution_path: ExecutionPath,
) -> ExecutionResult:
    """Publish one PR only through the shared safeguard lifecycle."""

    from fdai.core.executor.executor import (
        ExecutorOutcome,
        _build_remediation_pr,
        _pr_plan_digest,
    )

    blast_reason = owner._check_blast_radius(action)
    if blast_reason is not None:
        return await owner._finish(
            action=action,
            rule=rule,
            outcome=ExecutorOutcome.ABSTAINED_BLAST_RADIUS,
            reason=blast_reason,
            execution_path=execution_path,
        )
    try:
        patch = owner._renderer.render(
            RenderRequest(
                rule=rule,
                resource_id=action.target_resource_ref,
                params=dict(action.params),
            )
        )
    except RenderError as exc:
        return await owner._finish(
            action=action,
            rule=rule,
            outcome=ExecutorOutcome.ABSTAINED_RENDER_ERROR,
            reason=str(exc),
            execution_path=execution_path,
        )
    safeguards = evaluate_pre_dispatch(
        action,
        execution_path=execution_path,
        plan_digest=_pr_plan_digest(rule=rule, patch=patch) if patch.strip() else "",
        plan_kind="remediation_patch",
    )
    if isinstance(safeguards, SafeguardRefusal):
        return await owner._finish(
            action=action,
            rule=rule,
            outcome=ExecutorOutcome.REJECTED_INVARIANT,
            reason=safeguards.reason,
            execution_path=execution_path,
        )
    dispatch_port = PrLifecycleDispatchPort(
        owner=owner,
        action=action,
        rule=rule,
        pr=_build_remediation_pr(
            action=action,
            rule=rule,
            patch=patch,
            dry_run_receipt=safeguards.dry_run_receipt,
        ),
        execution_path=execution_path,
        dry_run_receipt=safeguards.dry_run_receipt,
    )
    coordinator = owner._safeguard_coordinator
    if coordinator is None:  # pragma: no cover - caller narrows this branch
        raise RuntimeError("safeguard lifecycle coordinator is unavailable")
    coordinated = await coordinator.dispatch(
        action=action,
        safeguard_receipt=safeguards,
        dispatch_port=dispatch_port,
        correlation_id=str(action.event_id),
        attempt=action.workflow_action.attempt if action.workflow_action is not None else 1,
    )
    if not coordinated.dispatch_performed:
        return await owner._finish(
            action=action,
            rule=rule,
            outcome=(
                ExecutorOutcome.ALREADY_EXISTED
                if coordinated.disposition is SafeguardCoordinationDisposition.DUPLICATE
                and coordinated.bundle_digest is not None
                else ExecutorOutcome.REJECTED_INVARIANT
            ),
            reason=coordinated.reason,
            safeguard_bundle_digest=coordinated.bundle_digest,
            execution_path=execution_path,
            remember=False,
        )
    if dispatch_port.error is not None:
        await owner._finish(
            action=action,
            rule=rule,
            outcome=ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN,
            reason="publisher outcome is unknown after an adapter error",
            safeguard_bundle_digest=coordinated.bundle_digest,
            dry_run_receipt=safeguards.dry_run_receipt,
            execution_path=execution_path,
            remember=False,
        )
        raise dispatch_port.error
    receipt = dispatch_port.receipt
    if receipt is None:
        return await owner._finish(
            action=action,
            rule=rule,
            outcome=ExecutorOutcome.REJECTED_INVARIANT,
            reason="publisher returned no lifecycle-bound receipt",
            safeguard_bundle_digest=coordinated.bundle_digest,
            dry_run_receipt=safeguards.dry_run_receipt,
            execution_path=execution_path,
            remember=False,
        )
    return await owner._finish(
        action=action,
        rule=rule,
        outcome=(
            ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN
            if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED
            else ExecutorOutcome.ALREADY_EXISTED
            if receipt.already_existed
            else ExecutorOutcome.PUBLISHED
        ),
        reason=(
            coordinated.reason or "dispatch continuity is quarantined"
            if coordinated.disposition is SafeguardCoordinationDisposition.QUARANTINED
            else None
        ),
        pr_ref=receipt.pr_ref,
        pr_url=receipt.url,
        safeguard_bundle_digest=coordinated.bundle_digest,
        dry_run_receipt=safeguards.dry_run_receipt,
        execution_path=execution_path,
        remember=coordinated.disposition is not SafeguardCoordinationDisposition.QUARANTINED,
    )


__all__ = ["PrSafeguardLifecycleOwner", "execute_pr_with_safeguard_lifecycle"]
