"""Immutable alert artifacts and a single guarded manual-PR sink invocation.

StateStore readers use the parent's private, content-addressed namespaces. This adapter
does not grant authority, maintain dispatch state, merge a PR, apply IaC, or call Azure.
The generic publisher lacks a conditional-source contract: a real source reader AND the
Core-owned authority fence must be bound before publication can be considered available.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Protocol

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertRollbackBaseline
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    AlertPrDispatch,
    AlertPublicationCheck,
    alert_execution_key,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchBoundaryGuard,
    DispatchNotAttemptedError,
)
from fdai.delivery.alert_noise_iac import AlertIaCPatch
from fdai.shared.contracts.models import Action, Mode, Rule
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.state_store import StateStore


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None:
        raise AlertExecutionHeld("artifact_digest_invalid")
    return value


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class StateStoreAlertPlanReader:
    """Read exact retained plan/evidence records, never scan for a latest or similar plan."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def read(self, plan_digest: str) -> AlertChangePlan:
        """Read ``alert-noise:plan:sha256:<hex>`` and reconstruct its complete commitment."""
        raw = await self._store.read_state("alert-noise:plan:" + _digest(plan_digest))
        if raw is None:
            raise AlertExecutionHeld("plan_not_retained")
        plan = AlertChangePlan.model_validate(raw)
        if digest_record(plan) != plan_digest:
            raise AlertExecutionHeld("retained_plan_mismatch")
        return plan

    async def baseline(self, plan: AlertChangePlan) -> AlertRollbackBaseline:
        """Rebuild the historical baseline, including the processing object for suppression.

        Historical baseline integrity is separate from current dispatch authority: recovery
        may need this record after forward evidence expires. Synthetic baselines never qualify.
        """
        plan = AlertChangePlan.model_validate(plan)
        raw = await self._store.read_state("alert-noise:evidence:" + plan.evidence_digest)
        if raw is None:
            raise AlertExecutionHeld("evidence_not_retained")
        evidence = AlertEvidence.model_validate(raw)
        if (
            digest_record(evidence) != plan.evidence_digest
            or evidence.stamp.synthetic
            or evidence.stamp.coverage != "complete"
            or evidence.stamp.tenant_ref != plan.tenant_ref
            or evidence.stamp.scope_ref != plan.scope_ref
        ):
            raise AlertExecutionHeld("retained_evidence_mismatch")
        rule = next((row for row in evidence.rules if row.ref == plan.treatment.target_ref), None)
        if rule is None:
            raise AlertExecutionHeld("baseline_target_missing")
        processing = None
        if plan.treatment.kind == "suppression":
            processing = next(
                (
                    row
                    for row in evidence.processing_rules
                    if row.ref == plan.treatment.processing_rule_ref
                ),
                None,
            )
            if processing is None or set(processing.rule_refs) != {rule.ref}:
                raise AlertExecutionHeld("baseline_processing_target_missing")
        baseline = AlertRollbackBaseline(rule=rule, processing_rule=processing)
        if (
            digest_record(baseline) != plan.rollback_ref
            or (processing.revision if processing else rule.revision) != plan.target_revision
        ):
            raise AlertExecutionHeld("rollback_baseline_mismatch")
        return baseline


class AlertPatchReader(Protocol):
    """Read the exact server-rendered source/result pair for this immutable plan."""

    async def read(self, plan: AlertChangePlan) -> AlertIaCPatch: ...


