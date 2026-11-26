"""Synthetic fixtures prove protected comparison publication, not live cohort readiness."""

from __future__ import annotations

import argparse
import dataclasses
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    CohortClaimPolicyError,
    CohortExporterMeasureBinding,
    load_cohort_claim_policy,
)
from fdai.delivery.measurement import cohort_observation_import_cli as cli
from fdai.delivery.measurement.cohort_observation_import import CohortObservationImportContext
from fdai.delivery.measurement.dashboard_comparison import (
    DashboardComparisonPublicationError,
    load_dashboard_comparison_receipt,
    publish_dashboard_comparison,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
    decision_evidence_state_key,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArm,
    CohortArtifactOrigin,
    baseline_treatment_cohort_receipt_digest,
    cohort_arm_fact_digest_values,
)
from fdai_service_contracts.dashboard_comparison import (
    DASHBOARD_COMPARISON_STATE_KEY,
    DashboardComparisonSnapshot,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest

ROOT = Path(__file__).resolve().parents[5]
POLICY = load_cohort_claim_policy(ROOT / "config/sre-cohort-claim-policy.json")
NOW = datetime(2026, 9, 12, tzinfo=UTC)
REVISION = "a" * 40
WORKFLOW = ".github/workflows/cohort-treatment-export.yml"
STATIC = "sha256:" + "f" * 64


def _policy():
    return dataclasses.replace(
        POLICY,
        allowed_exporter_workflow_paths=(("baseline", ()), ("treatment", (WORKFLOW,))),
        exporter_measure_bindings=(
            ("baseline", ()),
            (
                "treatment",
                (
                    CohortExporterMeasureBinding(
                        "example-cohort-source",
                        WORKFLOW,
                        POLICY.required_metric_ids,
                        POLICY.required_guard_ids,
                    ),
                ),
            ),
        ),
    )


def _context(now=NOW):
    return CohortObservationImportContext(
        CohortArm.TREATMENT,
        REVISION,
        WORKFLOW,
        1,
        1,
        "cohort-observations-treatment",
        now,
    )


def _evidence(digest, provenance, start, end):
    values = {
        "schema_version": "1.0.0",
        "authority_class": POLICY.allowed_authority_classes[0],
        "source_identity": POLICY.allowed_source_identities[0],
        "authentication_evidence_digest": STATIC,
        "scope_digest": POLICY.measurement_protocol_digest,
        "purpose_id": POLICY.purpose_id,
        "producer_id": POLICY.producer_id,
        "producer_version": POLICY.producer_version,
        "method_id": POLICY.method_id,
        "method_version": POLICY.method_version,
        "source_revision": REVISION,
        "evidence_digest": digest,
        "provenance_digest": provenance,
        "event_at": start,
        "evidence_cutoff": end,
        "recorded_at": end + timedelta(minutes=5),
        "fresh_until": end + timedelta(seconds=POLICY.freshness_ceiling_seconds),
        "freshness_policy_id": "sre-cohort-claim-freshness",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": POLICY.freshness_policy_digest,
        "freshness_ceiling_seconds": POLICY.freshness_ceiling_seconds,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": STATIC,
        "conflict_status": "clear",
        "conflict_evidence_digest": STATIC,
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    return DecisionCriticalEvidenceReceipt.model_validate(
        {**values, "receipt_digest": decision_critical_evidence_receipt_digest(**values)}
    )


def _receipt(offset=timedelta()):
    arms = {}
    for arm, hours, value in (("baseline", 3, 0.4), ("treatment", 1, 0.6)):
        end = NOW - timedelta(hours=hours) + offset
        provenance = content_digest({"arm": arm, "end": end.isoformat(), "kind": "provenance"})
        facts = {
            "arm": arm,
            "measurement_basis_kind": POLICY.measurement_basis_kind,
            "measurement_protocol_version": POLICY.measurement_protocol_version,
            "measurement_protocol_digest": POLICY.measurement_protocol_digest,
            "fdai_revision": REVISION,
            "report_digest": content_digest({"arm": arm, "end": end.isoformat(), "kind": "report"}),
            "provenance_digest": provenance,
            "sample_count": 30,
            "synthetic": False,
            "metrics_complete": True,
            "provenance_complete": True,
            "metrics": [
                {
                    "metric_id": metric,
                    "absolute_value": value,
                    "sample_size": 30,
                    "lower_bound": value * 0.8,
                    "upper_bound": value * 1.2,
                }
                for metric in POLICY.required_metric_ids
            ],
            "guards": [
                {
                    "guard_id": guard,
                    "observed_basis_points": 0,
                    "sample_size": 30,
                    "breached": False,
                }
                for guard in POLICY.required_guard_ids
            ],
        }
        arms[arm] = {
            **facts,
            "evidence_receipt": _evidence(
                cohort_arm_fact_digest_values(**facts),
                provenance,
                end - timedelta(hours=1),
                end,
            ),
        }
    values = {
        "schema_version": "1.0.0",
        "cohort_id": "synthetic-test-cohort",
        "measurement_basis_kind": POLICY.measurement_basis_kind,
        "measurement_protocol_version": POLICY.measurement_protocol_version,
        "measurement_protocol_digest": POLICY.measurement_protocol_digest,
        "fdai_revision": REVISION,
        **arms,
        "evidence_cutoff": NOW - timedelta(hours=1) + offset,
        "execution_authority": False,
    }
    return BaselineTreatmentCohortReceipt.model_validate(
        {**values, "receipt_digest": baseline_treatment_cohort_receipt_digest(**values)}
    )


async def _retain(store, envelope, minutes):
    subjects = expected_verification_subjects(
        authentication_evidence_digest=envelope.authentication_evidence_digest,
        evidence_digest=envelope.evidence_digest,
        completeness_evidence_digest=envelope.completeness_evidence_digest,
        conflict_evidence_digest=envelope.conflict_evidence_digest,
        freshness_policy_digest=envelope.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=envelope.receipt_digest,
            subject_digest=subject,
            proof_digest=content_digest({"kind": str(kind), "receipt": envelope.receipt_digest}),
            verifier_id="synthetic-test-verifier",
            verifier_version="1.0.0",
            trust_anchor_id="test:readback",
            issued_at=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=minutes),
        )
        for kind, subject in subjects.items()
    )
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=envelope.receipt_digest,
        verifier_id="synthetic-test-verifier",
        verifier_version="1.0.0",
        trust_anchor_id="test:readback",
        verified_at=NOW - timedelta(minutes=10),
        valid_until=NOW + timedelta(minutes=minutes),
        proofs=proofs,
    )
    admission = DecisionEvidenceAdmission(
        envelope.receipt_digest,
        bundle.bundle_digest,
        envelope.evidence_digest,
        envelope.scope_digest,
        envelope.purpose_id,
        envelope.source_revision,
        bundle.verified_at,
        bundle.valid_until,
    )
    await store.write_state(
        decision_evidence_state_key(
            evidence_digest=envelope.evidence_digest,
            scope_digest=envelope.scope_digest,
            purpose_id=envelope.purpose_id,
            source_revision=envelope.source_revision,
        ),
        decision_evidence_record_mapping(RetainedDecisionEvidence(envelope, bundle, admission)),
    )


