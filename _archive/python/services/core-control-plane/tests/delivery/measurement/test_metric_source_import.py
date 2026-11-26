"""Protected production import binds typed sources to retained evidence, never booleans."""

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
from fdai.delivery.measurement.metric_source import (
    METRIC_SOURCE_PURPOSE,
    AttributedCostMetricSource,
    ChangeMetricSource,
    IncidentMetricSource,
    MetricSourceBatch,
    load_metric_source_batch,
    metric_source_batch_digest,
    metric_source_evidence_digest,
    metric_source_scope_digest,
)
from fdai.delivery.measurement.metric_source_import import import_metric_source_batch
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_cohort import CohortArm
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 9, 12, tzinfo=UTC)
REVISION = "a" * 40
WORKFLOW = ".github/workflows/cohort-treatment-export.yml"
SOURCE_ID = "treatment-lifecycle-source"
POLICY = load_cohort_claim_policy(ROOT / "config/sre-cohort-claim-policy.json")


def _context() -> CohortObservationImportContext:
    return CohortObservationImportContext(
        arm=CohortArm.TREATMENT,
        fdai_revision=REVISION,
        source_workflow_path=WORKFLOW,
        source_run_id=1,
        source_run_attempt=1,
        source_artifact_name="cohort-observations-treatment",
        imported_at=NOW,
    )


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
                        source_id=SOURCE_ID,
                        workflow_path=WORKFLOW,
                        metric_ids=(
                            "change_lead_time_seconds",
                            "cost_per_unit_usd",
                            "mttr_seconds",
                        ),
                        guard_ids=(),
                    ),
                ),
            ),
        ),
    )


def _source(kind: str = "incident", **updates: object):
    common = {
        "event_id": "event-1",
        "mode": "enforce",
        "source_record_id": "source-record-1",
        "source_refs": ("source:record-1",),
        "observed_at": NOW,
        "coverage": "complete",
        "synthetic": False,
    }
    if kind == "incident":
        return IncidentMetricSource.model_validate(
            {
                **common,
                "opened_at": NOW - timedelta(seconds=120),
                "resolved_at": NOW,
                **updates,
            }
        )
    if kind == "change":
        return ChangeMetricSource.model_validate(
            {
                **common,
                "change_requested_at": NOW - timedelta(seconds=300),
                "merged_at": NOW,
                **updates,
            }
        )
    return AttributedCostMetricSource.model_validate(
        {
            **common,
            "amount": 2.5,
            "currency": "USD",
            "period_start": NOW - timedelta(hours=1),
            "period_end": NOW,
            **updates,
        }
    )


def _batch(*sources) -> MetricSourceBatch:
    values = {"records": sorted(sources, key=lambda source: (source.kind, source.event_id))}
    return MetricSourceBatch.model_validate(
        {**values, "batch_digest": metric_source_batch_digest(**values)}
    )


def _admission(source) -> DecisionEvidenceAdmission:
    return DecisionEvidenceAdmission(
        receipt_digest="sha256:" + "1" * 64,
        verification_bundle_digest="sha256:" + "2" * 64,
        evidence_digest=metric_source_evidence_digest(source, source_id=SOURCE_ID),
        scope_digest=metric_source_scope_digest(source, source_id=SOURCE_ID),
        purpose_id=METRIC_SOURCE_PURPOSE,
        source_revision=REVISION,
        verified_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    ("kind", "metric_id", "value", "unit"),
    [
        ("incident", "mttr_seconds", 120, "seconds"),
        ("change", "change_lead_time_seconds", 300, "seconds"),
        ("spend", "attributed_cost_usd", 2.5, "USD"),
    ],
)
async def test_admitted_source_is_recorded_with_exact_semantics(
    monkeypatch, kind, metric_id, value, unit
) -> None:
    source = _source(kind)
    admission = _admission(source)
    admit = AsyncMock(return_value=admission)
    monkeypatch.setattr(StateStoreDecisionEvidenceAdmissionProvider, "admit", admit)
    store = InMemoryStateStore()
    report = await import_metric_source_batch(
        _batch(source), context=_context(), policy=_policy(), store=store
    )
    assert report["accepted_count"] == 1
    admit.assert_awaited_once_with(
        evidence_digest=admission.evidence_digest,
        scope_digest=admission.scope_digest,
        purpose_id=METRIC_SOURCE_PURPOSE,
        source_revision=REVISION,
    )
    row = store.audit_entries[0]["entry"]
    assert (row["metric_id"], row["value"], row["unit"]) == (metric_id, value, unit)
    assert row["source_id"] == SOURCE_ID
    assert row["event_id"] == source.event_id
    assert row["mode"] == "enforce"
    assert row["arm"] == "treatment"
    assert row["measurement_protocol_digest"] == POLICY.measurement_protocol_digest
    assert row["source_revision"] == REVISION
    assert admission.receipt_digest in row["source_refs"]
    assert row["execution_authority"] is False


