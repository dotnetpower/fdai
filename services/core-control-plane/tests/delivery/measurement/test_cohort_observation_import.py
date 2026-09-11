"""Trusted cohort observation import tests."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    CohortClaimPolicyError,
    load_cohort_claim_policy,
)
from fdai.delivery.measurement.cohort_observation_import import (
    MAX_COHORT_OBSERVATION_BATCH_BYTES,
    MAX_COHORT_OBSERVATIONS,
    CohortObservationBatch,
    CohortObservationConflictError,
    CohortObservationImportContext,
    CohortObservationImportReport,
    _record_import_summary,
    cohort_observation_batch_digest,
    import_cohort_observation_batch,
    load_cohort_observation_batch,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_cohort import CohortArm
from fdai_service_contracts.ontology_query import content_digest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY = load_cohort_claim_policy(REPO_ROOT / COHORT_CLAIM_POLICY_PATH)
REVISION = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 9, 11, tzinfo=UTC)
SOURCE_WORKFLOW = ".github/workflows/cohort-treatment-export.yml"
OTHER_SOURCE_WORKFLOW = ".github/workflows/cohort-treatment-export-secondary.yml"
ARTIFACT_NAME = "cohort-observations-treatment"


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _batch(*, value: float = 1.0, observed_at: datetime = NOW) -> CohortObservationBatch:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "observations": [
            {
                "kind": "guard",
                "guard_id": "policy_violation_escape_rate",
                "source_cluster_digest": _digest("1"),
                "observed_at": observed_at.isoformat(),
                "observed_basis_points": 0,
                "breached": False,
            },
            {
                "kind": "metric",
                "metric_id": "auto_resolution_rate",
                "source_cluster_digest": _digest("1"),
                "observed_at": observed_at.isoformat(),
                "value": value,
            },
        ],
    }
    values["batch_digest"] = cohort_observation_batch_digest(**values)
    return CohortObservationBatch.model_validate(values)


def _context(**updates: object) -> CohortObservationImportContext:
    values: dict[str, object] = {
        "arm": CohortArm.TREATMENT,
        "fdai_revision": REVISION,
        "source_workflow_path": SOURCE_WORKFLOW,
        "source_run_id": 123,
        "source_run_attempt": 1,
        "source_artifact_name": ARTIFACT_NAME,
        "imported_at": NOW,
    }
    values.update(updates)
    return CohortObservationImportContext(**values)  # type: ignore[arg-type]


def _authorized_policy():
    return dataclasses.replace(
        POLICY,
        allowed_exporter_workflow_paths=(
            ("baseline", ()),
            ("treatment", (SOURCE_WORKFLOW,)),
        ),
    )


async def test_authorized_batch_is_persisted_without_claim_authority() -> None:
    store = InMemoryStateStore()

    report = await import_cohort_observation_batch(
        _batch(),
        context=_context(),
        policy=_authorized_policy(),
        store=store,
    )

    assert report.accepted_count == 2
    assert report.duplicate_count == 0
    assert report.to_mapping()["claim_eligibility_authority"] is False
    entries = [row["entry"] for row in store.audit_entries]
    metric = next(row for row in entries if row["action_kind"] == "measurement.cohort.metric.v1")
    guard = next(row for row in entries if row["action_kind"] == "measurement.cohort.guard.v1")
    assert metric["arm"] == "treatment"
    assert metric["fdai_revision"] == REVISION
    assert metric["measurement_protocol_digest"] == POLICY.measurement_protocol_digest
    assert metric["value"] == 1.0
    assert guard["breached"] is False
    assert metric["synthetic"] is False
    assert metric["execution_authority"] is False
    assert metric["claim_eligibility_authority"] is False
    assert metric["import_provenance"] == {
        "batch_digest": _batch().batch_digest,
        "source_workflow_path": SOURCE_WORKFLOW,
        "source_run_id": 123,
        "source_run_attempt": 1,
        "source_artifact_name": ARTIFACT_NAME,
    }


async def test_reimport_is_idempotent_and_reports_duplicates() -> None:
    store = InMemoryStateStore()
    batch = _batch()
    context = _context()
    policy = _authorized_policy()

    await import_cohort_observation_batch(
        batch,
        context=context,
        policy=policy,
        store=store,
    )
    replay = await import_cohort_observation_batch(
        batch,
        context=context,
        policy=policy,
        store=store,
    )

    assert replay.accepted_count == 0
    assert replay.duplicate_count == 2
    assert len(tuple(store.audit_entries)) == 3


async def test_same_measure_cluster_with_changed_value_conflicts() -> None:
    store = InMemoryStateStore()
    context = _context()
    policy = _authorized_policy()
    await import_cohort_observation_batch(
        _batch(value=0.0),
        context=context,
        policy=policy,
        store=store,
    )

    with pytest.raises(CohortObservationConflictError, match="different content"):
        await import_cohort_observation_batch(
            _batch(value=1.0),
            context=context,
            policy=policy,
            store=store,
        )


async def test_same_measure_cluster_from_another_exporter_conflicts() -> None:
    store = InMemoryStateStore()
    policy = dataclasses.replace(
        _authorized_policy(),
        allowed_exporter_workflow_paths=(
            ("baseline", ()),
            ("treatment", (OTHER_SOURCE_WORKFLOW, SOURCE_WORKFLOW)),
        ),
    )
    await import_cohort_observation_batch(
        _batch(),
        context=_context(),
        policy=policy,
        store=store,
    )

    with pytest.raises(CohortObservationConflictError, match="different content"):
        await import_cohort_observation_batch(
            _batch(),
            context=_context(source_workflow_path=OTHER_SOURCE_WORKFLOW),
            policy=policy,
            store=store,
        )


async def test_import_summary_rejects_conflicting_stored_content() -> None:
    store = InMemoryStateStore()
    report = CohortObservationImportReport(
        arm=CohortArm.TREATMENT,
        batch_digest=_batch().batch_digest,
        accepted_count=2,
        duplicate_count=0,
        metric_count=1,
        guard_count=1,
    )
    context = _context()
    policy = _authorized_policy()
    identity = content_digest(
        {
            "arm": context.arm.value,
            "batch_digest": report.batch_digest,
            "fdai_revision": context.fdai_revision,
            "measurement_protocol_digest": policy.measurement_protocol_digest,
        }
    )
    key = f"measurement:cohort:import:{identity.removeprefix('sha256:')}"
    await store.write_state(key, {"batch_digest": _digest("f")})

    with pytest.raises(CohortObservationConflictError, match="summary identity"):
        await _record_import_summary(
            report,
            context=context,
            policy=policy,
            store=store,
        )


async def test_empty_or_wrong_arm_allowlist_fails_before_writes() -> None:
    store = InMemoryStateStore()

    with pytest.raises(CohortClaimPolicyError, match="allowlist is empty"):
        await import_cohort_observation_batch(
            _batch(),
            context=_context(),
            policy=POLICY,
            store=store,
        )

    assert tuple(store.audit_entries) == ()


async def test_observations_outside_the_frozen_window_are_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        await import_cohort_observation_batch(
            _batch(observed_at=NOW - timedelta(days=91)),
            context=_context(),
            policy=_authorized_policy(),
            store=InMemoryStateStore(),
        )


def test_batch_cannot_declare_importer_owned_trust_fields() -> None:
    payload = _batch().model_dump(mode="json")
    payload["arm"] = "treatment"

    with pytest.raises(ValidationError):
        CohortObservationBatch.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("arm", "treatment", "CohortArm"),
        ("source_run_id", True, "run identity"),
        ("source_run_attempt", "1", "run identity"),
        ("source_workflow_path", 1, "workflow path"),
        ("source_artifact_name", 1, "artifact name"),
        ("imported_at", "2026-09-11T00:00:00Z", "datetime"),
    ],
)
def test_trusted_import_context_uses_strict_runtime_types(
    field: str,
    value: object,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _context(**{field: value})


@pytest.mark.parametrize("value", [True, False, "1"])
def test_metric_value_must_be_a_strict_json_number(value: object) -> None:
    payload = _batch().model_dump(mode="json")
    payload["observations"][1]["value"] = value

    with pytest.raises(ValidationError):
        CohortObservationBatch.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("breached", 0),
        ("breached", "false"),
        ("observed_basis_points", False),
        ("observed_basis_points", "0"),
    ],
)
def test_guard_values_must_use_strict_json_types(field: str, value: object) -> None:
    payload = _batch().model_dump(mode="json")
    payload["observations"][0][field] = value

    with pytest.raises(ValidationError):
        CohortObservationBatch.model_validate(payload)


def test_batch_digest_and_canonical_order_are_enforced() -> None:
    payload = _batch().model_dump(mode="json")
    payload["batch_digest"] = _digest("f")
    with pytest.raises(ValidationError, match="digest does not match"):
        CohortObservationBatch.model_validate(payload)

    payload = _batch().model_dump(mode="json")
    payload["observations"] = list(reversed(payload["observations"]))
    with pytest.raises(ValidationError, match="canonical order"):
        CohortObservationBatch.model_validate(payload)


def test_load_rejects_an_oversized_batch(tmp_path: Path) -> None:
    path = tmp_path / "cohort-observation-batch.json"
    path.write_bytes(b"{" + b" " * MAX_COHORT_OBSERVATION_BATCH_BYTES + b"}")

    with pytest.raises(ValueError, match="8 MiB limit"):
        load_cohort_observation_batch(path)


def test_batch_rejects_more_than_the_bounded_observation_count() -> None:
    observations = [
        {
            "kind": "metric",
            "metric_id": "auto_resolution_rate",
            "source_cluster_digest": f"sha256:{index:064x}",
            "observed_at": NOW.isoformat(),
            "value": 1.0,
        }
        for index in range(MAX_COHORT_OBSERVATIONS + 1)
    ]

    with pytest.raises(ValidationError):
        CohortObservationBatch.model_validate(
            {
                "schema_version": "1.0.0",
                "observations": observations,
                "batch_digest": _digest("f"),
            }
        )


def test_load_round_trips_a_valid_batch(tmp_path: Path) -> None:
    path = tmp_path / "cohort-observation-batch.json"
    path.write_text(json.dumps(_batch().model_dump(mode="json")), encoding="utf-8")

    assert load_cohort_observation_batch(path) == _batch()


def test_load_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "cohort-observation-batch.json"
    path.write_text(
        '{"schema_version":"1.0.0","schema_version":"2.0.0","observations":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="repeats JSON key"):
        load_cohort_observation_batch(path)