async def _sources(store, receipt, *, include_cohort=True):
    await _retain(store, receipt.baseline.evidence_receipt, 20)
    await _retain(store, receipt.treatment.evidence_receipt, 10)
    cohort_envelope = _evidence(
        receipt.receipt_digest,
        content_digest({"cohort": receipt.receipt_digest}),
        receipt.baseline.evidence_receipt.event_at,
        receipt.evidence_cutoff,
    )
    if include_cohort:
        await _retain(store, cohort_envelope, 15)
    return cohort_envelope


async def _publish(receipt, store, **updates):
    values = {
        "context": _context(),
        "policy": _policy(),
        "store": store,
        "import_origin": CohortArtifactOrigin.GOVERNED_EXTERNAL,
        **updates,
    }
    return await publish_dashboard_comparison(receipt, **values)


async def test_actual_durable_admission_read_publishes_one_separate_snapshot():
    receipt = _receipt()
    store = InMemoryStateStore()
    envelope = await _sources(store, receipt)
    result = await _publish(receipt, store)
    snapshot = DashboardComparisonSnapshot.from_state(
        await store.read_state(DASHBOARD_COMPARISON_STATE_KEY), evaluated_at=NOW
    )
    assert result["accepted_count"] == 1
    assert snapshot.valid_until == NOW + timedelta(minutes=10)
    assert snapshot.cohort_admission_receipt_digest == envelope.receipt_digest
    assert snapshot.cohort_receipt_digest == receipt.receipt_digest
    assert snapshot.cohort_admission_receipt_digest != snapshot.cohort_receipt_digest
    assert snapshot.baseline.metrics == receipt.baseline.metrics
    assert snapshot.treatment.metrics == receipt.treatment.metrics
    assert snapshot.baseline.window_end < snapshot.treatment.window_end
    assert len(store.audit_entries) == 1
    assert store.audit_entries[0]["entry"]["execution_authority"] is False


