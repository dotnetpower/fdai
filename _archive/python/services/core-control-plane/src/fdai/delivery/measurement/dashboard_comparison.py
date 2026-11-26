"""Publish a separate expiring dashboard comparison through protected cohort admission."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fdai.core.measurement.baseline_cohort_claim import (
    evaluate_admitted_cohort_claim,
    provider_cohort_admissions,
)
from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicy, CohortClaimPolicyError
from fdai.delivery.measurement.cohort_observation_import import CohortObservationImportContext
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
)
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArm,
    CohortArmReport,
    CohortArtifactOrigin,
)
from fdai_service_contracts.dashboard_comparison import (
    DASHBOARD_COMPARISON_ACTION_KIND,
    DASHBOARD_COMPARISON_STATE_KEY,
    DashboardComparisonArm,
    DashboardComparisonSnapshot,
    dashboard_comparison_id,
)

MAX_COMPARISON_RECEIPT_BYTES = 8 * 1024 * 1024


class DashboardComparisonPublicationError(ValueError):
    """A cohort is unadmitted, stale, conflicting, or from an untrusted import context."""


class _CohortArtifactAdmissionView:
    """Adapt an admitted envelope's evidence identity to the cohort evaluator.

    Durable admissions name the verification envelope in ``receipt_digest`` and
    the cohort artifact in ``evidence_digest``. The existing cohort evaluator names
    that artifact in both slots. Translate only the independently admitted cohort
    lookup, preserve arm identities, and retain the original envelope reference.
    """

    def __init__(self, provider: DecisionEvidenceAdmissionProvider, cohort_digest: str) -> None:
        self._provider = provider
        self._cohort_digest = cohort_digest
        self.cohort_envelope_receipt_digest: str | None = None

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        admission = await self._provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
        )
        if admission is None or evidence_digest != self._cohort_digest:
            return admission
        if admission.evidence_digest != self._cohort_digest:
            raise DashboardComparisonPublicationError("cohort admission evidence does not match")
        self.cohort_envelope_receipt_digest = admission.receipt_digest
        return replace(admission, receipt_digest=self._cohort_digest)


def load_dashboard_comparison_receipt(path: Path) -> BaselineTreatmentCohortReceipt | None:
    """Load a bounded cohort receipt, or defer to the existing observation formats."""

    with path.open("rb") as stream:
        payload = stream.read(MAX_COMPARISON_RECEIPT_BYTES + 1)
    if len(payload) > MAX_COMPARISON_RECEIPT_BYTES:
        raise ValueError("comparison receipt exceeds the 8 MiB limit")
    raw = json.loads(payload, object_pairs_hook=_unique_json_object)
    if not isinstance(raw, dict):
        raise ValueError("measurement artifact MUST be a JSON object")
    if "baseline" not in raw and "treatment" not in raw:
        return None
    return BaselineTreatmentCohortReceipt.model_validate(raw)


async def publish_dashboard_comparison(
    receipt: BaselineTreatmentCohortReceipt,
    *,
    context: CohortObservationImportContext,
    policy: CohortClaimPolicy,
    store: StateStore,
    import_origin: CohortArtifactOrigin,
) -> dict[str, object]:
    """Publish only a complete current cohort admitted through the protected caller.

    The repository policy and expected immutable revision come from trusted CLI
    context. No artifact may supply its origin, requirements, or admissions.
    Replays never extend expiry. Older evidence cannot replace a newer snapshot;
    concurrent replacement uses the same atomic StateStore revision/audit seam.
    """

    receipt = BaselineTreatmentCohortReceipt.model_validate(receipt.model_dump(mode="json"))
    if import_origin is not CohortArtifactOrigin.GOVERNED_EXTERNAL:
        raise DashboardComparisonPublicationError("comparison requires governed external import")
    if context.arm is not CohortArm.TREATMENT:
        raise DashboardComparisonPublicationError(
            "comparison publication requires treatment context"
        )
    if context.source_workflow_path not in policy.allowed_exporters(context.arm.value):
        raise CohortClaimPolicyError("comparison source workflow is not authorized")
    policy.exporter_binding(context.arm.value, context.source_workflow_path)
    for report in (receipt.baseline, receipt.treatment):
        window = report.evidence_receipt.evidence_cutoff - report.evidence_receipt.event_at
        if window.total_seconds() > policy.maximum_window_seconds:
            raise DashboardComparisonPublicationError("comparison evidence window exceeds policy")
    requirement = policy.requirement(expected_revision=context.fdai_revision)
    provider = _CohortArtifactAdmissionView(
        StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: context.imported_at),
        receipt.receipt_digest,
    )
    admissions = await provider_cohort_admissions(receipt, requirement, provider=provider)
    assessment = evaluate_admitted_cohort_claim(
        receipt,
        requirement,
        admissions=admissions,
        import_origin=import_origin,
        evaluated_at=context.imported_at,
    )
    if not assessment.claim_eligible:
        reasons = ",".join(reason.value for reason in assessment.rejection_reasons)
        raise DashboardComparisonPublicationError(f"comparison cohort is not admitted: {reasons}")
    envelope_ref = provider.cohort_envelope_receipt_digest
    if envelope_ref is None:
        raise DashboardComparisonPublicationError("comparison cohort admission envelope is missing")
    snapshot = _snapshot(
        receipt,
        policy=policy,
        published_at=context.imported_at,
        admissions=admissions,
        cohort_envelope_ref=envelope_ref,
    )
    return await _persist_snapshot(snapshot, context=context, store=store)


def _snapshot(
    receipt: BaselineTreatmentCohortReceipt,
    *,
    policy: CohortClaimPolicy,
    published_at: datetime,
    admissions: tuple[DecisionEvidenceAdmission, ...],
    cohort_envelope_ref: str,
) -> DashboardComparisonSnapshot:
    facts = {
        "cohort_id": receipt.cohort_id,
        "cohort_receipt_digest": receipt.receipt_digest,
        "cohort_admission_receipt_digest": cohort_envelope_ref,
        "measurement_protocol_version": receipt.measurement_protocol_version,
        "measurement_protocol_digest": receipt.measurement_protocol_digest,
        "fdai_revision": receipt.fdai_revision,
        "baseline": _arm(receipt.baseline, policy),
        "treatment": _arm(receipt.treatment, policy),
        "evidence_cutoff": receipt.evidence_cutoff,
        "published_at": published_at,
        "valid_until": min(
            *(admission.valid_until for admission in admissions),
            receipt.baseline.evidence_receipt.fresh_until,
            receipt.treatment.evidence_receipt.fresh_until,
        ),
        "admission_receipt_refs": tuple(
            sorted(
                {
                    cohort_envelope_ref,
                    receipt.baseline.evidence_receipt.receipt_digest,
                    receipt.treatment.evidence_receipt.receipt_digest,
                }
            )
        ),
        "verification_bundle_refs": tuple(
            sorted({admission.verification_bundle_digest for admission in admissions})
        ),
    }
    return DashboardComparisonSnapshot.model_validate(
        {**facts, "publication_id": dashboard_comparison_id(**facts)}
    )


def _arm(report: CohortArmReport, policy: CohortClaimPolicy) -> DashboardComparisonArm:
    return DashboardComparisonArm(
        arm=report.arm,
        sample_count=report.sample_count,
        metrics=tuple(
            item for item in report.metrics if item.metric_id in policy.required_metric_ids
        ),
        guards=tuple(item for item in report.guards if item.guard_id in policy.required_guard_ids),
        report_digest=report.report_digest,
        provenance_digest=report.provenance_digest,
        evidence_receipt_digest=report.evidence_receipt.receipt_digest,
        window_start=report.evidence_receipt.event_at,
        window_end=report.evidence_receipt.evidence_cutoff,
    )


async def _persist_snapshot(
    snapshot: DashboardComparisonSnapshot,
    *,
    context: CohortObservationImportContext,
    store: StateStore,
) -> dict[str, object]:
    current = await store.read_state(DASHBOARD_COMPARISON_STATE_KEY)
    revision = 0
    if current is not None:
        previous = DashboardComparisonSnapshot.model_validate(current.get("snapshot"))
        # Expired snapshots still provide the monotonic evidence watermark.
        DashboardComparisonSnapshot.from_state(current, evaluated_at=previous.published_at)
        revision = current["revision"]
        if previous.cohort_receipt_digest == snapshot.cohort_receipt_digest:
            return _result(previous, created=False)
        if (
            snapshot.published_at < previous.published_at
            or snapshot.evidence_cutoff <= previous.evidence_cutoff
            or snapshot.baseline.window_end < previous.baseline.window_end
            or snapshot.treatment.window_end < previous.treatment.window_end
        ):
            raise DashboardComparisonPublicationError("comparison would replace newer evidence")
    state = {"revision": revision + 1, "snapshot": snapshot.model_dump(mode="json")}
    audit = {
        "action_kind": DASHBOARD_COMPARISON_ACTION_KIND,
        "actor": "fdai.measurement",
        "mode": "shadow",
        "idempotency_key": f"dashboard-comparison:{snapshot.publication_id}",
        "publication_id": snapshot.publication_id,
        "cohort_receipt_digest": snapshot.cohort_receipt_digest,
        "recorded_at": snapshot.published_at.isoformat(),
        "valid_until": snapshot.valid_until.isoformat(),
        "source_workflow_path": context.source_workflow_path,
        "source_run_id": context.source_run_id,
        "source_run_attempt": context.source_run_attempt,
        "source_artifact_name": context.source_artifact_name,
        "execution_authority": False,
        "promotion_authority": False,
        "snapshot": snapshot.model_dump(mode="json"),
    }
    if current is None:
        created = await store.write_state_with_audit_if_absent(
            DASHBOARD_COMPARISON_STATE_KEY, state, audit
        )
    else:
        created = await store.compare_and_set_state_with_audit(
            DASHBOARD_COMPARISON_STATE_KEY,
            state,
            expected_revision=revision,
            audit_entry=audit,
        )
    if not created:
        winner = await store.read_state(DASHBOARD_COMPARISON_STATE_KEY)
        if winner is not None:
            published = DashboardComparisonSnapshot.from_state(
                winner, evaluated_at=context.imported_at
            )
            if published.cohort_receipt_digest == snapshot.cohort_receipt_digest:
                return _result(published, created=False)
        raise DashboardComparisonPublicationError("comparison publication lost a concurrent update")
    return _result(snapshot, created=True)


def _result(snapshot: DashboardComparisonSnapshot, *, created: bool) -> dict[str, object]:
    return {
        "publication_id": snapshot.publication_id,
        "accepted_count": int(created),
        "duplicate_count": int(not created),
        "valid_until": snapshot.valid_until.isoformat(),
        "execution_authority": False,
        "claim_eligibility_authority": False,
    }


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("comparison receipt repeats a JSON key")
        result[key] = value
    return result
