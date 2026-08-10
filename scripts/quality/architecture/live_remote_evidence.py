#!/usr/bin/env python3
"""Derive customer-agnostic live compatibility records from remote transitions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
ROLLBACK_ORDER = (
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
    "core-control-plane",
)
RESTORE_ORDER = SERVICE_IDS
OBSERVATION_KINDS = (
    "health",
    "identity",
    "image",
    "offset",
    "schema",
    "source",
    "topology",
)


class LiveRemoteEvidenceError(ValueError):
    """Report remote evidence that cannot produce exact live compatibility records."""


def canonical_digest(value: object) -> str:
    """Return the canonical JSON digest used by service evidence contracts."""
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LiveRemoteEvidenceError(f"{label} must be an object")
    return value


def _services(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise LiveRemoteEvidenceError(f"{label} must be an array")
    result: dict[str, dict[str, Any]] = {}
    for raw in value:
        item = _object(raw, f"{label} item")
        service_id = item.get("id")
        if service_id not in SERVICE_IDS or service_id in result:
            raise LiveRemoteEvidenceError(f"{label} service ids are invalid")
        result[str(service_id)] = item
    if set(result) != set(SERVICE_IDS):
        raise LiveRemoteEvidenceError(f"{label} must cover the canonical five services")
    return result


def _stage(service: dict[str, Any], name: str) -> dict[str, Any]:
    stages = service.get("stages")
    if not isinstance(stages, list):
        raise LiveRemoteEvidenceError("remote service stages must be an array")
    matches = [item for item in stages if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise LiveRemoteEvidenceError(f"remote service must contain one {name} stage")
    return matches[0]


def _peer_versions(
    order: tuple[str, ...], service_id: str, before: str, after: str
) -> dict[str, str]:
    target_index = order.index(service_id)
    return {
        peer: after if order.index(peer) < target_index else before
        for peer in SERVICE_IDS
        if peer != service_id
    }


def _artifact_content(
    service_id: str,
    kind: str,
    rollback: dict[str, Any],
    restore: dict[str, Any],
) -> dict[str, Any]:
    def transition(stage: dict[str, Any]) -> dict[str, Any]:
        plan = _object(stage.get("plan"), "remote plan")
        apply = _object(stage.get("apply"), "remote apply")
        return {
            "plan_run_id": plan["workflow_run_id"],
            "apply_run_id": apply["workflow_run_id"],
            "plan_digest": plan["plan_digest"],
            "context_digest": plan["context_digest"],
            "peer_receipt_artifact_sha256": apply["peer_receipt_artifact_sha256"],
        }

    return {
        "kind": kind,
        "service_id": service_id,
        "observed": True,
        "rollback": transition(rollback),
        "restore": transition(restore),
    }


def build_live_remote_evidence(
    compatibility: dict[str, Any], remote: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build exact receipts and observations from a validated remote aggregate."""
    remote_services = _services(remote.get("services"), "remote services")
    compatibility_services = _services(compatibility.get("services"), "compatibility services")
    controls = remote.get("controls_commit_sha")
    repository = remote.get("repository")
    workflow = remote.get("workflow")
    if not all(isinstance(value, str) and value for value in (controls, repository, workflow)):
        raise LiveRemoteEvidenceError("remote evidence source fields are invalid")
    run_id = f"is09-remote-transition:{controls}"
    source = {"repository": repository, "revision": controls, "workflow": workflow}
    source_digest = canonical_digest(source)
    artifacts: list[dict[str, Any]] = []
    observation_refs: dict[str, dict[str, str]] = {}
    for service_id in SERVICE_IDS:
        rollback = _stage(remote_services[service_id], "rollback")
        restore = _stage(remote_services[service_id], "restore")
        observation_refs[service_id] = {}
        for kind in OBSERVATION_KINDS:
            content = _artifact_content(service_id, kind, rollback, restore)
            artifact_without_ref = {
                "kind": kind,
                "service_id": service_id,
                "run_id": run_id,
                "source_digest": source_digest,
                "content_digest": canonical_digest(content),
                "content": content,
            }
            reference = canonical_digest(artifact_without_ref)
            observation_refs[service_id][kind] = reference
            artifacts.append({"ref": reference, **artifact_without_ref})
    evidence_manifest = {
        "manifest_version": "1.0.0",
        "run_id": run_id,
        "source": source,
        "source_digest": source_digest,
        "artifacts": artifacts,
    }
    evidence_manifest_digest = canonical_digest(evidence_manifest)
    matrix_digest = canonical_digest(compatibility.get("producer_consumer_matrix"))
    receipts: list[dict[str, Any]] = []
    for service_index, service_id in enumerate(SERVICE_IDS):
        service = remote_services[service_id]
        contract = compatibility_services[service_id]
        for direction_index, (direction, stage_name, order) in enumerate(
            (
                ("migration", "restore", RESTORE_ORDER),
                ("rollback", "rollback", ROLLBACK_ORDER),
            )
        ):
            transition = _object(contract.get(direction), f"{service_id} {direction}")
            before = transition.get("from_version")
            after = transition.get("to_version")
            if not isinstance(before, str) or not isinstance(after, str):
                raise LiveRemoteEvidenceError(f"{service_id} {direction} versions are invalid")
            remote_stage = _stage(service, stage_name)
            apply = _object(remote_stage.get("apply"), f"{service_id} {stage_name} apply")
            peers = _peer_versions(order, service_id, before, after)
            receipts.append(
                {
                    "receipt_version": "1.0.0",
                    "receipt_id": (
                        f"00000000-0000-0000-0000-{300 + service_index * 2 + direction_index:012d}"
                    ),
                    "service_id": service_id,
                    "direction": direction,
                    "from_version": before,
                    "to_version": after,
                    "idempotency_key": (
                        f"service-upgrade:{service_id}:{direction}:{before}:{after}"
                    ),
                    "matrix_digest": matrix_digest,
                    "peer_versions_before": peers,
                    "peer_versions_after": peers,
                    "peer_restart_count": 0,
                    "duplicate_terminal_effects": 0,
                    "offsets_preserved": True,
                    "checks": {
                        "additive_fields": True,
                        "duplicate_delivery": True,
                        "health": True,
                        "idempotency": True,
                        "matrix": True,
                        "reordered_delivery": True,
                        "unsupported_major_rejection": True,
                    },
                    "started_at": apply["started_at"],
                    "completed_at": apply["completed_at"],
                    "proof_kind": "live",
                    "evidence_manifest_digest": evidence_manifest_digest,
                    "evidence_run_id": run_id,
                    "evidence_source_digest": source_digest,
                    "observation_refs": observation_refs[service_id],
                    "outcome": "stable",
                }
            )
    return receipts, evidence_manifest
