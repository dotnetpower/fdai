"""Gate manual publication on real locks AND independently admitted writer exclusion.

No shipped lock proves exclusion of portal, IaC, automation or authority-state writers.
The external mechanism must already enforce the exact exclusion window, protected identity,
authority revisions and release constraint. An independently verified ledger must attest that
truth. This adapter neither provisions that mechanism nor manufactures its verification.
Without it, even a production-eligible PostgreSQL lock leaves publication unavailable.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime

from fdai_service_contracts.alert_noise import NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan

from fdai.core.detection.alert_noise.execution import (
    RESTORE_ACTION,
    AlertAuthorityLease,
    AlertExecutionHeld,
    alert_execution_key,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_authority import (
    StateStoreAlertAuthorityReader,
    StateStoreAlertRecoveryAuthorityReader,
)
from fdai.delivery.alert_noise_evidence import (
    AdmittedAlertRecord,
    StateStoreAlertEvaluationReader,
    alert_scope_digest,
)
from fdai.delivery.alert_noise_fence_lease import _AlertAuthorityLease
from fdai.delivery.alert_noise_fence_records import (
    ALERT_WRITER_EXCLUSIVITY_PURPOSE as ALERT_WRITER_EXCLUSIVITY_PURPOSE,
)
from fdai.delivery.alert_noise_fence_records import (
    AlertLockTrust as AlertLockTrust,
)
from fdai.delivery.alert_noise_fence_records import (
    _WriterExclusion as _WriterExclusion,
)
from fdai.delivery.alert_noise_fence_records import (
    alert_writer_binding as alert_writer_binding,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    decision_evidence_state_key,
    parse_decision_evidence_record,
)
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.remediation_pr import RemediationPr
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    HeldResourceLock,
    HeldResourceLockLifecycle,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
    require_evidence_resource_lock,
)
from fdai.shared.providers.state_store import StateStore


class StateStoreAlertAuthorityFence:
    """Hold all secondary evidenced locks and verify a separately governed exclusion record.

    The writer key is alert-noise:writer-exclusivity:<full Action digest>; payload uses
    _WriterExclusion's closed fields. Its dispatch_receipt_digest pins ALL admitted authority
    revisions in the separate dispatch proof. The external mechanism must protect those
    revisions as well as provider dependencies and the exact publisher repository through
    commit. A record saying a role can write is not an exclusion attestation.
    The DE ledger must be retained in store under the configured verification trust anchor.
    production=False is only for explicit no-network unit fixtures, never a runtime fallback.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        admissions: DecisionEvidenceAdmissionProvider | None,
        lock: EvidenceResourceLock | None,
        lock_trust: AlertLockTrust,
        verification_trust_anchor_id: str,
        authority: StateStoreAlertAuthorityReader | None,
        policy: NoisePolicy,
        scope_ref: str,
        tenant_ref: str,
        repository_ref: str,
        repository_revision: str,
        writer_ref: str,
        source_revision: str,
        clock: Callable[[], datetime],
        production: bool = True,
        recovery: StateStoreAlertRecoveryAuthorityReader | None = None,
        evaluations: StateStoreAlertEvaluationReader | None = None,
    ) -> None:
        """Bind exact existing sources; no constructor argument grants external writer exclusion."""
        self._scope = alert_scope_digest(tenant_ref=tenant_ref, scope_ref=scope_ref)
        if (
            any(
                re.fullmatch(r"commit:[a-f0-9]{40}(?:[a-f0-9]{24})?", value) is None
                for value in (source_revision, repository_revision)
            )
            or re.fullmatch(r"[a-z][a-z0-9_.:-]{0,159}", repository_ref) is None
            or re.fullmatch(r"principal:[a-f0-9]{64}", writer_ref) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}", verification_trust_anchor_id)
            is None
            or type(production) is not bool
        ):
            raise ValueError(
                "alert fence requires exact source, repository, writer and trust bindings"
            )
        self._store, self._admissions, self._lock, self._trust = store, admissions, lock, lock_trust
        self._anchor, self._authority, self._recovery = (
            verification_trust_anchor_id,
            authority,
            recovery,
        )
        self._policy, self._evaluations = NoisePolicy.model_validate(policy), evaluations
        self._repository, self._repository_revision = repository_ref, repository_revision
        self._writer, self._revision, self._clock, self._production = (
            writer_ref,
            source_revision,
            clock,
            production,
        )

    @asynccontextmanager
    async def hold(
        self, *, action: Action, plan: AlertChangePlan, pr: RemediationPr
    ) -> AsyncIterator[AlertAuthorityLease]:
        """Acquire sorted namespaced dependencies; no verified exclusion means no yielded lease."""
        handles: list[HeldResourceLock] = []
        try:
            action = Action.model_validate(action.model_dump(mode="python"))
            plan = AlertChangePlan.model_validate(plan)
            self._require_inputs(action, plan, pr)
            provider = require_evidence_resource_lock(self._lock, production=self._production)
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(15):
                    for ref in sorted(plan.lock_refs):
                        request = ResourceLockAcquisitionRequest.create(
                            target_ref="alert-noise-exclusive:" + ref,
                            action_digest=full_action_digest(action),
                            attempt=action.workflow_action.attempt if action.workflow_action else 1,
                            producer_id="alert-noise-authority-fence",
                            producer_version="1.0.0",
                            source_revision=self._revision,
                        )
                        held = await stack.enter_async_context(provider.acquire_evidenced(request))
                        handles.append(held)
                        if held.acquisition_request != request:
                            raise AlertExecutionHeld("alert_exclusive_lock_request_mismatch")
                        HeldResourceLockLifecycle(request, held.acquisition_receipt)
                    lease = _AlertAuthorityLease(self, action, plan, pr, tuple(handles))
                    await lease._initialize()
                try:
                    yield lease
                finally:
                    lease._proofs = ()
                    lease._active = False
            for held in handles:
                release = held.release_receipt
                if (
                    release is None
                    or release.state is not ResourceLockReleaseState.RELEASED
                    or release.acquisition_receipt != held.acquisition_receipt
                ):
                    raise AlertExecutionHeld("alert_exclusive_lock_release_unknown")
        except AlertExecutionHeld:
            raise
        except Exception:
            raise AlertExecutionHeld("alert_exclusive_writer_unavailable") from None

    def _require_inputs(self, action: Action, plan: AlertChangePlan, pr: RemediationPr) -> None:
        if (
            alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref) != self._scope
            or action.mode is not Mode.ENFORCE
            or pr.mode is not Mode.ENFORCE
            or action.action_type not in {plan.action_type, RESTORE_ACTION}
            or action.executor_identity_ref != self._writer
            or action.workflow_action is None
            or action.target_resource_ref not in plan.lock_refs
            or action.params != {"plan_digest": digest_record(plan)[7:]}
            or action.idempotency_key
            != alert_execution_key(action.action_type, digest_record(plan))
            or pr.action_id != action.action_id
            or pr.idempotency_key != action.idempotency_key
            or not {"enforce", "hil", "require-manual-merge"}.issubset(pr.labels)
            or pr.metadata.get("executor_identity_ref") != self._writer
            or pr.metadata.get("action_type") != action.action_type
            or pr.metadata.get("plan_digest") != digest_record(plan)
            or any(
                re.fullmatch(r"sha256:[a-f0-9]{64}", pr.metadata.get(name, "")) is None
                for name in ("source_digest", "result_digest")
            )
        ):
            raise AlertExecutionHeld("alert_fence_binding_mismatch")

    async def _require_anchor(self, proof: AdmittedAlertRecord) -> None:
        """Resolve the real retained five-proof bundle, not a trust-anchor label in a payload."""
        admission = proof.admission
        key = decision_evidence_state_key(
            evidence_digest=admission.evidence_digest,
            scope_digest=admission.scope_digest,
            purpose_id=admission.purpose_id,
            source_revision=admission.source_revision,
        )
        raw = await self._store.read_state(key)
        if raw is None:
            raise AlertExecutionHeld("alert_verification_ledger_missing")
        retained = parse_decision_evidence_record(raw)
        if (
            retained.receipt.receipt_digest != proof.receipt_digest
            or retained.admission != admission
            or retained.verification_bundle.trust_anchor_id != self._anchor
        ):
            raise AlertExecutionHeld("alert_verification_anchor_mismatch")
