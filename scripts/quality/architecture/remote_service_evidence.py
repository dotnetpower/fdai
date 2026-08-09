#!/usr/bin/env python3
"""Validate customer-agnostic remote evidence for five service transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
REPOSITORY = "dotnetpower/fdai"
WORKFLOW = ".github/workflows/service-deploy.yml"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_GUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_FORBIDDEN_KEYS = re.compile(
    r"(?i)(tenant|subscription|resource[_-]?group|resource[_-]?id|backend|endpoint|hostname)"
)
_FORBIDDEN_VALUES = re.compile(
    r"(?i)(/subscriptions/|\.azure\.(?:com|net)|\.windows\.net|https?://[^/]*azure)"
)
_STAGE_NAMES = ("initial", "rollback", "restore")
_STAGE_RELEASES = {"initial": "N", "rollback": "N-1", "restore": "N"}


class RemoteEvidenceError(ValueError):
    """Report incomplete, inconsistent, or deployment-specific remote evidence."""


@dataclass(frozen=True, slots=True)
class RemoteEvidenceSummary:
    """Counts derived from one complete remote verification aggregate."""

    service_plan_apply_receipts: int
    service_upgrade_and_rollback_proofs: int
    protected_plan_runs: int
    protected_apply_runs: int
    peer_isolation_receipts: int


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RemoteEvidenceError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RemoteEvidenceError(f"{label} must be an array")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RemoteEvidenceError(f"{label} fields are invalid")


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RemoteEvidenceError(f"{label} must be a sha256 digest")
    return value


def _require_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise RemoteEvidenceError(f"{label} must be a lowercase 40-character git SHA")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RemoteEvidenceError(f"{label} must be a positive integer")
    return value


def _reject_deployment_context(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise RemoteEvidenceError(f"{path} has a non-string key")
            if _FORBIDDEN_KEYS.search(key):
                raise RemoteEvidenceError(f"remote evidence contains deployment context at {path}")
            _reject_deployment_context(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_deployment_context(nested, path=f"{path}[{index}]")
    elif isinstance(value, str):
        if _GUID.search(value) or _FORBIDDEN_VALUES.search(value):
            raise RemoteEvidenceError(f"remote evidence contains a deployment identifier at {path}")


def _validate_release(
    value: object,
    *,
    label: str,
    expected_version: str,
    expected_source_revision: str | None,
) -> dict[str, Any]:
    release = _object(value, label)
    _exact_keys(
        release,
        {
            "distribution_version",
            "source_revision",
            "supply_chain_run_id",
            "supply_chain_run_attempt",
            "images",
        },
        label,
    )
    if release["distribution_version"] != expected_version:
        raise RemoteEvidenceError(f"{label} distribution version is invalid")
    source_revision = _require_commit(release["source_revision"], f"{label} source revision")
    if expected_source_revision is not None and source_revision != expected_source_revision:
        raise RemoteEvidenceError(f"{label} source revision does not match the release contract")
    _require_positive_int(release["supply_chain_run_id"], f"{label} supply-chain run id")
    _require_positive_int(release["supply_chain_run_attempt"], f"{label} supply-chain run attempt")
    images = _object(release["images"], f"{label} images")
    if set(images) != set(SERVICE_IDS):
        raise RemoteEvidenceError(f"{label} images must cover the canonical five services")
    for service_id, digest in images.items():
        _require_sha256(digest, f"{label} {service_id} image")
    return release


def _validate_run_common(
    value: object,
    *,
    label: str,
    controls_commit_sha: str,
) -> tuple[dict[str, Any], int, int]:
    run = _object(value, label)
    for key in ("workflow_head_sha", "controls_commit_sha"):
        if _require_commit(run.get(key), f"{label} {key}") != controls_commit_sha:
            raise RemoteEvidenceError(f"{label} does not use the aggregate controls commit")
    run_id = _require_positive_int(run.get("workflow_run_id"), f"{label} workflow run id")
    run_attempt = _require_positive_int(
        run.get("workflow_run_attempt"), f"{label} workflow run attempt"
    )
    if run.get("conclusion") != "success":
        raise RemoteEvidenceError(f"{label} conclusion is not success")
    if run.get("peer_receipt_status") != "verified" or run.get("peer_count") != 4:
        raise RemoteEvidenceError(f"{label} peer isolation is not verified")
    for key in (
        "plan_digest",
        "context_digest",
        "peer_receipt_artifact_sha256",
    ):
        _require_sha256(run.get(key), f"{label} {key}")
    return run, run_id, run_attempt


def _validate_stage(
    value: object,
    *,
    service_id: str,
    expected_name: str,
    releases: dict[str, dict[str, Any]],
    controls_commit_sha: str,
    run_ids: set[int],
    peer_receipts: set[str],
) -> tuple[int, int]:
    stage = _object(value, f"{service_id} {expected_name} stage")
    _exact_keys(
        stage,
        {"name", "release", "source_revision", "image_digest", "plan", "apply"},
        f"{service_id} {expected_name} stage",
    )
    if stage["name"] != expected_name or stage["release"] != _STAGE_RELEASES[expected_name]:
        raise RemoteEvidenceError(f"{service_id} {expected_name} stage identity is invalid")
    release = releases[str(stage["release"])]
    if stage["source_revision"] != release["source_revision"]:
        raise RemoteEvidenceError(f"{service_id} {expected_name} source revision is invalid")
    if stage["image_digest"] != release["images"][service_id]:
        raise RemoteEvidenceError(f"{service_id} {expected_name} image digest is invalid")

    plan, plan_id, plan_attempt = _validate_run_common(
        stage["plan"],
        label=f"{service_id} {expected_name} plan",
        controls_commit_sha=controls_commit_sha,
    )
    _exact_keys(
        plan,
        {
            "workflow_run_id",
            "workflow_run_attempt",
            "workflow_head_sha",
            "controls_commit_sha",
            "deployment_mode",
            "plan_digest",
            "context_digest",
            "metadata_artifact_sha256",
            "peer_receipt_artifact_sha256",
            "peer_receipt_status",
            "peer_count",
            "conclusion",
        },
        f"{service_id} {expected_name} plan",
    )
    _require_sha256(
        plan["metadata_artifact_sha256"],
        f"{service_id} {expected_name} plan metadata artifact",
    )
    expected_mode = "initial-cutover" if expected_name == "initial" else "standard"
    if plan["deployment_mode"] != expected_mode:
        raise RemoteEvidenceError(f"{service_id} {expected_name} deployment mode is invalid")

    apply, apply_id, _apply_attempt = _validate_run_common(
        stage["apply"],
        label=f"{service_id} {expected_name} apply",
        controls_commit_sha=controls_commit_sha,
    )
    _exact_keys(
        apply,
        {
            "workflow_run_id",
            "workflow_run_attempt",
            "workflow_head_sha",
            "controls_commit_sha",
            "plan_run_id",
            "plan_run_attempt",
            "plan_digest",
            "context_digest",
            "peer_receipt_artifact_sha256",
            "peer_receipt_status",
            "peer_count",
            "conclusion",
        },
        f"{service_id} {expected_name} apply",
    )
    if (
        apply["plan_run_id"] != plan_id
        or apply["plan_run_attempt"] != plan_attempt
        or apply["plan_digest"] != plan["plan_digest"]
        or apply["context_digest"] != plan["context_digest"]
    ):
        raise RemoteEvidenceError(f"{service_id} {expected_name} apply is not bound to its plan")
    if apply_id <= plan_id:
        raise RemoteEvidenceError(f"{service_id} {expected_name} apply must follow its plan")
    if plan["peer_receipt_artifact_sha256"] == apply["peer_receipt_artifact_sha256"]:
        raise RemoteEvidenceError(
            f"{service_id} {expected_name} plan and apply peer receipts must be distinct"
        )
    for receipt in (
        plan["peer_receipt_artifact_sha256"],
        apply["peer_receipt_artifact_sha256"],
    ):
        if receipt in peer_receipts:
            raise RemoteEvidenceError("remote peer receipt artifacts must be unique")
        peer_receipts.add(receipt)
    for run_id in (plan_id, apply_id):
        if run_id in run_ids:
            raise RemoteEvidenceError("remote workflow run ids must be unique")
        run_ids.add(run_id)
    return plan_id, apply_id


def validate_remote_service_evidence(
    manifest: dict[str, Any], evidence: dict[str, Any]
) -> RemoteEvidenceSummary:
    """Validate exact remote N -> N-1 -> N evidence without Azure context."""

    _reject_deployment_context(evidence)
    _exact_keys(
        evidence,
        {
            "schema_version",
            "proof_kind",
            "repository",
            "workflow",
            "controls_commit_sha",
            "n",
            "n_minus_one",
            "services",
            "summary",
        },
        "remote evidence",
    )
    if evidence["schema_version"] != "1.0.0" or evidence["proof_kind"] != "remote":
        raise RemoteEvidenceError("remote evidence version or proof kind is invalid")
    if evidence["repository"] != REPOSITORY or evidence["workflow"] != WORKFLOW:
        raise RemoteEvidenceError("remote evidence repository or workflow is invalid")
    controls_commit_sha = _require_commit(
        evidence["controls_commit_sha"], "remote evidence controls commit"
    )
    transition = _object(manifest.get("release_transition"), "release transition")
    n = _validate_release(
        evidence["n"],
        label="N release",
        expected_version=str(transition["n_distribution_version"]),
        expected_source_revision=None,
    )
    n_minus_one = _validate_release(
        evidence["n_minus_one"],
        label="N-1 release",
        expected_version=str(transition["n_minus_one_distribution_version"]),
        expected_source_revision=str(transition["n_minus_one_source_revision"]),
    )
    if n["source_revision"] == n_minus_one["source_revision"]:
        raise RemoteEvidenceError("N and N-1 source revisions must be distinct")
    if n["supply_chain_run_id"] == n_minus_one["supply_chain_run_id"]:
        raise RemoteEvidenceError("N and N-1 supply-chain runs must be distinct")

    services = _array(evidence["services"], "remote evidence services")
    if len(services) != 5:
        raise RemoteEvidenceError("remote evidence must contain five services")
    service_order = [
        service.get("id") if isinstance(service, dict) else None for service in services
    ]
    if service_order != list(SERVICE_IDS):
        raise RemoteEvidenceError("remote evidence services must use canonical order")
    manifest_services = {
        str(item["id"]): item for item in _array(manifest.get("services"), "manifest services")
    }
    releases = {"N": n, "N-1": n_minus_one}
    seen: set[str] = set()
    run_ids: set[int] = set()
    peer_receipts: set[str] = set()
    apply_ids: dict[tuple[str, str], int] = {}
    initial_apply_ids: list[int] = []
    for value in services:
        service = _object(value, "remote evidence service")
        _exact_keys(
            service,
            {"id", "distribution", "transition_sequence", "stages"},
            "remote evidence service",
        )
        service_id = service.get("id")
        if service_id not in SERVICE_IDS or service_id in seen:
            raise RemoteEvidenceError("remote evidence service ids are invalid or duplicated")
        service_id = str(service_id)
        seen.add(service_id)
        if service["distribution"] != manifest_services[service_id]["distribution"]:
            raise RemoteEvidenceError(f"{service_id} distribution is invalid")
        expected_sequence = [
            transition["n_distribution_version"],
            transition["n_minus_one_distribution_version"],
            transition["n_distribution_version"],
        ]
        if service["transition_sequence"] != expected_sequence:
            raise RemoteEvidenceError(f"{service_id} transition sequence is invalid")
        stages = _array(service["stages"], f"{service_id} stages")
        if len(stages) != 3:
            raise RemoteEvidenceError(f"{service_id} must have three transition stages")
        stage_run_ids: dict[str, tuple[int, int]] = {}
        for expected_name, stage in zip(_STAGE_NAMES, stages, strict=True):
            plan_id, apply_id = _validate_stage(
                stage,
                service_id=service_id,
                expected_name=expected_name,
                releases=releases,
                controls_commit_sha=controls_commit_sha,
                run_ids=run_ids,
                peer_receipts=peer_receipts,
            )
            stage_run_ids[expected_name] = (plan_id, apply_id)
            apply_ids[(service_id, expected_name)] = apply_id
        if not (
            stage_run_ids["initial"][1]
            < stage_run_ids["rollback"][0]
            < stage_run_ids["rollback"][1]
            < stage_run_ids["restore"][0]
            < stage_run_ids["restore"][1]
        ):
            raise RemoteEvidenceError(f"{service_id} transition run order is invalid")
        initial_apply_ids.append(stage_run_ids["initial"][1])
    if seen != set(SERVICE_IDS):
        raise RemoteEvidenceError("remote evidence must cover the canonical five services")
    if min(apply_ids[(service_id, "rollback")] for service_id in SERVICE_IDS) <= max(
        initial_apply_ids
    ):
        raise RemoteEvidenceError("rollback rehearsals must follow all initial N applies")
    if (
        apply_ids[("isolated-executor", "rollback")]
        >= apply_ids[("core-control-plane", "rollback")]
    ):
        raise RemoteEvidenceError("Executor must reach N-1 before the Core rollback")
    if apply_ids[("core-control-plane", "restore")] >= apply_ids[("isolated-executor", "restore")]:
        raise RemoteEvidenceError("Core must return to N before the Executor restore")

    summary = _object(evidence["summary"], "remote evidence summary")
    expected_summary = {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
        "protected_plan_runs": 15,
        "protected_apply_runs": 15,
        "peer_isolation_receipts": 30,
        "outcome": "verified",
    }
    if summary != expected_summary:
        raise RemoteEvidenceError("remote evidence summary is invalid")
    return RemoteEvidenceSummary(
        service_plan_apply_receipts=5,
        service_upgrade_and_rollback_proofs=5,
        protected_plan_runs=15,
        protected_apply_runs=15,
        peer_isolation_receipts=30,
    )
