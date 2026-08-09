from __future__ import annotations

import copy
from typing import Any

import pytest
from scripts.quality.architecture.remote_service_evidence import (
    SERVICE_IDS,
    RemoteEvidenceError,
    validate_remote_service_evidence,
)

_CONTROLS = "a" * 40
_N_SOURCE = "b" * 40
_N_MINUS_ONE_SOURCE = "c" * 40
_DISTRIBUTIONS = {
    "core-control-plane": "fdai-core-control-plane",
    "operator-service": "fdai-operator-service",
    "document-ingestion-api": "fdai-document-ingestion-api",
    "document-processing-worker": "fdai-document-processing-worker",
    "isolated-executor": "fdai-isolated-executor-service",
}
_TRANSITION_RUNS = {
    "operator-service": ((300, 301), (302, 303)),
    "document-ingestion-api": ((310, 311), (312, 313)),
    "document-processing-worker": ((320, 321), (322, 323)),
    "isolated-executor": ((330, 331), (360, 361)),
    "core-control-plane": ((340, 341), (342, 343)),
}


def _digest(seed: int) -> str:
    return f"sha256:{seed:064x}"


def _manifest() -> dict[str, Any]:
    return {
        "release_transition": {
            "n_distribution_version": "0.1.3",
            "n_minus_one_distribution_version": "0.1.2",
            "n_minus_one_source_revision": _N_MINUS_ONE_SOURCE,
        },
        "services": [
            {"id": service_id, "distribution": distribution}
            for service_id, distribution in _DISTRIBUTIONS.items()
        ],
    }


def _run(
    run_id: int,
    *,
    plan_digest: str,
    context_digest: str,
    peer_seed: int,
) -> dict[str, Any]:
    return {
        "workflow_run_id": run_id,
        "workflow_run_attempt": 1,
        "workflow_head_sha": _CONTROLS,
        "controls_commit_sha": _CONTROLS,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "peer_receipt_artifact_sha256": _digest(peer_seed),
        "peer_receipt_status": "verified",
        "peer_count": 4,
        "conclusion": "success",
    }


def _stage(
    *,
    service_index: int,
    name: str,
    release: str,
    plan_id: int,
    apply_id: int,
) -> dict[str, Any]:
    seed = service_index * 10_000 + plan_id * 10
    plan_digest = _digest(seed + 1)
    context_digest = _digest(seed + 2)
    plan = {
        **_run(
            plan_id,
            plan_digest=plan_digest,
            context_digest=context_digest,
            peer_seed=seed + 3,
        ),
        "deployment_mode": "initial-cutover" if name == "initial" else "standard",
        "metadata_artifact_sha256": _digest(seed + 4),
    }
    apply = {
        **_run(
            apply_id,
            plan_digest=plan_digest,
            context_digest=context_digest,
            peer_seed=seed + 5,
        ),
        "plan_run_id": plan_id,
        "plan_run_attempt": 1,
    }
    return {
        "name": name,
        "release": release,
        "source_revision": _N_SOURCE if release == "N" else _N_MINUS_ONE_SOURCE,
        "image_digest": _digest(10 + service_index if release == "N" else 20 + service_index),
        "plan": plan,
        "apply": apply,
    }


def _evidence() -> dict[str, Any]:
    images_n = {_id: _digest(10 + index) for index, _id in enumerate(SERVICE_IDS)}
    images_n_minus_one = {_id: _digest(20 + index) for index, _id in enumerate(SERVICE_IDS)}
    services = []
    for index, service_id in enumerate(SERVICE_IDS):
        rollback, restore = _TRANSITION_RUNS[service_id]
        services.append(
            {
                "id": service_id,
                "distribution": _DISTRIBUTIONS[service_id],
                "transition_sequence": ["0.1.3", "0.1.2", "0.1.3"],
                "stages": [
                    _stage(
                        service_index=index,
                        name="initial",
                        release="N",
                        plan_id=100 + index,
                        apply_id=200 + index,
                    ),
                    _stage(
                        service_index=index,
                        name="rollback",
                        release="N-1",
                        plan_id=rollback[0],
                        apply_id=rollback[1],
                    ),
                    _stage(
                        service_index=index,
                        name="restore",
                        release="N",
                        plan_id=restore[0],
                        apply_id=restore[1],
                    ),
                ],
            }
        )
    return {
        "schema_version": "1.0.0",
        "proof_kind": "remote",
        "repository": "dotnetpower/fdai",
        "workflow": ".github/workflows/service-deploy.yml",
        "controls_commit_sha": _CONTROLS,
        "n": {
            "distribution_version": "0.1.3",
            "source_revision": _N_SOURCE,
            "supply_chain_run_id": 10,
            "supply_chain_run_attempt": 1,
            "images": images_n,
        },
        "n_minus_one": {
            "distribution_version": "0.1.2",
            "source_revision": _N_MINUS_ONE_SOURCE,
            "supply_chain_run_id": 20,
            "supply_chain_run_attempt": 1,
            "images": images_n_minus_one,
        },
        "services": services,
        "summary": {
            "service_plan_apply_receipts": 5,
            "service_upgrade_and_rollback_proofs": 5,
            "protected_plan_runs": 15,
            "protected_apply_runs": 15,
            "peer_isolation_receipts": 30,
            "outcome": "verified",
        },
    }


