"""Focused contracts for protected deployment plan and apply evidence builders."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.deployment.azure.build_deployment_apply_receipt import build_apply_receipt
from scripts.deployment.azure.build_deployment_plan_metadata import build_plan_metadata

_SOURCE_COMMIT = "a" * 40


def _plan_environ() -> dict[str, str]:
    return {
        "PLAN_ID": "plan-10-1",
        "PLAN_DIGEST": "b" * 64,
        "SOURCE_ARTIFACT_DIGEST": "c" * 64,
        "PLAN_CONTEXT_DIGEST": "d" * 64,
        "PREFLIGHT_EVIDENCE_DIGEST": "e" * 64,
        "AZURE_PREFLIGHT_EVIDENCE_DIGEST": "f" * 64,
        "PLAN_COMMIT_SHA": _SOURCE_COMMIT,
        "PLAN_REQUEST_ID": "standard-request",
        "CREATED_AT": "2026-09-11T00:00:00Z",
        "EXPIRES_AT": "2026-09-11T01:00:00Z",
        "GITHUB_RUN_ID": "10",
    }


def _apply_environ() -> dict[str, str]:
    return {
        "APPLY_PLAN_ID": "plan-10-1",
        "APPLY_PLAN_DIGEST": "b" * 64,
        "APPLY_REQUEST_ID": "standard-request",
        "APPLY_CONTEXT_DIGEST": "d" * 64,
        "APPLY_SOURCE_COMMIT": _SOURCE_COMMIT,
        "GITHUB_RUN_ID": "11",
        "GITHUB_RUN_ATTEMPT": "1",
        "APPLIED_AT": "2026-09-11T00:30:00Z",
    }


def test_plan_metadata_binds_summary_and_required_observations() -> None:
    summary = {
        "schema_version": "fdai.deployment-plan-summary.v1",
        "summary_digest": "1" * 64,
    }

    metadata = build_plan_metadata(environ=_plan_environ(), plan_summary=summary)

    assert metadata["plan_summary"] == summary
    assert metadata["post_apply_observations"] == [
        "database-migrations",
        "runtime-health",
        "initial-inventory-execution",
        "canary-publisher",
        "terraform-zero-change",
    ]
    assert "subscription_ready" not in metadata


def test_apply_receipt_binds_inventory_bytes_and_closes_digest(tmp_path: Path) -> None:
    inventory = {
        "schema_version": "fdai.genesis-initial-inventory-execution-receipt.v1",
        "source_commit": _SOURCE_COMMIT,
        "status": "succeeded",
        "active_generation_verified": False,
        "subscription_ready": False,
        "receipt_digest": "2" * 64,
    }
    inventory_path = tmp_path / "initial-inventory-receipt.json"
    inventory_path.write_text(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    plan_metadata_path = tmp_path / "plan-metadata.json"
    plan_metadata_path.write_text("{}\n", encoding="utf-8")

    receipt = build_apply_receipt(
        environ=_apply_environ(),
        inventory_path=inventory_path,
        plan_metadata_path=plan_metadata_path,
    )

    inventory_bytes = inventory_path.read_bytes()
    assert (
        receipt["initial_inventory_execution_receipt_digest"]
        == hashlib.sha256(inventory_bytes).hexdigest()
    )
    assert receipt["terraform_zero_change_verified"] is True
    receipt_digest = receipt.pop("receipt_digest")
    assert (
        receipt_digest
        == hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
