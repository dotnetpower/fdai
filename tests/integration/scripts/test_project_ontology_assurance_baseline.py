from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.automation.project_ontology_assurance_baseline import (
    BaselineProjectionError,
    project_repository_safe_baseline,
)

SOURCE_REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _passing_artifact() -> dict[str, Any]:
    results = [
        {
            "question_id": f"en-inventory_listing-{index}",
            "locale": "en" if index <= 50 else "ko",
            "operation": "inventory_listing",
            "disposition": "answered",
            "reason_code": "semantic_answer_verified",
            "semantic_route": "verified_query_plan",
            "request_id": f"request-{index}",
            "projection_id": f"projection-{index}",
            "ontology_release_digest": DIGEST,
            "principal_manifest_digest": DIGEST,
            "plan_digest": DIGEST,
            "execution_receipt_digest": DIGEST,
            "checks_completed": 1,
            "checks_total": 1,
            "evidence_ref_count": 1,
            "plan_capabilities": ["function:query.manifest"],
            "plan_capability_match": True,
            "unauthorized_execution_claim": False,
        }
        for index in range(1, 101)
    ]
    return {
        "schema_version": "1.3.0",
        "source_revision": SOURCE_REVISION,
        "configuration_digest": DIGEST,
        "workspace_patch_digest": DIGEST,
        "evidence_identity_digest": DIGEST,
        "receipt_source": "live_assurance",
        "run_scope": "full_cohort",
        "run_mode": "live",
        "started_at": "2026-08-17T00:00:00Z",
        "completed_at": "2026-08-17T01:00:00Z",
        "authentication": "browser_entra",
        "authentication_attestation": {
            "storage_state_restored": True,
            "live_protected_request_count": 100,
        },
        "run_configuration": {"schema_version": "1.4.0"},
        "transport_evidence": {
            "schema_version": "1.0.0",
            "phase": "seeded_100",
            "request_topic_digest": "sha256:" + "c" * 64,
            "projection_topic_digest": "sha256:" + "d" * 64,
            "request_count": 100,
            "projection_count": 100,
        },
        "passed": True,
        "production_ready": True,
        "summary": {
            "question_count": 100,
            "live_question_count": 100,
            "resumed_question_count": 0,
            "passed_count": 100,
            "answered_count": 100,
            "answered_with_complete_evidence_count": 100,
            "locale_coverage_complete": True,
            "operation_coverage_complete": True,
            "answered_locale_coverage_complete": True,
            "required_answer_coverage_complete": True,
            "unsupported_operational_claim_count": 0,
            "unauthorized_execution_count": 0,
            "ambient_request_count": 0,
            "bound_request_count": 0,
            "plan_capability_mismatch_count": 0,
            "exhausted_transport_retry_count": 0,
        },
        "results": results,
    }


def test_repository_safe_projection_hashes_runtime_identities() -> None:
    source = _passing_artifact()

    projected = project_repository_safe_baseline(source, source_artifact_digest=DIGEST)

    encoded = json.dumps(projected)
    assert projected["production_ready"] is True
    assert len(projected["results"]) == 100
    assert projected["results"][0]["request_id_digest"].startswith("sha256:")
    assert projected["results"][0]["projection_id_digest"].startswith("sha256:")
    assert projected["transport_evidence"] == source["transport_evidence"]
    assert "request-1" not in encoded
    assert "projection-1" not in encoded


def test_repository_safe_projection_rejects_failed_source() -> None:
    source = _passing_artifact()
    source["production_ready"] = False

    with pytest.raises(BaselineProjectionError, match="full assurance gate"):
        project_repository_safe_baseline(source, source_artifact_digest=DIGEST)


def test_repository_safe_projection_rejects_missing_transport_evidence() -> None:
    source = _passing_artifact()
    del source["transport_evidence"]

    with pytest.raises(BaselineProjectionError, match="full assurance gate"):
        project_repository_safe_baseline(source, source_artifact_digest=DIGEST)


def test_repository_safe_projection_cli_writes_valid_json(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    destination = tmp_path / "baseline.json"
    source.write_text(json.dumps(_passing_artifact()), encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - invokes the repository-owned Python module
        (
            sys.executable,
            "-m",
            "scripts.automation.project_ontology_assurance_baseline",
            str(source),
            str(destination),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(destination.read_text(encoding="utf-8"))["production_ready"] is True
