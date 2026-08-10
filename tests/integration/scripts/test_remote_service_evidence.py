from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
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
    "operator-service": ((300, 305), (311, 316)),
    "document-ingestion-api": ((301, 306), (312, 317)),
    "document-processing-worker": ((302, 307), (313, 318)),
    "isolated-executor": ((303, 308), (314, 319)),
    "core-control-plane": ((304, 309), (310, 315)),
}


def _digest(seed: int) -> str:
    return f"sha256:{seed:064x}"


def _manifest() -> dict[str, Any]:
    return {
        "release_transition": {
            "n_distribution_version": "0.1.3",
            "n_source_revision": _N_SOURCE,
            "n_minus_one_distribution_version": "0.1.2",
            "n_minus_one_source_revision": _N_MINUS_ONE_SOURCE,
            "local_n_minus_one_source_revision": "d" * 40,
            "n_contract_set_version": "1.1.0",
            "n_minus_one_contract_set_version": "1.0.0",
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
    started_at = datetime(2026, 8, 9, tzinfo=UTC) + timedelta(seconds=run_id * 10)
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
        "started_at": started_at.isoformat(),
        "completed_at": (started_at + timedelta(seconds=5)).isoformat(),
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
        "deployment_mode": "standard",
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
        "live_observation_artifact_sha256": _digest(seed + 6),
    }
    image_digest = _digest(10 + service_index if release == "N" else 20 + service_index)
    apply["observations"] = {
        kind: {
            "kind": kind,
            "service_id": SERVICE_IDS[service_index],
            "observed": True,
            "workflow_run_id": apply_id,
            "workflow_run_attempt": 1,
            "commit_sha": _N_SOURCE if release == "N" else _N_MINUS_ONE_SOURCE,
            "verification": verification,
            **({"image_digest": image_digest} if kind == "image" else {}),
        }
        for kind, verification in (
            ("health", "post-apply-health"),
            ("identity", "sealed-target-identity"),
            ("image", "attested-and-observed-image"),
            ("offset", "peer-state-serials-preserved"),
            ("schema", "service-migration-upgrade"),
            ("source", "protected-plan-source"),
            ("topology", "four-peer-isolation"),
        )
    }
    return {
        "name": name,
        "release": release,
        "source_revision": _N_SOURCE if release == "N" else _N_MINUS_ONE_SOURCE,
        "image_digest": image_digest,
        "plan": plan,
        "apply": apply,
    }


def _evidence() -> dict[str, Any]:
    images_n = {
        service_id: {
            "digest": _digest(10 + index),
            "attestations": [
                "provenance",
                "sbom",
                *(["resolved-models"] if service_id == "core-control-plane" else []),
            ],
        }
        for index, service_id in enumerate(SERVICE_IDS)
    }
    images_n_minus_one = {
        service_id: {
            "digest": _digest(20 + index),
            "attestations": [
                "provenance",
                "sbom",
                *(["resolved-models"] if service_id == "core-control-plane" else []),
            ],
        }
        for index, service_id in enumerate(SERVICE_IDS)
    }
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
        "adoptions": [
            {
                "service_id": service_id,
                "completion": {
                    "workflow_run_id": 30 + index,
                    "workflow_run_attempt": 1,
                    "workflow_head_sha": _CONTROLS,
                    "conclusion": "success" if index == 0 else "failure",
                    "migration_step_conclusion": "success",
                },
                "artifact": {
                    "workflow_run_id": 40 + index,
                    "workflow_run_attempt": 1,
                    "workflow_head_sha": _CONTROLS,
                    "controls_commit_sha": _CONTROLS,
                    "conclusion": "failure",
                    "artifact_step_conclusion": "success",
                    "artifact_sha256": _digest(30 + index),
                    "observed_legacy_head": "legacy_head_1",
                    "observed_legacy_revision_count": 10,
                    "observed_schema_fingerprint": _digest(40 + index),
                    "schema_version": 1,
                    "owned_table_count": index + 1,
                    "verified_at": "2026-08-09T00:00:00Z",
                    "rollback_reference": (
                        f"git:{_CONTROLS}:service-migrations/branches/"
                        f"{service_id}/adoption.json#rollback"
                    ),
                },
            }
            for index, service_id in enumerate(SERVICE_IDS)
        ],
        "n": {
            "distribution_version": "0.1.3",
            "source_revision": _N_SOURCE,
            "supply_chain_run_id": 10,
            "supply_chain_run_attempt": 1,
            "workflow_head_sha": _N_SOURCE,
            "conclusion": "success",
            "images": images_n,
        },
        "n_minus_one": {
            "distribution_version": "0.1.2",
            "source_revision": _N_MINUS_ONE_SOURCE,
            "supply_chain_run_id": 20,
            "supply_chain_run_attempt": 1,
            "workflow_head_sha": _N_MINUS_ONE_SOURCE,
            "conclusion": "success",
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


def _set_stage_run_ids(stage: dict[str, Any], plan_id: int, apply_id: int) -> None:
    stage["plan"]["workflow_run_id"] = plan_id
    stage["apply"]["workflow_run_id"] = apply_id
    stage["apply"]["plan_run_id"] = plan_id
    for observation in stage["apply"]["observations"].values():
        observation["workflow_run_id"] = apply_id


def test_accepts_complete_customer_agnostic_remote_evidence() -> None:
    summary = validate_remote_service_evidence(_manifest(), _evidence())

    assert summary.service_plan_apply_receipts == 5
    assert summary.service_upgrade_and_rollback_proofs == 5
    assert summary.protected_plan_runs == 15
    assert summary.protected_apply_runs == 15
    assert summary.peer_isolation_receipts == 30


def test_rejects_replayed_initial_cutover_in_compatibility_proof() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][0]["plan"]["deployment_mode"] = "initial-cutover"

    with pytest.raises(RemoteEvidenceError, match="deployment mode is invalid"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_missing_remote_adoption() -> None:
    evidence = _evidence()
    evidence["adoptions"].pop()

    with pytest.raises(RemoteEvidenceError, match="must contain five services"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_unsuccessful_remote_adoption_step() -> None:
    evidence = _evidence()
    evidence["adoptions"][0]["completion"]["migration_step_conclusion"] = "failure"

    with pytest.raises(RemoteEvidenceError, match="adoption completion is incomplete"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_accepts_adoption_artifact_before_later_completion() -> None:
    evidence = _evidence()
    adoption = evidence["adoptions"][0]

    assert adoption["artifact"]["workflow_run_id"] != adoption["completion"]["workflow_run_id"]
    validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_relabelled_live_observation() -> None:
    evidence = _evidence()
    observation = evidence["services"][0]["stages"][1]["apply"]["observations"]["health"]
    observation["kind"] = "image"

    with pytest.raises(RemoteEvidenceError, match="health observation binding is invalid"):
        validate_remote_service_evidence(_manifest(), evidence)


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
    reused = evidence["n"]["images"]["core-control-plane"]["digest"]
    evidence["n"]["images"]["operator-service"]["digest"] = reused
    operator = _service(evidence, "operator-service")
    operator["stages"][0]["image_digest"] = reused
    operator["stages"][2]["image_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="image digests must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_same_image_for_n_and_n_minus_one() -> None:
    evidence = _evidence()
    reused = evidence["n"]["images"]["core-control-plane"]["digest"]
    evidence["n_minus_one"]["images"]["core-control-plane"]["digest"] = reused
    core = _service(evidence, "core-control-plane")
    core["stages"][1]["image_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="N and N-1 images must be distinct"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_supply_chain_head_not_bound_to_source() -> None:
    evidence = _evidence()
    evidence["n"]["workflow_head_sha"] = "d" * 40

    with pytest.raises(RemoteEvidenceError, match="workflow head does not match"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_n_source_not_bound_to_release_contract() -> None:
    evidence = _evidence()
    evidence["n"]["source_revision"] = "d" * 40
    evidence["n"]["workflow_head_sha"] = "d" * 40

    with pytest.raises(RemoteEvidenceError, match="source revision does not match"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_failed_supply_chain_run() -> None:
    evidence = _evidence()
    evidence["n_minus_one"]["conclusion"] = "failure"

    with pytest.raises(RemoteEvidenceError, match="conclusion is not success"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_incomplete_image_attestations() -> None:
    evidence = _evidence()
    evidence["n"]["images"]["core-control-plane"]["attestations"].remove("resolved-models")

    with pytest.raises(RemoteEvidenceError, match="attestations are incomplete"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_stage_context() -> None:
    evidence = _evidence()
    reused = evidence["services"][0]["stages"][0]["plan"]["context_digest"]
    rollback = evidence["services"][0]["stages"][1]
    rollback["plan"]["context_digest"] = reused
    rollback["apply"]["context_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="context digests must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_stage_plan_digest() -> None:
    evidence = _evidence()
    reused = evidence["services"][0]["stages"][0]["plan"]["plan_digest"]
    rollback = evidence["services"][1]["stages"][1]
    rollback["plan"]["plan_digest"] = reused
    rollback["apply"]["plan_digest"] = reused

    with pytest.raises(RemoteEvidenceError, match="plan digests must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_reused_plan_metadata_artifact() -> None:
    evidence = _evidence()
    reused = evidence["services"][0]["stages"][0]["plan"]["metadata_artifact_sha256"]
    evidence["services"][0]["stages"][1]["plan"]["metadata_artifact_sha256"] = reused

    with pytest.raises(RemoteEvidenceError, match="metadata artifacts must be unique"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_stale_controls_commit() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][0]["plan"]["controls_commit_sha"] = "d" * 40

    with pytest.raises(RemoteEvidenceError, match="aggregate controls commit"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_accepts_distinct_dispatch_head_with_same_trusted_controls() -> None:
    evidence = _evidence()
    evidence["services"][0]["stages"][0]["plan"]["workflow_head_sha"] = "d" * 40

    validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_customer_azure_context() -> None:
    evidence = _evidence()
    evidence["tenant_id"] = "00000000-0000-0000-0000-000000000123"

    with pytest.raises(RemoteEvidenceError, match="deployment context"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_customer_azure_context_in_manifest() -> None:
    manifest = _manifest()
    manifest["tenant_id"] = "00000000-0000-0000-0000-000000000123"

    with pytest.raises(RemoteEvidenceError, match="deployment context"):
        validate_remote_service_evidence(manifest, _evidence())


def test_rejects_embedded_azure_resource_identifier() -> None:
    evidence = _evidence()
    evidence["repository"] = "/subscriptions/example/resourceGroups/example"

    with pytest.raises(RemoteEvidenceError, match="deployment identifier"):
        validate_remote_service_evidence(_manifest(), evidence)


@pytest.mark.parametrize(
    "value",
    (
        "%2Fsubscriptions%2F00000000-0000-0000-0000-000000000123",
        "00000000000000000000000000000123",
    ),
)
def test_rejects_encoded_or_compact_deployment_identifier(value: str) -> None:
    evidence = _evidence()
    evidence["repository"] = value

    with pytest.raises(RemoteEvidenceError, match="deployment identifier"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_missing_manifest_service() -> None:
    manifest = _manifest()
    manifest["services"].pop()

    with pytest.raises(RemoteEvidenceError, match="canonical five services"):
        validate_remote_service_evidence(manifest, _evidence())


def test_rejects_unrecognized_transition_field() -> None:
    manifest = _manifest()
    manifest["release_transition"]["unexpected"] = "value"

    with pytest.raises(RemoteEvidenceError, match="release transition fields are invalid"):
        validate_remote_service_evidence(manifest, _evidence())


def test_rejects_core_rollback_before_executor() -> None:
    evidence = _evidence()
    core = _service(evidence, "core-control-plane")
    _set_stage_run_ids(core["stages"][1], 298, 299)

    with pytest.raises(RemoteEvidenceError, match="Executor must reach N-1"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_executor_restore_before_core() -> None:
    evidence = _evidence()
    core = _service(evidence, "core-control-plane")
    _set_stage_run_ids(core["stages"][2], 362, 363)

    with pytest.raises(RemoteEvidenceError, match="Core must return to N"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_inflated_summary() -> None:
    evidence = _evidence()
    evidence["summary"]["service_upgrade_and_rollback_proofs"] = 6

    with pytest.raises(RemoteEvidenceError, match="summary is invalid"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_overlapping_applies() -> None:
    evidence = _evidence()
    first_apply = evidence["services"][0]["stages"][0]["apply"]
    second_apply = evidence["services"][1]["stages"][0]["apply"]
    second_apply["started_at"] = first_apply["started_at"]
    second_apply["completed_at"] = first_apply["completed_at"]

    with pytest.raises(RemoteEvidenceError, match="applies must be serial"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_plan_overlapping_prior_apply() -> None:
    evidence = _evidence()
    initial_apply = evidence["services"][0]["stages"][0]["apply"]
    rollback_plan = evidence["services"][0]["stages"][1]["plan"]
    rollback_plan["started_at"] = initial_apply["started_at"]
    rollback_plan["completed_at"] = initial_apply["completed_at"]

    with pytest.raises(RemoteEvidenceError, match="rollback plans must follow all initial applies"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_restore_before_all_rollbacks() -> None:
    evidence = _evidence()
    operator_restore = _service(evidence, "operator-service")["stages"][2]
    executor = _service(evidence, "isolated-executor")
    core = _service(evidence, "core-control-plane")
    _set_stage_run_ids(operator_restore, 308, 309)
    _set_stage_run_ids(executor["stages"][1], 320, 321)
    _set_stage_run_ids(executor["stages"][2], 322, 323)
    _set_stage_run_ids(core["stages"][1], 324, 325)
    _set_stage_run_ids(core["stages"][2], 326, 327)

    with pytest.raises(RemoteEvidenceError, match="restores must follow all rollback"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_run_that_completes_before_start() -> None:
    evidence = _evidence()
    apply = evidence["services"][0]["stages"][0]["apply"]
    apply["completed_at"] = "2026-08-09T00:00:00+00:00"

    with pytest.raises(RemoteEvidenceError, match="completed before it started"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_rejects_apply_starting_before_plan_completed() -> None:
    evidence = _evidence()
    stage = evidence["services"][0]["stages"][0]
    stage["apply"]["started_at"] = stage["plan"]["started_at"]
    stage["apply"]["completed_at"] = stage["plan"]["completed_at"]

    with pytest.raises(RemoteEvidenceError, match="before its plan completed"):
        validate_remote_service_evidence(_manifest(), evidence)


def test_validation_does_not_mutate_evidence() -> None:
    evidence = _evidence()
    before = copy.deepcopy(evidence)

    validate_remote_service_evidence(_manifest(), evidence)

    assert evidence == before
