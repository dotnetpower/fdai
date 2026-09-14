"""Resolve private requester identities and independently admitted workflow promotion records."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow import (
    ALERT_WORKFLOW_PROMOTION_PURPOSE,
    workflow_promotion_binding,
)
from fdai.shared.contracts.models import Mode, Workflow
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore


class MappedAlertRequesterReader:
    """Read the composition-owned current opaque-reference to private Entra OID map.

    Composition owns refreshing and revoking this current view. Only the resolved
    subject enters private replay context; the whole map is never copied. Public
    results carry no subject. Missing/revoked bindings return no subject, and malformed
    OIDs fail closed. Mapping membership establishes identity only, never permission.
    """

    def __init__(self, *, subjects: Mapping[str, str]) -> None:
        self._subjects = subjects

    async def resolve(self, *, requester_ref: str) -> str | None:
        """Resolve only this exact reference; no principal is accepted from an input body."""
        principal = self._subjects.get(requester_ref)
        if principal is None:
            return None
        if type(principal) is not str:
            raise AlertExecutionHeld("workflow_requester_mapping_invalid")
        try:
            parsed = UUID(principal)
        except ValueError as exc:
            raise AlertExecutionHeld("workflow_requester_mapping_invalid") from exc
        if str(parsed) != principal or parsed.int == 0:
            raise AlertExecutionHeld("workflow_requester_mapping_invalid")
        return principal


class StateStoreAlertWorkflowPromotionReader:
    """Admit an existing private reviewed-release record, never synthesize promotion.

    The exact key is ``alert-noise:workflow-promotion:<workflow.name>``. Its four keys
    are ``binding`` (the canonical ``workflow_promotion_binding``), ``evidence_digest``
    (the binding digest), ``receipt`` (DecisionCriticalEvidenceReceipt), and its exact
    ``receipt_digest``. An independent DecisionEvidenceAdmissionProvider must resolve
    that same receipt and exact evidence/scope/purpose/source revision. Missing,
    synthetic, conflicting, stale, malformed or replaced records remain shadow.
    Only a separate governed producer writes this record; there is no writer here.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        admission_provider: DecisionEvidenceAdmissionProvider | None,
        source_revision: str,
        clock: Callable[[], datetime],
    ) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}", source_revision) is None:
            raise ValueError("alert workflow promotion source revision MUST be explicit")
        self._store, self._admissions = store, admission_provider
        self._source_revision, self._clock = source_revision, clock

    async def read(
        self,
        *,
        workflow: Workflow,
        plan: AlertChangePlan,
        target_resource_id: str,
        now: datetime,
    ) -> DecisionEvidenceAdmission | None:
        """Return exact independently admitted release evidence, or no promotion."""
        try:
            async with asyncio.timeout(10):
                return await self._read(workflow, plan, target_resource_id, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - no failed promotion read can enable dispatch
            async with asyncio.timeout(5):
                await self._store.append_audit_entry(
                    {
                        "actor": "Forseti",
                        "action_kind": "alert_noise.workflow_promotion.held",
                        "workflow_ref": workflow.name,
                        "reason": "promotion_evidence_unavailable",
                        "error_type": type(exc).__name__,
                        "mode": Mode.SHADOW.value,
                        "recorded_at": self._clock().isoformat(),
                        "execution_authority": False,
                    }
                )
            return None

    async def _read(
        self,
        workflow: Workflow,
        plan: AlertChangePlan,
        target: str,
        now: datetime,
    ) -> DecisionEvidenceAdmission | None:
        key = "alert-noise:workflow-promotion:" + workflow.name
        raw = await self._store.read_state(key)
        if raw is None or self._admissions is None:
            return None
        binding = workflow_promotion_binding(
            workflow=workflow,
            plan=plan,
            target_resource_id=target,
            source_revision=self._source_revision,
        )
        evidence_digest = content_digest(binding)
        if (
            set(raw) != {"binding", "evidence_digest", "receipt_digest", "receipt"}
            or raw["binding"] != binding
            or content_digest(raw["binding"]) != evidence_digest
            or raw["evidence_digest"] != evidence_digest
        ):
            raise AlertExecutionHeld("workflow_promotion_binding_mismatch")
        receipt_raw = raw["receipt"]
        if (
            not isinstance(receipt_raw, Mapping)
            or receipt_raw.get("synthetic") is not False
            or receipt_raw.get("execution_authority") is not False
        ):
            raise AlertExecutionHeld("workflow_promotion_receipt_invalid")
        receipt = DecisionCriticalEvidenceReceipt.model_validate(receipt_raw)
        scope_digest = str(binding["scope_digest"])
        if (
            raw["receipt_digest"] != receipt.receipt_digest
            or receipt.evidence_digest != evidence_digest
            or receipt.scope_digest != scope_digest
            or receipt.purpose_id != ALERT_WORKFLOW_PROMOTION_PURPOSE
            or receipt.source_revision != self._source_revision
            or receipt.synthetic
            or receipt.completeness_basis_points != 10_000
            or receipt.conflict_status is not EvidenceConflictStatus.CLEAR
            or not receipt.recorded_at <= now < receipt.fresh_until
        ):
            raise AlertExecutionHeld("workflow_promotion_receipt_mismatch")
        admission = await self._admissions.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=ALERT_WORKFLOW_PROMOTION_PURPOSE,
            source_revision=self._source_revision,
        )
        if admission is None:
            return None
        # A concurrently replaced or revoked record cannot reuse an earlier admission.
        if await self._store.read_state(key) != raw:
            raise AlertExecutionHeld("workflow_promotion_changed")
        evaluated_at = self._clock()
        if (
            type(admission) is not DecisionEvidenceAdmission
            or admission.receipt_digest != receipt.receipt_digest
            or admission.execution_authority is not False
            or admission.promotion_authority is not False
            or not receipt.recorded_at <= admission.verified_at
            or admission.valid_until > receipt.fresh_until
            or not now <= evaluated_at < admission.valid_until
            or assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=evidence_digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=ALERT_WORKFLOW_PROMOTION_PURPOSE,
                expected_source_revision=self._source_revision,
                evaluated_at=evaluated_at,
            )
        ):
            raise AlertExecutionHeld("workflow_promotion_admission_mismatch")
        return admission