class StateStoreAlertPatchReader:
    """Read private patch content at ``alert-noise:patch:sha256:<plan hex>`` only."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def read(self, plan: AlertChangePlan) -> AlertIaCPatch:
        """Revalidate every retained field; the path is never inferred from a rule or target."""
        plan = AlertChangePlan.model_validate(plan)
        digest = digest_record(plan)
        raw = await self._store.read_state("alert-noise:patch:" + digest)
        if raw is None:
            raise AlertExecutionHeld("patch_not_retained")
        expected = {"plan_digest", "path", "source_digest", "result_digest", "forward", "rollback"}
        if set(raw) != expected or raw.get("plan_digest") != digest:
            raise AlertExecutionHeld("retained_patch_binding_mismatch")
        if any(type(raw[name]) is not str for name in expected):
            raise AlertExecutionHeld("retained_patch_shape_invalid")
        patch = AlertIaCPatch(
            path=raw["path"],
            source_digest=raw["source_digest"],
            result_digest=raw["result_digest"],
            forward=raw["forward"],
            rollback=raw["rollback"],
        )
        _require_patch(patch)
        return patch


class AlertIaCSourceReader(Protocol):
    """Read an existing exact file from the composition-bound IaC repository revision.

    The authority lease must fence that revision through the publisher's branch/file commit.
    Missing content is not permission to create a resource or select a different file.
    """

    async def read(self, *, path: str) -> str | None: ...


def _require_patch(patch: AlertIaCPatch) -> None:
    """Reject traversal, ambiguous paths, oversized content and changed before/after bytes."""
    if type(patch) is not AlertIaCPatch:
        raise AlertExecutionHeld("patch_shape_invalid")
    path = PurePosixPath(patch.path)
    if (
        not 1 <= len(patch.path) <= 512
        or str(path) != patch.path
        or path.is_absolute()
        or any(part in {".", "..", ".git"} for part in path.parts)
        or re.fullmatch(r"[a-zA-Z0-9_./-]+\.tf\.json", patch.path) is None
    ):
        raise AlertExecutionHeld("patch_path_invalid")
    for text, digest in (
        (patch.rollback, patch.source_digest),
        (patch.forward, patch.result_digest),
    ):
        if (
            type(text) is not str
            or not 1 <= len(text.encode("utf-8")) <= 1_000_000
            or _text_digest(text) != _digest(digest)
        ):
            raise AlertExecutionHeld("patch_content_mismatch")
    if patch.source_digest == patch.result_digest:
        raise AlertExecutionHeld("patch_has_no_change")


class AlertManualPrDispatcher:
    """Prepare a manual PR and supply its stateless sink to the existing coordinator.

    There is deliberately no standalone ``submit(plan, actor=...)`` execution entry point.
    Shadow is refused even when this delivery adapter is called without the outer port.
    """

    def __init__(
        self,
        *,
        patches: AlertPatchReader,
        publisher: RemediationPrPublisher,
        source_reader: AlertIaCSourceReader | None = None,
    ) -> None:
        self._patches, self._publisher, self._source_reader = patches, publisher, source_reader

    async def prepare(self, *, action: Action, rule: Rule, plan: AlertChangePlan) -> RemediationPr:
        """Read, rehash and bind one exact forward or conditional-restore file without effects."""
        plan = AlertChangePlan.model_validate(plan)
        digest = digest_record(plan)
        if (
            action.mode is not Mode.ENFORCE
            or action.action_type not in {plan.action_type, RESTORE_ACTION}
            or action.params != {"plan_digest": digest.removeprefix("sha256:")}
            or action.idempotency_key != alert_execution_key(action.action_type, digest)
            or not action.executor_identity_ref
            or action.workflow_action is None
            or rule.id not in action.citing_rules
        ):
            raise AlertExecutionHeld("publication_action_mismatch")
        patch = await self._patches.read(plan)
        _require_patch(patch)
        restore = action.action_type == RESTORE_ACTION
        source = patch.result_digest if restore else patch.source_digest
        result = patch.source_digest if restore else patch.result_digest
        return RemediationPr(
            action_id=action.action_id,
            idempotency_key=action.idempotency_key,
            rule_ids=tuple(action.citing_rules),
            title="Review approved alert configuration change",
            body=(
                f"Plan: {digest}\nAction: {action.action_type}\n"
                f"Source: {source}\nResult: {result}\nRollback baseline: {plan.rollback_ref}\n"
                "Manual review and a separately guarded apply are required.\n"
                "Publication does not verify Azure configuration or notification effects.\n"
            ),
            patch=patch.rollback if restore else patch.forward,
            patch_path=patch.path,
            labels=("enforce", "hil", "require-manual-merge", "alert-noise"),
            mode=action.mode,
            metadata=MappingProxyType(
                {
                    "plan_digest": digest,
                    "action_type": action.action_type,
                    "source_digest": source,
                    "result_digest": result,
                    "evidence_digest": plan.evidence_digest,
                    "rollback_ref": plan.rollback_ref,
                    "execution_path": "pr_manual",
                    "executor_identity_ref": action.executor_identity_ref,
                }
            ),
        )

    def dispatch_port(
        self,
        *,
        pr: RemediationPr,
        revalidate: Callable[[], Awaitable[AlertPublicationCheck]],
        audit_intent: Callable[[str], Awaitable[None]],
        dry_run_receipt: str,
    ) -> AlertPrDispatch:
        """Create a single invocation adapter; it owns no retries, locks or durable journal."""
        return _AlertPrDispatchPort(
            pr=pr,
            publisher=self._publisher,
            revalidate=revalidate,
            source_reader=self._source_reader,
            audit_intent=audit_intent,
            dry_run_receipt=dry_run_receipt,
        )


class _AlertPrDispatchPort:
    """Call the real coordinator guard immediately at the existing publisher boundary."""

    def __init__(
        self,
        *,
        pr: RemediationPr,
        publisher: RemediationPrPublisher,
        source_reader: AlertIaCSourceReader | None,
        revalidate: Callable[[], Awaitable[AlertPublicationCheck]],
        audit_intent: Callable[[str], Awaitable[None]],
        dry_run_receipt: str,
    ) -> None:
        self._pr, self._publisher, self._source = pr, publisher, source_reader
        self._revalidate, self._audit_intent = revalidate, audit_intent
        self._dry_run_receipt = _digest(dry_run_receipt)
        self.receipt: PublishReceipt | None = None
        self.error: BaseException | None = None
        self.invoked = False
        self.bundle_digest: str | None = None

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[DispatchTransportState, AuthoritativeSinkState, str | None, str | None]:
        del started_at
        if (
            self.invoked
            or self._source is None
            or self._pr.mode is not Mode.ENFORCE
            or not {"hil", "enforce", "require-manual-merge"}.issubset(self._pr.labels)
        ):
            raise AlertExecutionHeld("publication_binding_missing")
        self.bundle_digest = evidence_record.bundle.bundle_digest
        pr = replace(
            self._pr,
            metadata=MappingProxyType(
                {
                    **dict(self._pr.metadata),
                    "safeguard_bundle_digest": self.bundle_digest,
                    "dry_run_receipt": self._dry_run_receipt,
                }
            ),
        )
        await self._audit_intent(self.bundle_digest)
        async with asyncio.timeout(15):
            current = await self._source.read(path=pr.patch_path)
        if (
            type(current) is not str
            or len(current.encode("utf-8")) > 1_000_000
            or _text_digest(current) != pr.metadata["source_digest"]
        ):
            raise AlertExecutionHeld("publication_source_changed")
        check = await self._revalidate()
        invoked_at = await pre_invoke_guard()
        try:
            check(invoked_at)
        except Exception as exc:
            raise DispatchNotAttemptedError("alert boundary admission expired") from exc
        self.invoked = True
        try:
            receipt = await self._publisher.publish(pr)
            if (
                type(receipt) is not PublishReceipt
                or not receipt.pr_ref.strip()
                or type(receipt.already_existed) is not bool
                or receipt.state not in {"open", "closed", "merged"}
            ):
                raise ValueError("publisher receipt is invalid")
            self.receipt = receipt
        except (asyncio.CancelledError, Exception) as exc:
            self.error = exc
            return DispatchTransportState.UNKNOWN, AuthoritativeSinkState.UNKNOWN, None, None
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.COMMITTED,
            content_digest({"domain": "pr-publish-reference", "pr_ref": receipt.pr_ref}),
            content_digest(
                {
                    "domain": "pr-publish-status",
                    "pr_ref": receipt.pr_ref,
                    "state": receipt.state,
                    "already_existed": receipt.already_existed,
                }
            ),
        )
