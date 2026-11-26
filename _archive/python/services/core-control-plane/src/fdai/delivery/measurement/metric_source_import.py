"""Protected lifecycle/spend ingestion, bound to exact retained independent evidence."""

from __future__ import annotations

from datetime import timedelta

from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicy, CohortClaimPolicyError
from fdai.core.measurement.metric_recorder import MetricObservationRecorder
from fdai.core.measurement.mttr import compute_mttr
from fdai.delivery.measurement.cohort_observation_import import CohortObservationImportContext
from fdai.delivery.measurement.metric_source import (
    METRIC_SOURCE_PURPOSE,
    AttributedCostMetricSource,
    ChangeMetricSource,
    IncidentMetricSource,
    MetricSourceBatch,
    metric_source_evidence_digest,
    metric_source_scope_digest,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.baseline_cohort import CohortArm
from fdai_service_contracts.metric_observation import (
    MetricObservationV1,
    metric_observation_id,
)
from fdai_service_contracts.ontology_query import content_digest


async def import_metric_source_batch(
    batch: MetricSourceBatch,
    *,
    context: CohortObservationImportContext,
    policy: CohortClaimPolicy,
    store: StateStore,
) -> dict[str, object]:
    """Record live metric facts through the existing protected exporter boundary.

    The source artifact cannot choose its exporter, revision, arm, or admission.
    The retained proof must independently verify the exact lifecycle/spend facts
    under ``measurement-metric-source``. Baseline imports are never live telemetry.
    Missing bindings or evidence reject the batch without manufacturing observations.
    These imports do not create or admit a baseline/treatment comparison claim.
    """

    batch = MetricSourceBatch.model_validate(batch.model_dump(mode="json"))
    if context.arm is not CohortArm.TREATMENT:
        raise ValueError("live metric source imports require the treatment arm")
    if context.source_workflow_path not in policy.allowed_exporters(context.arm.value):
        raise CohortClaimPolicyError("metric source workflow is not authorized")
    binding = policy.exporter_binding(context.arm.value, context.source_workflow_path)
    admissions = StateStoreDecisionEvidenceAdmissionProvider(
        store=store, clock=lambda: context.imported_at
    )
    earliest = context.imported_at - timedelta(seconds=policy.maximum_window_seconds)
    observations: list[MetricObservationV1] = []
    for source in batch.records:
        if not earliest <= source.observed_at <= context.imported_at:
            raise ValueError("metric source falls outside the frozen import window")
        if isinstance(source, IncidentMetricSource):
            metric_id = "mttr_seconds"
            policy_metric_id = metric_id
            measured = compute_mttr((source,)).mean_seconds
            if measured is None:
                raise ValueError("incident source has no valid resolution duration")
            value = measured
            unit = "seconds"
        elif isinstance(source, ChangeMetricSource):
            metric_id = "change_lead_time_seconds"
            policy_metric_id = metric_id
            value = (source.merged_at - source.change_requested_at).total_seconds()
            unit = "seconds"
        elif isinstance(source, AttributedCostMetricSource):
            metric_id = "attributed_cost_usd"
            # Reuse the approved cost exporter, not its aggregate ratio. This
            # source is independently admitted actual spend for exactly one event.
            policy_metric_id = "cost_per_unit_usd"
            value = source.amount
            unit = "USD"
        else:
            raise ValueError("unsupported metric source")
        if not binding.allows_metric(policy_metric_id):
            raise CohortClaimPolicyError("exporter is not authorized for this metric source")
        admission = await admissions.admit(
            evidence_digest=metric_source_evidence_digest(source, source_id=binding.source_id),
            scope_digest=metric_source_scope_digest(source, source_id=binding.source_id),
            purpose_id=METRIC_SOURCE_PURPOSE,
            source_revision=context.fdai_revision,
        )
        if admission is None:
            raise ValueError("metric source lacks current independent exact-fact evidence")
        values: dict[str, object] = {
            "metric_id": metric_id,
            "mode": source.mode,
            "arm": context.arm.value,
            "measurement_protocol_digest": policy.measurement_protocol_digest,
            "source_revision": context.fdai_revision,
            "event_id": source.event_id,
            "source_id": binding.source_id,
            "source_record_id": source.source_record_id,
            "source_refs": tuple(
                sorted(
                    {
                        *source.source_refs,
                        admission.receipt_digest,
                        admission.verification_bundle_digest,
                    }
                )
            ),
            "value": value,
            "unit": unit,
            "observed_at": source.observed_at,
            "recorded_at": context.imported_at,
            "synthetic": source.synthetic,
            "complete": source.coverage == "complete",
            "supersedes_observation_id": source.supersedes_observation_id,
        }
        observations.append(
            MetricObservationV1.model_validate(
                {**values, "observation_id": metric_observation_id(**values)}
            )
        )
    recorder = MetricObservationRecorder(store)
    accepted = 0
    for observation in observations:
        accepted += int(await recorder.record(observation))
    await _record_import_provenance(
        batch, context=context, source_id=binding.source_id, store=store
    )
    return {
        "batch_digest": batch.batch_digest,
        "accepted_count": accepted,
        "duplicate_count": len(observations) - accepted,
        "unavailable_count": sum(item.synthetic or not item.complete for item in observations),
        "execution_authority": False,
        "claim_eligibility_authority": False,
    }


async def _record_import_provenance(
    batch: MetricSourceBatch,
    *,
    context: CohortObservationImportContext,
    source_id: str,
    store: StateStore,
) -> None:
    """Retain source-run custody separately so retry times cannot alter metric identity."""

    provenance = {
        "batch_digest": batch.batch_digest,
        "source_id": source_id,
        "fdai_revision": context.fdai_revision,
        "source_workflow_path": context.source_workflow_path,
        "source_run_id": context.source_run_id,
        "source_run_attempt": context.source_run_attempt,
        "source_artifact_name": context.source_artifact_name,
        "record_count": len(batch.records),
    }
    key = f"measurement:metric-import:{content_digest(provenance).removeprefix('sha256:')}"
    created = await store.write_state_with_audit_if_absent(
        key,
        provenance,
        {
            **provenance,
            "action_kind": "measurement.metric.import.v1",
            "actor": "fdai.measurement",
            "mode": "shadow",
            "idempotency_key": key,
            "recorded_at": context.imported_at.isoformat(),
            "execution_authority": False,
            "claim_eligibility_authority": False,
        },
    )
    if not created and await store.read_state(key) != provenance:
        raise ValueError("metric source import provenance conflicts with retained state")