def _service(evidence: dict[str, Any], service_id: str) -> dict[str, Any]:
    return next(item for item in evidence["services"] if item["id"] == service_id)


def test_accepts_complete_customer_agnostic_remote_evidence() -> None:
    summary = validate_remote_service_evidence(_manifest(), _evidence())

    assert summary.service_plan_apply_receipts == 5
    assert summary.service_upgrade_and_rollback_proofs == 5
    assert summary.protected_plan_runs == 15
    assert summary.protected_apply_runs == 15
    assert summary.peer_isolation_receipts == 30


def test_rejects_missing_service() -> None:
    evidence = _evidence()
    evidence["services"].pop()

    with pytest.raises(RemoteEvidenceError, match="must contain five services"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reordered_services() -> None:
    evidence = _evidence()
    evidence["services"][0], evidence["services"][1] = (
        evidence["services"][1],
        evidence["services"][0],
    )

    with pytest.raises(RemoteEvidenceError, match="canonical order"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_unbound_apply_plan() -> None:
    evidence = _evidence()
    apply = evidence["services"][0]["stages"][0]["apply"]
    apply["context_digest"] = _digest(999)

    with pytest.raises(RemoteEvidenceError, match="apply is not bound to its plan"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_duplicate_workflow_run() -> None:
    evidence = _evidence()
    evidence["services"][1]["stages"][0]["plan"]["workflow_run_id"] = 100
    evidence["services"][1]["stages"][0]["apply"]["plan_run_id"] = 100

    with pytest.raises(RemoteEvidenceError, match="run ids must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_unverified_peer_receipt() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][1]["apply"]["peer_receipt_status"] = "unknown"

    with pytest.raises(RemoteEvidenceError, match="peer isolation is not verified"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_peer_receipt_artifact() -> None:
    evidence = _evidence()
    reused = evidence["services"][0]["stages"][0]["plan"]["peer_receipt_artifact_sha256"]
    evidence["services"][1]["stages"][0]["plan"]["peer_receipt_artifact_sha256"] = reused

    with pytest.raises(RemoteEvidenceError, match="receipt artifacts must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_image_not_bound_to_release() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][2]["image_digest"] = _digest(999)

    with pytest.raises(RemoteEvidenceError, match="restore image digest is invalid"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_image_across_services() -> None:
    evidence = _evidence()
    reused = evidence["n"]["images"]["core-control-plane"]
    evidence["n"]["images"]["operator-service"] = reused
    operator = _service(evidence, "operator-service")
    operator["stages"][0]["image_digest"] = reused
    operator["stages"][2]["image_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="image digests must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_same_image_for_n_and_n_minus_one() -> None:
    evidence = _evidence()
    reused = evidence["n"]["images"]["core-control-plane"]
    evidence["n_minus_one"]["images"]["core-control-plane"] = reused
    core = _service(evidence, "core-control-plane")
    core["stages"][1]["image_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="N and N-1 images must be distinct"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_stage_context() -> None:
    evidence = _evidence()
    reused = evidence["services"][0]["stages"][0]["plan"]["context_digest"]
    rollback = evidence["services"][0]["stages"][1]
    rollback["plan"]["context_digest"] = reused
    rollback["apply"]["context_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="context digests must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_stale_controls_commit() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][0]["plan"]["controls_commit_sha"] = "d" * 40

    with pytest.raises(RemoteEvidenceError, match="aggregate controls commit"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_customer_azure_context() -> None:
    evidence = _evidence()
    evidence["tenant_id"] = "00000000-0000-0000-0000-000000000123"

    with pytest.raises(RemoteEvidenceError, match="deployment context"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_embedded_azure_resource_identifier() -> None:
    evidence = _evidence()
    evidence["repository"] = "/subscriptions/example/resourceGroups/example"

    with pytest.raises(RemoteEvidenceError, match="deployment identifier"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_core_rollback_before_executor() -> None:
    evidence = _evidence()
    core = _service(evidence, "core-control-plane")
    core["stages"][1]["plan"]["workflow_run_id"] = 328
    core["stages"][1]["apply"]["workflow_run_id"] = 329
    core["stages"][1]["apply"]["plan_run_id"] = 328

    with pytest.raises(RemoteEvidenceError, match="Executor must reach N-1"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_executor_restore_before_core() -> None:
    evidence = _evidence()
    core = _service(evidence, "core-control-plane")
    core["stages"][2]["plan"]["workflow_run_id"] = 362
    core["stages"][2]["apply"]["workflow_run_id"] = 363
    core["stages"][2]["apply"]["plan_run_id"] = 362

    with pytest.raises(RemoteEvidenceError, match="Core must return to N"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_inflated_summary() -> None:
    evidence = _evidence()
    evidence["summary"]["service_upgrade_and_rollback_proofs"] = 6

    with pytest.raises(RemoteEvidenceError, match="summary is invalid"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_validation_does_not_mutate_evidence() -> None:
    evidence = _evidence()
    before = copy.deepcopy(evidence)

    validate_remote_service_evidence(_manifest(), evidence)

    assert evidence == before