async def test_missing_independent_evidence_never_emits_metric() -> None:
    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="independent exact-fact"):
        await import_metric_source_batch(
            _batch(_source()), context=_context(), policy=_policy(), store=store
        )
    assert not store.audit_entries


async def test_entire_batch_evidence_is_checked_before_recording(monkeypatch) -> None:
    spend = _source("spend")
    monkeypatch.setattr(
        StateStoreDecisionEvidenceAdmissionProvider,
        "admit",
        AsyncMock(side_effect=[_admission(spend), None]),
    )
    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="independent exact-fact"):
        await import_metric_source_batch(
            _batch(spend, _source()), context=_context(), policy=_policy(), store=store
        )
    assert not store.audit_entries


async def test_default_policy_stays_unavailable_until_real_exporter_binding_exists() -> None:
    store = InMemoryStateStore()
    with pytest.raises(CohortClaimPolicyError, match="not authorized"):
        await import_metric_source_batch(
            _batch(_source()), context=_context(), policy=POLICY, store=store
        )
    assert not store.audit_entries


async def test_baseline_never_becomes_live_telemetry() -> None:
    with pytest.raises(ValueError, match="treatment"):
        await import_metric_source_batch(
            _batch(_source()),
            context=dataclasses.replace(_context(), arm=CohortArm.BASELINE),
            policy=_policy(),
            store=InMemoryStateStore(),
        )


@pytest.mark.parametrize(
    ("kind", "updates"),
    [
        ("incident", {"verified": True}),
        ("incident", {"arm": "treatment"}),
        ("incident", {"measurement_protocol_digest": "sha256:" + "a" * 64}),
        ("incident", {"source_revision": REVISION}),
        ("incident", {"observed_at": NOW.replace(tzinfo=None)}),
        ("incident", {"opened_at": NOW + timedelta(seconds=1)}),
        ("change", {"merged_at": NOW - timedelta(hours=1)}),
        ("change", {"deployed_at": NOW}),
        ("spend", {"currency": "EUR"}),
        ("spend", {"estimated_savings": 2.5}),
        ("spend", {"amount": True}),
        ("spend", {"amount": float("nan")}),
        ("spend", {"coverage": True}),
    ],
)
def test_source_shape_rejects_unproven_semantics(kind, updates) -> None:
    with pytest.raises(ValidationError):
        _source(kind, **updates)


def test_source_artifact_loader_uses_sealed_typed_contract(monkeypatch) -> None:
    batch = _batch(_source())
    monkeypatch.setattr(Path, "open", lambda *_: io.BytesIO(batch.model_dump_json().encode()))
    assert load_metric_source_batch(Path("example-source.json")) == batch


def test_source_artifact_loader_rejects_duplicate_json_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        Path, "open", lambda *_: io.BytesIO(b'{"kind":"metric_sources","kind":"legacy"}')
    )
    with pytest.raises(ValueError, match="repeats"):
        load_metric_source_batch(Path("example-source.json"))


def test_source_artifact_loader_preserves_legacy_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        Path, "open", lambda *_: io.BytesIO(b'{"observations":[],"schema_version":"1.0.0"}')
    )
    assert load_metric_source_batch(Path("example-source.json")) is None


async def test_synthetic_or_incomplete_sources_remain_explicit(monkeypatch) -> None:
    source = _source("spend", synthetic=True, coverage="incomplete")
    monkeypatch.setattr(
        StateStoreDecisionEvidenceAdmissionProvider,
        "admit",
        AsyncMock(return_value=_admission(source)),
    )
    store = InMemoryStateStore()
    result = await import_metric_source_batch(
        _batch(source), context=_context(), policy=_policy(), store=store
    )
    assert result["unavailable_count"] == 1
    assert store.audit_entries[0]["entry"]["synthetic"] is True
    assert store.audit_entries[0]["entry"]["complete"] is False


async def test_production_cli_dispatches_source_artifacts_through_protected_import(
    monkeypatch,
) -> None:
    source_batch = _batch(_source())
    store = InMemoryStateStore()
    importer = AsyncMock(return_value={"accepted_count": 1})
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **_: store)
    monkeypatch.setattr(cli, "load_cohort_claim_policy", lambda _: _policy())
    monkeypatch.setattr(cli, "load_dashboard_comparison_receipt", lambda _: None)
    monkeypatch.setattr(cli, "load_metric_source_batch", lambda _: source_batch)
    monkeypatch.setattr(cli, "import_metric_source_batch", importer)
    args = argparse.Namespace(
        batch=Path("example-source.json"),
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
    assert importer.await_args.args == (source_batch,)
    assert importer.await_args.kwargs["store"] is store
    assert importer.await_args.kwargs["context"] == _context()
