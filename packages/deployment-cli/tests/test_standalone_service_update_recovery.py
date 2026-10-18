from __future__ import annotations

import json
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_service_update_recovery import (
    failed_core_update_repair_digest,
    partial_core_update_admissible,
    readback_context,
    source_image_import_paths,
)


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _recovery(work_dir: Path) -> dict[str, object]:
    original = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "application",
    }
    residual_review = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "application",
        "plan_digest": "a" * 64,
    }
    residual = {
        "schema_version": "fdai.standalone-residual-claim.v1",
        "stage": "application",
    }
    successor_review = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "application",
        "source_commit": "b" * 40,
        "plan_digest": "c" * 64,
        "residual_successor": {
            "original_claim_digest": canonical_digest(original),
            "residual_plan_digest": residual_review["plan_digest"],
            "residual_claim_digest": canonical_digest(residual),
        },
        "summary": {
            "resource_changes": [
                {
                    "address": 'kubernetes_deployment_v1.workload["core-control-plane"]',
                    "actions": ["delete", "create"],
                },
                {
                    "address": 'kubernetes_horizontal_pod_autoscaler_v2.workload["core-control-plane"]',
                    "actions": ["create"],
                },
            ]
        },
    }
    successor = {
        "schema_version": "fdai.standalone-residual-successor-claim.v1",
        "stage": "application",
        "plan_digest": successor_review["plan_digest"],
        "original_claim_digest": canonical_digest(original),
        "residual_claim_digest": canonical_digest(residual),
    }
    rebind = {
        "schema_version": "fdai.application-input-rebind-receipt.v1",
        "field": "browser_gateway.backend_nsg_id",
        "mutation_performed": True,
    }
    rebind["receipt_digest"] = canonical_digest(rebind)
    for name, value in (
        ("application-claim.json", original),
        ("application-residual-review.json", residual_review),
        ("application-residual-claim.json", residual),
        ("application-residual-successor-review.json", successor_review),
        ("application-residual-successor-claim.json", successor),
        ("application-input-rebind-receipt.json", rebind),
    ):
        _write(work_dir / name, value)
    return {"source_commit": "b" * 40}


def test_partial_core_update_accepts_exact_failed_application_recovery(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    context = _recovery(tmp_path)

    assert partial_core_update_admissible(tmp_path, context, service="core-control-plane")
    assert not partial_core_update_admissible(tmp_path, context, service="operator-service")


def test_partial_core_update_rejects_unreviewed_change(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    context = _recovery(tmp_path)
    review_path = tmp_path / "application-residual-successor-review.json"
    review = json.loads(review_path.read_text())
    review["summary"]["resource_changes"].append(
        {"address": "kubernetes_service_v1.workload", "actions": ["update"]}
    )
    _write(review_path, review)

    assert not partial_core_update_admissible(tmp_path, context, service="core-control-plane")


def test_failed_core_update_allows_one_exact_repair(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    context = _recovery(tmp_path)
    operation = "service-update-core-control-plane-aaaaaaaaaaaa"
    record = {
        "schema_version": "fdai.aks-service-update.v1",
        "service": "core-control-plane",
        "operation": operation,
        "image": "registry.invalid/core@sha256:" + "1" * 64,
        "source_commit": "c" * 40,
        "previous_image": "registry.invalid/core@sha256:" + "2" * 64,
        "baseline": {
            "core-control-plane": {
                "image": "registry.invalid/core@sha256:" + "2" * 64,
                "source_commit": "b" * 40,
            }
        },
    }
    record["update_digest"] = canonical_digest(record)
    context["active_service_update"] = {
        "operation": operation,
        "service": "core-control-plane",
        "update_digest": record["update_digest"],
    }
    review = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "plan_digest": "d" * 64,
        "service_update": {
            "service": "core-control-plane",
            "image": record["image"],
            "source_commit": record["source_commit"],
            "update_digest": record["update_digest"],
        },
        "summary": {
            "action_counts": {
                "create": 0,
                "delete": 0,
                "no-op": 1,
                "read": 0,
                "replace": 1,
                "update": 0,
            }
        },
    }
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "application",
        "plan_digest": review["plan_digest"],
    }
    _write(tmp_path / f"{operation}.json", record)
    _write(tmp_path / f"{operation}-review.json", review)
    _write(tmp_path / f"{operation}-claim.json", claim)

    assert (
        failed_core_update_repair_digest(
            tmp_path,
            context,
            service="core-control-plane",
        )
        == record["update_digest"]
    )

    record["superseded_update_digest"] = record["update_digest"]
    record["update_digest"] = canonical_digest(
        {key: value for key, value in record.items() if key != "update_digest"}
    )
    context["active_service_update"]["update_digest"] = record["update_digest"]  # type: ignore[index]
    _write(tmp_path / f"{operation}.json", record)
    assert (
        failed_core_update_repair_digest(
            tmp_path,
            context,
            service="core-control-plane",
        )
        is None
    )


def test_failed_ordinary_core_update_allows_one_exact_rollback(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    operation = "service-update-core-control-plane-bbbbbbbbbbbb"
    record = {
        "schema_version": "fdai.aks-service-update.v1",
        "service": "core-control-plane",
        "operation": operation,
        "image": "registry.invalid/core@sha256:" + "1" * 64,
        "source_commit": "c" * 40,
        "previous_image": "registry.invalid/core@sha256:" + "2" * 64,
        "baseline": {
            "core-control-plane": {
                "image": "registry.invalid/core@sha256:" + "2" * 64,
                "source_commit": "b" * 40,
            }
        },
    }
    record["update_digest"] = canonical_digest(record)
    context = {
        "source_commit": "b" * 40,
        "active_service_update": {
            "operation": operation,
            "service": "core-control-plane",
            "update_digest": record["update_digest"],
        },
    }
    review = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "plan_digest": "d" * 64,
        "service_update": {
            "service": "core-control-plane",
            "image": record["image"],
            "source_commit": record["source_commit"],
            "update_digest": record["update_digest"],
        },
        "summary": {
            "action_counts": {
                "create": 0,
                "delete": 0,
                "no-op": 1,
                "read": 0,
                "replace": 0,
                "update": 1,
            }
        },
    }
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "application",
        "plan_digest": review["plan_digest"],
    }
    _write(tmp_path / f"{operation}.json", record)
    _write(tmp_path / f"{operation}-review.json", review)
    _write(tmp_path / f"{operation}-claim.json", claim)

    assert (
        failed_core_update_repair_digest(
            tmp_path,
            context,
            service="core-control-plane",
        )
        == record["update_digest"]
    )


