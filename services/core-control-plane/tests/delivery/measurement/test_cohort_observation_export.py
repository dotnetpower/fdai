"""Tests for customer-agnostic per-arm cohort observation batch exporter and CLI."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    CohortClaimPolicyError,
    CohortExporterMeasureBinding,
    load_cohort_claim_policy,
)
from fdai.delivery.measurement.cohort_observation_export import (
    CohortObservationExportError,
    build_cohort_observation_batch,
    export_cohort_observation_batch,
    main,
)
from fdai.delivery.measurement.cohort_observation_import import (
    CohortObservationImportContext,
    import_cohort_observation_batch,
    load_cohort_observation_batch,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_cohort import CohortArm

CLUSTER_1 = "sha256:" + "1" * 64
CLUSTER_2 = "sha256:" + "2" * 64


def test_build_and_export_cohort_observation_batch_orders_and_seals_observations(
    tmp_path: Path,
) -> None:
    raw_input = {
        "observations": [
            {
                "kind": "metric",
                "metric_id": "mttr_seconds",
                "source_cluster_digest": CLUSTER_2,
                "observed_at": "2026-11-01T10:00:00Z",
                "value": 180.0,
            },
            {
                "kind": "guard",
                "guard_id": "unauthorized_execution_rate",
                "source_cluster_digest": CLUSTER_1,
                "observed_at": "2026-11-01T10:05:00Z",
                "observed_basis_points": 0,
                "breached": False,
            },
            {
                "kind": "metric",
                "metric_id": "auto_resolution_rate",
                "source_cluster_digest": CLUSTER_1,
                "observed_at": "2026-11-01T10:01:00Z",
                "value": 0.92,
            },
        ]
    }
    in_file = tmp_path / "raw-observations.json"
    out_file = tmp_path / "cohort-observation-batch.json"
    in_file.write_text(json.dumps(raw_input), encoding="utf-8")

    receipt = export_cohort_observation_batch(input_path=in_file, output_path=out_file)
    assert receipt.observation_count == 3
    assert receipt.metric_count == 2
    assert receipt.guard_count == 1
    assert receipt.distinct_metric_ids == ("auto_resolution_rate", "mttr_seconds")
    assert receipt.distinct_guard_ids == ("unauthorized_execution_rate",)
    assert receipt.execution_authority is False
    assert receipt.claim_eligibility_authority is False

    loaded = load_cohort_observation_batch(out_file)
    assert loaded.batch_digest == receipt.batch_digest
    # Canonical order places 'guard' before 'metric' lexicographically by kind, then measure_id.
    assert [item.kind for item in loaded.observations] == ["guard", "metric", "metric"]


def test_exporter_rejects_importer_owned_trust_fields_and_unknown_measures(
    tmp_path: Path,
) -> None:
    with pytest.raises(CohortObservationExportError, match="importer-owned trust fields"):
        build_cohort_observation_batch(
            [
                {
                    "kind": "metric",
                    "metric_id": "mttr_seconds",
                    "source_cluster_digest": CLUSTER_1,
                    "observed_at": "2026-11-01T10:00:00Z",
                    "value": 120.0,
                    "arm": "treatment",
                }
            ]
        )

    with pytest.raises(CohortObservationExportError, match="not in the governed cohort policy"):
        build_cohort_observation_batch(
            [
                {
                    "kind": "metric",
                    "metric_id": "invented_metric_id",
                    "source_cluster_digest": CLUSTER_1,
                    "observed_at": "2026-11-01T10:00:00Z",
                    "value": 1.0,
                }
            ]
        )

    bundle_with_trust = tmp_path / "forged-bundle.json"
    bundle_with_trust.write_text(
        json.dumps(
            {
                "arm": "baseline",
                "claim_eligible": True,
                "observations": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CohortObservationExportError, match="importer-owned trust fields"):
        export_cohort_observation_batch(
            input_path=bundle_with_trust,
            output_path=tmp_path / "out.json",
        )


def test_cli_main_emits_deterministic_json_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    in_file = tmp_path / "cli-in.json"
    out_file = tmp_path / "cli-out.json"
    in_file.write_text(
        json.dumps(
            [
                {
                    "kind": "guard",
                    "guard_id": "policy_violation_escape_rate",
                    "source_cluster_digest": CLUSTER_1,
                    "observed_at": "2026-11-01T11:00:00Z",
                    "observed_basis_points": 0,
                    "breached": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    rc = main(["--input", str(in_file), "--output", str(out_file)])
    assert rc == 0
    captured = json.loads(capsys.readouterr().out.strip())
    assert captured["observation_count"] == 1
    assert captured["guard_count"] == 1
    assert captured["execution_authority"] is False
    assert captured["claim_eligibility_authority"] is False


async def test_exported_batch_is_accepted_by_protected_importer_under_task_local_policy_fixture(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[5]
    base_policy = load_cohort_claim_policy(repo_root / COHORT_CLAIM_POLICY_PATH)
    workflow_path = ".github/workflows/cohort-treatment-export.yml"
    task_local_policy = dataclasses.replace(
        base_policy,
        allowed_exporter_workflow_paths=(
            ("baseline", ()),
            ("treatment", (workflow_path,)),
        ),
        exporter_measure_bindings=(
            ("baseline", ()),
            (
                "treatment",
                (
                    CohortExporterMeasureBinding(
                        source_id="treatment-sre-exporter",
                        workflow_path=workflow_path,
                        metric_ids=("auto_resolution_rate", "mttr_seconds"),
                        guard_ids=("unauthorized_execution_rate",),
                    ),
                ),
            ),
        ),
    )

    in_file = tmp_path / "raw-sre-observations.json"
    out_file = tmp_path / "cohort-observation-batch.json"
    in_file.write_text(
        json.dumps(
            {
                "observations": [
                    {
                        "kind": "metric",
                        "metric_id": "mttr_seconds",
                        "source_cluster_digest": CLUSTER_2,
                        "observed_at": "2026-11-01T10:00:00Z",
                        "value": 180.0,
                    },
                    {
                        "kind": "guard",
                        "guard_id": "unauthorized_execution_rate",
                        "source_cluster_digest": CLUSTER_1,
                        "observed_at": "2026-11-01T10:05:00Z",
                        "observed_basis_points": 0,
                        "breached": False,
                    },
                    {
                        "kind": "metric",
                        "metric_id": "auto_resolution_rate",
                        "source_cluster_digest": CLUSTER_1,
                        "observed_at": "2026-11-01T10:01:00Z",
                        "value": 0.92,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = main(["--input", str(in_file), "--output", str(out_file)])
    assert rc == 0

    sealed_batch = load_cohort_observation_batch(out_file)
    store = InMemoryStateStore()
    context = CohortObservationImportContext(
        arm=CohortArm.TREATMENT,
        fdai_revision="0123456789abcdef0123456789abcdef01234567",
        source_workflow_path=workflow_path,
        source_run_id=77,
        source_run_attempt=1,
        source_artifact_name="cohort-observations-treatment",
        imported_at=datetime(2026, 11, 1, 10, 10, tzinfo=UTC),
    )

    report = await import_cohort_observation_batch(
        sealed_batch,
        context=context,
        policy=task_local_policy,
        store=store,
    )
    assert report.arm is CohortArm.TREATMENT
    assert report.batch_digest == sealed_batch.batch_digest
    assert report.accepted_count == 3
    assert report.duplicate_count == 0
    assert report.metric_count == 2
    assert report.guard_count == 1
    assert report.to_mapping()["execution_authority"] is False
    assert report.to_mapping()["claim_eligibility_authority"] is False

    with pytest.raises(CohortClaimPolicyError, match="exporter allowlist is empty"):
        await import_cohort_observation_batch(
            sealed_batch,
            context=dataclasses.replace(context, arm=CohortArm.BASELINE),
            policy=task_local_policy,
            store=store,
        )
