"""Focused contracts for protected deployment plan and apply evidence builders."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.deployment.azure.build_cost_governance_job_readback import (
    build_job_readback,
)
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


def test_plan_metadata_seals_cost_governance_runtime_profile() -> None:
    environment = {
        **_plan_environ(),
        "FDAI_RUNTIME_IMAGE_REVISION": _SOURCE_COMMIT,
        "FDAI_RUNTIME_IMAGE_DIGEST": f"sha256:{'1' * 64}",
        "FDAI_RUNTIME_IMAGE_PROFILE": "cost-governance",
    }

    metadata = build_plan_metadata(environ=environment, plan_summary={})

    assert metadata["runtime_image"] == {
        "source_revision": _SOURCE_COMMIT,
        "digest": f"sha256:{'1' * 64}",
        "profile": "cost-governance",
    }
    assert metadata["post_apply_observations"] == [
        "terraform-zero-change",
        "cost-governance-job-image-readback",
    ]


def test_cost_governance_job_readback_binds_both_jobs() -> None:
    digest = "1" * 64

    readback = build_job_readback(
        expected_image=f"example.azurecr.io/fdai-cost-governance@sha256:{digest}",
        job_receipts={
            "collector": {
                "container": "cost-governance-collector",
                "image_digest": digest,
            },
            "analyzer": {
                "container": "cost-governance-analyzer",
                "image_digest": digest,
            },
        },
    )

    assert readback == {
        "schema_version": "fdai.cost-governance-job-image-readback.v1",
        "image_digest": f"sha256:{digest}",
        "jobs": {
            "analyzer": {
                "container": "cost-governance-analyzer",
                "image_digest": f"sha256:{digest}",
            },
            "collector": {
                "container": "cost-governance-collector",
                "image_digest": f"sha256:{digest}",
            },
        },
    }


@pytest.mark.parametrize(
    ("role", "field", "value", "message"),
    [
        ("collector", "image_digest", "2" * 64, "image digest does not match"),
        ("analyzer", "container", "inventory", "container binding is invalid"),
    ],
)
def test_cost_governance_job_readback_rejects_invalid_job_evidence(
    role: str,
    field: str,
    value: str,
    message: str,
) -> None:
    digest = "1" * 64
    receipts = {
        "collector": {
            "container": "cost-governance-collector",
            "image_digest": digest,
        },
        "analyzer": {
            "container": "cost-governance-analyzer",
            "image_digest": digest,
        },
    }
    receipts[role][field] = value

    with pytest.raises(ValueError, match=message):
        build_job_readback(
            expected_image=f"example.azurecr.io/fdai-cost-governance@sha256:{digest}",
            job_receipts=receipts,
        )


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


def test_cost_apply_receipt_binds_job_readback_and_plan_image(tmp_path: Path) -> None:
    image_digest = f"sha256:{'1' * 64}"
    readback = {
        "schema_version": "fdai.cost-governance-job-image-readback.v1",
        "image_digest": image_digest,
        "jobs": {
            "analyzer": {
                "container": "cost-governance-analyzer",
                "image_digest": image_digest,
            },
            "collector": {
                "container": "cost-governance-collector",
                "image_digest": image_digest,
            },
        },
    }
    readback_path = tmp_path / "cost-governance-job-image-readback.json"
    readback_path.write_text(
        json.dumps(readback, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    plan_metadata_path = tmp_path / "plan-metadata.json"
    plan_metadata_path.write_text(
        json.dumps(
            {
                "runtime_image": {
                    "source_revision": _SOURCE_COMMIT,
                    "digest": image_digest,
                    "profile": "cost-governance",
                }
            }
        ),
        encoding="utf-8",
    )
    environment = {
        **_apply_environ(),
        "APPLY_REQUEST_ID": "apply-cost-" + "a" * 48,
    }

    receipt = build_apply_receipt(
        environ=environment,
        inventory_path=tmp_path / "missing-inventory.json",
        plan_metadata_path=plan_metadata_path,
        cost_governance_readback_path=readback_path,
    )

    assert receipt["terraform_zero_change_verified"] is True
    assert receipt["cost_governance_job_images_verified"] is True
    assert receipt["cost_governance_image_digest"] == image_digest
    assert (
        receipt["cost_governance_job_image_readback_digest"]
        == hashlib.sha256(readback_path.read_bytes()).hexdigest()
    )
    assert "runtime_health_verified" not in receipt
    assert "canary_verified" not in receipt


def test_cost_apply_receipt_rejects_readback_for_another_plan_image(tmp_path: Path) -> None:
    readback_path = tmp_path / "cost-governance-job-image-readback.json"
    readback_path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.cost-governance-job-image-readback.v1",
                "image_digest": f"sha256:{'1' * 64}",
                "jobs": {
                    "analyzer": {
                        "container": "cost-governance-analyzer",
                        "image_digest": f"sha256:{'1' * 64}",
                    },
                    "collector": {
                        "container": "cost-governance-collector",
                        "image_digest": f"sha256:{'1' * 64}",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    plan_metadata_path = tmp_path / "plan-metadata.json"
    plan_metadata_path.write_text(
        json.dumps(
            {
                "runtime_image": {
                    "source_revision": _SOURCE_COMMIT,
                    "digest": f"sha256:{'2' * 64}",
                    "profile": "cost-governance",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match plan image evidence"):
        build_apply_receipt(
            environ={
                **_apply_environ(),
                "APPLY_REQUEST_ID": "apply-cost-" + "a" * 48,
            },
            inventory_path=tmp_path / "missing-inventory.json",
            plan_metadata_path=plan_metadata_path,
            cost_governance_readback_path=readback_path,
        )


def test_cost_apply_receipt_requires_job_readback(tmp_path: Path) -> None:
    plan_metadata_path = tmp_path / "plan-metadata.json"
    plan_metadata_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Job image readback is unavailable"):
        build_apply_receipt(
            environ={
                **_apply_environ(),
                "APPLY_REQUEST_ID": "apply-cost-" + "a" * 48,
            },
            inventory_path=tmp_path / "missing-inventory.json",
            plan_metadata_path=plan_metadata_path,
            cost_governance_readback_path=tmp_path / "missing-readback.json",
        )
