"""Production coordinator for the complete safeguard evidence lifecycle.

This module owns the order of the safeguard phases around one real dispatch.
Each phase lives in a focused sibling module and is re-exported here so the
public import surface is unchanged:

* :mod:`fdai.core.executor.safeguard_lifecycle_models` - result, disposition,
  and configuration records.
* :mod:`fdai.core.executor.safeguard_lifecycle_denial` - durable denial
  journal and the single aware lifecycle clock.
* :mod:`fdai.core.executor.safeguard_lifecycle_preparation` - provider-owned
  preparation inside the held logical-target lock.
* :mod:`fdai.core.executor.safeguard_hold_fenced_port` - hold fencing applied
  immediately before the provider is invoked.
* :mod:`fdai.core.executor.safeguard_lifecycle_closure` - atomic post-release
  closure.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.executor.audit_intent import AuditIntentStore
from fdai.core.executor.idempotency_reservation import IdempotencyReservationStore
from fdai.core.executor.lock_continuity import EffectSinkContinuityPolicy
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchEvidenceStore
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchPort,
    SafeguardEvidenceLifecycleResult,
)
from fdai.core.executor.safeguard_lifecycle_closure import SafeguardClosureFinalizer
from fdai.core.executor.safeguard_lifecycle_denial import SafeguardDenialJournal
from fdai.core.executor.safeguard_lifecycle_models import (
    ProductionSafeguardStore,
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
    SafeguardCoordinationError,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguard_lifecycle_preparation import SafeguardLifecyclePreparer
from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
    SafeguardPreBundleCommitmentStore,
)
from fdai.core.executor.safeguards import SafeguardReceipt
from fdai.core.executor.target_dispatch_fence_store import TargetDispatchFenceStore
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.automation_hold_state import (
    AutomationHoldStateReader,
    HoldReleaseAuthorizationReader,
)
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    HeldResourceLock,
    ResourceLockAcquisitionRequest,
    require_evidence_resource_lock,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class SafeguardLifecycleCoordinator:
    """Order every provider-owned safeguard phase around one real dispatch."""

    def __init__(
        self,
        *,
        resource_lock: EvidenceResourceLock,
        reservation_store: IdempotencyReservationStore,
        audit_intent_store: AuditIntentStore,
        fence_store: TargetDispatchFenceStore,
        evidence_store: SafeguardDispatchEvidenceStore,
        closure_store: PostReleaseClosureStore,
        denial_audit_store: StateStore,
        continuity_policy: EffectSinkContinuityPolicy,
        config: SafeguardLifecycleCoordinatorConfig,
        commitment_store: SafeguardPreBundleCommitmentStore | None = None,
        hold_state_reader: AutomationHoldStateReader | None = None,
        hold_release_authorizations: HoldReleaseAuthorizationReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._resource_lock = require_evidence_resource_lock(
            resource_lock,
            production=config.production,
        )
        self._config = config
        self._commitment_store = commitment_store
        self._denial = SafeguardDenialJournal(
            config=config,
            denial_audit_store=denial_audit_store,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        self._preparer = SafeguardLifecyclePreparer(
            reservation_store=reservation_store,
            audit_intent_store=audit_intent_store,
            fence_store=fence_store,
            evidence_store=evidence_store,
            denial_audit_store=denial_audit_store,
            continuity_policy=continuity_policy,
            config=config,
            denial=self._denial,
            hold_state_reader=hold_state_reader,
            hold_release_authorizations=hold_release_authorizations,
        )
        self._closure = SafeguardClosureFinalizer(
            closure_store=closure_store,
            denial=self._denial,
        )
        if config.production:
            stores = (
                reservation_store,
                audit_intent_store,
                fence_store,
                evidence_store,
                closure_store,
            )
            if any(
                not isinstance(store, ProductionSafeguardStore)
                or store.production_eligible is not True
                for store in stores
            ):
                raise RuntimeError("production safeguard lifecycle stores are unavailable")

    @property
    def production_ready(self) -> bool:
        """Return whether this coordinator was composed for production."""

        return self._config.production

    @property
    def source_revision(self) -> str:
        """Return the exact source revision bound to every lifecycle."""

        return self._config.source_revision

    async def prepare_pre_bundle_commitment(
        self,
        *,
        action: Action,
        execution_path: ExecutionPath,
        correlation_id: str,
    ) -> SafeguardPreBundleCommitment:
        """Persist a workflow commitment before target locking or reuse it exactly."""

        lineage = action.workflow_action
        if lineage is None:
            return SafeguardPreBundleCommitment.create(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
                committed_at=self._now(),
            )
        store = self._commitment_store
        if store is None:
            raise SafeguardCoordinationError(
                "workflow safeguard pre-bundle commitment store is unavailable"
            )
        existing = await store.read(
            process_id=lineage.process_id,
            step_id=lineage.step_id,
            attempt=lineage.attempt,
        )
        if existing is not None:
            existing.require_matches(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
            )
            return existing
        commitment = SafeguardPreBundleCommitment.create(
            action=action,
            execution_path=execution_path,
            source_revision=self.source_revision,
            committed_at=self._now(),
        )
        bound = await store.bind(
            process_id=lineage.process_id,
            step_id=lineage.step_id,
            attempt=lineage.attempt,
            correlation_id=correlation_id or lineage.proposal_ref,
            commitment=commitment,
        )
        bound.require_matches(
            action=action,
            execution_path=execution_path,
            source_revision=self.source_revision,
        )
        return bound

    async def dispatch(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        dispatch_port: DispatchPort,
        correlation_id: str,
        attempt: int = 1,
    ) -> SafeguardCoordinatedDispatchResult:
        """Run prior phases, the shared lifecycle, release, and atomic closure."""

        if type(safeguard_receipt) is not SafeguardReceipt:
            return await self._denial.deny(action, "safeguard receipt is missing or invalid")
        execution_path = safeguard_receipt.execution_path
        try:
            commitment = await self.prepare_pre_bundle_commitment(
                action=action,
                execution_path=execution_path,
                correlation_id=correlation_id,
            )
            commitment.require_matches(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
            )
        except (ValueError, SafeguardCoordinationError) as exc:
            return await self._denial.deny(action, str(exc))
        if attempt < 1:
            return await self._denial.deny(action, "safeguard lifecycle attempt MUST be positive")

        acquisition_request = ResourceLockAcquisitionRequest.create(
            target_ref=action.target_resource_ref,
            action_digest=safeguard_receipt.action_digest,
            attempt=attempt,
            producer_id=self._config.producer_id,
            producer_version=self._config.producer_version,
            source_revision=self.source_revision,
        )
        held_lock: HeldResourceLock | None = None
        lifecycle: SafeguardEvidenceLifecycleResult | None = None
        release_error: BaseException | None = None
        try:
            async with self._resource_lock.acquire_evidenced(acquisition_request) as active_lock:
                held_lock = active_lock
                lifecycle_or_result = await self._preparer.dispatch_while_held(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                    commitment=commitment,
                    held_lock=active_lock,
                    dispatch_port=dispatch_port,
                    correlation_id=correlation_id,
                )
                if isinstance(lifecycle_or_result, SafeguardCoordinatedDispatchResult):
                    return lifecycle_or_result
                lifecycle = lifecycle_or_result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if lifecycle is None:
                return await self._denial.deny(
                    action,
                    "safeguard lifecycle failed before terminal evidence: "
                    f"{type(exc).__name__}: {exc}",
                )
            release_error = exc

        if held_lock is None or lifecycle is None:
            return await self._denial.deny(action, "safeguard lifecycle lost its held-lock result")
        return await self._closure.finalize(
            action=action,
            held_lock=held_lock,
            lifecycle=lifecycle,
            release_error=release_error,
        )

    def _now(self) -> datetime:
        """Return the single aware clock reading the lifecycle is bound to."""

        return self._denial.now()


__all__ = [
    "ProductionSafeguardStore",
    "SafeguardCoordinatedDispatchResult",
    "SafeguardCoordinationDisposition",
    "SafeguardCoordinationError",
    "SafeguardLifecycleCoordinator",
    "SafeguardLifecycleCoordinatorConfig",
]