async def test_replay_does_not_extend_publication_expiry_or_duplicate_audit():
    receipt = _receipt()
    store = InMemoryStateStore()
    await _sources(store, receipt)
    first = await _publish(receipt, store)
    second = await _publish(receipt, store, context=_context(NOW + timedelta(minutes=1)))
    assert second["publication_id"] == first["publication_id"]
    assert second["duplicate_count"] == 1
    assert len(store.audit_entries) == 1


async def test_older_receipt_cannot_overwrite_newer_context():
    old, new = _receipt(), _receipt(timedelta(minutes=10))
    store = InMemoryStateStore()
    await _sources(store, old)
    await _sources(store, new)
    await _publish(old, store)
    await _publish(new, store, context=_context(NOW + timedelta(minutes=1)))
    with pytest.raises(DashboardComparisonPublicationError, match="newer evidence"):
        await _publish(old, store, context=_context(NOW + timedelta(minutes=2)))
    state = await store.read_state(DASHBOARD_COMPARISON_STATE_KEY)
    assert state["revision"] == 2
    assert state["snapshot"]["cohort_receipt_digest"] == new.receipt_digest


async def test_complete_arm_admissions_without_cohort_admission_still_reject():
    receipt = _receipt()
    store = InMemoryStateStore()
    await _sources(store, receipt, include_cohort=False)
    with pytest.raises(DashboardComparisonPublicationError, match="not admitted"):
        await _publish(receipt, store)
    assert await store.read_state(DASHBOARD_COMPARISON_STATE_KEY) is None
    assert not store.audit_entries


async def test_expired_admission_cannot_publish():
    receipt = _receipt()
    store = InMemoryStateStore()
    await _sources(store, receipt)
    with pytest.raises(DashboardComparisonPublicationError, match="not admitted"):
        await _publish(receipt, store, context=_context(NOW + timedelta(minutes=11)))
    assert not store.audit_entries


@pytest.mark.parametrize(
    "updates",
    [
        {"import_origin": CohortArtifactOrigin.REPOSITORY},
        {"context": dataclasses.replace(_context(), arm=CohortArm.BASELINE)},
        {"context": dataclasses.replace(_context(), fdai_revision="b" * 40)},
    ],
)
async def test_artifact_cannot_choose_origin_arm_or_expected_revision(updates):
    receipt = _receipt()
    store = InMemoryStateStore()
    await _sources(store, receipt)
    with pytest.raises(DashboardComparisonPublicationError):
        await _publish(receipt, store, **updates)
    assert not store.audit_entries


async def test_default_empty_exporter_registry_stays_unavailable():
    with pytest.raises(CohortClaimPolicyError, match="not authorized"):
        await _publish(_receipt(), InMemoryStateStore(), policy=POLICY)


def test_receipt_loader_is_bounded_and_preserves_existing_formats(monkeypatch):
    receipt = _receipt()
    monkeypatch.setattr(Path, "open", lambda *_: io.BytesIO(receipt.model_dump_json().encode()))
    assert load_dashboard_comparison_receipt(Path("example.json")) == receipt
    monkeypatch.setattr(Path, "open", lambda *_: io.BytesIO(b'{"observations":[]}'))
    assert load_dashboard_comparison_receipt(Path("example.json")) is None


async def test_existing_protected_cli_has_executable_comparison_route(monkeypatch):
    receipt = _receipt()
    publisher = AsyncMock(return_value={"accepted_count": 1})
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    monkeypatch.setattr(cli, "load_cohort_claim_policy", lambda _: _policy())
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **_: InMemoryStateStore())
    monkeypatch.setattr(cli, "load_dashboard_comparison_receipt", lambda _: receipt)
    monkeypatch.setattr(cli, "publish_dashboard_comparison", publisher)
    args = argparse.Namespace(
        batch=Path("example.json"),
        policy=Path("example-policy.json"),
        arm="treatment",
        revision=REVISION,
        source_workflow_path=WORKFLOW,
        source_run_id=1,
        source_run_attempt=1,
        source_artifact_name="cohort-observations-treatment",
        imported_at=NOW.isoformat(),
    )
    assert await cli._run(args) == {"accepted_count": 1}
    assert publisher.await_args.args == (receipt,)
    assert publisher.await_args.kwargs["import_origin"] is CohortArtifactOrigin.GOVERNED_EXTERNAL
    assert publisher.await_args.kwargs["context"] == _context()