def test_recovery_refreshes_secret_contract_from_planned_variables(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    _write(
        tmp_path / "workloads.auto.tfvars.json",
        {
            "workloads": {
                "core-control-plane": {
                    "secret_environment": {
                        "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                        "FDAI_TEAMS_NOTIFICATION_ENDPOINT": "fdai-teams-notification-endpoint",
                    }
                }
            }
        },
    )
    context = {
        "expected_workloads": {
            "core-control-plane": {
                "image": "registry.invalid/core@sha256:" + "1" * 64,
                "secret_environment": {"FDAI_STATE_STORE_DSN": "fdai-state-store-dsn"},
            }
        }
    }

    refreshed = readback_context(tmp_path, context)

    assert refreshed["expected_workloads"]["core-control-plane"][  # type: ignore[index]
        "secret_environment"
    ] == {
        "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
        "FDAI_TEAMS_NOTIFICATION_ENDPOINT": "fdai-teams-notification-endpoint",
    }
    assert context["expected_workloads"]["core-control-plane"][  # type: ignore[index]
        "secret_environment"
    ] == {"FDAI_STATE_STORE_DSN": "fdai-state-store-dsn"}


def test_later_source_image_uses_versioned_import_identity(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    service = "core-control-plane"
    _write(
        tmp_path / f"source-image-import-{service}-claim.json",
        {"source_commit": "a" * 40, "image_digest": "sha256:" + "b" * 64},
    )
    _write(
        tmp_path / f"source-image-import-{service}-receipt.json",
        {"state": "imported"},
    )

    claim, receipt = source_image_import_paths(
        tmp_path,
        service=service,
        source_commit="c" * 40,
        image_digest="sha256:" + "d" * 64,
    )

    assert claim.name.startswith(f"source-image-import-{service}-")
    assert claim.name.endswith("-claim.json")
    assert receipt.name == claim.name.removesuffix("-claim.json") + "-receipt.json"


def test_same_source_image_reuses_legacy_import_identity(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    service = "core-control-plane"
    commit = "a" * 40
    digest = "sha256:" + "b" * 64
    claim = tmp_path / f"source-image-import-{service}-claim.json"
    receipt = tmp_path / f"source-image-import-{service}-receipt.json"
    _write(claim, {"source_commit": commit, "image_digest": digest})

    assert source_image_import_paths(
        tmp_path,
        service=service,
        source_commit=commit,
        image_digest=digest,
    ) == (claim, receipt)
