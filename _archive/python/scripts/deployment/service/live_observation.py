#!/usr/bin/env python3
"""Seal kind-specific live observations from one verified service apply receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
_SHA256 = re.compile(r"(?:sha256:)?[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IMAGE = re.compile(r"[^\s]+@(sha256:[0-9a-f]{64})")


class LiveObservationError(ValueError):
    """Raised when a verified apply receipt cannot produce live observations."""


def _required_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LiveObservationError(f"{label} must be a sha256 digest")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_observations(
    receipt: dict[str, Any],
    *,
    service_id: str,
    commit_sha: str,
    image_ref: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    plan_digest: str,
    context_digest: str,
) -> dict[str, Any]:
    """Build seven distinct observations only after peer and health verification succeeded."""
    if service_id not in _SERVICE_IDS or receipt.get("service") != service_id:
        raise LiveObservationError("live observation service is invalid")
    if receipt.get("status") != "verified" or receipt.get("mode") != "apply":
        raise LiveObservationError("live observations require a verified apply receipt")
    if (
        receipt.get("workflow_run_id") != workflow_run_id
        or receipt.get("workflow_run_attempt") != workflow_run_attempt
    ):
        raise LiveObservationError("live observation workflow binding is invalid")
    if receipt.get("commit_sha") != commit_sha or _COMMIT.fullmatch(commit_sha) is None:
        raise LiveObservationError("live observation source revision is invalid")
    image_match = _IMAGE.fullmatch(image_ref)
    if image_match is None or receipt.get("image_ref") != image_ref:
        raise LiveObservationError("live observation image binding is invalid")
    normalized_plan = _required_digest(plan_digest, "plan digest")
    normalized_context = _required_digest(context_digest, "context digest")
    if _required_digest(receipt.get("plan_digest"), "receipt plan digest") != normalized_plan:
        raise LiveObservationError("live observation plan binding is invalid")
    if (
        _required_digest(receipt.get("context_digest"), "receipt context digest")
        != normalized_context
    ):
        raise LiveObservationError("live observation context binding is invalid")
    peer_count = receipt.get("peer_count")
    peers = receipt.get("peers")
    if peer_count != 4 or not isinstance(peers, list) or len(peers) != 4:
        raise LiveObservationError("live observation peer evidence is incomplete")
    peer_services: list[str] = []
    peer_serials: dict[str, int] = {}
    for peer in peers:
        if not isinstance(peer, dict):
            raise LiveObservationError("live observation peer evidence is invalid")
        peer_service = peer.get("service")
        serial = peer.get("serial")
        if (
            peer_service not in _SERVICE_IDS
            or peer_service == service_id
            or peer_service in peer_serials
            or isinstance(serial, bool)
            or not isinstance(serial, int)
            or serial < 0
        ):
            raise LiveObservationError("live observation peer evidence is invalid")
        peer_services.append(str(peer_service))
        peer_serials[str(peer_service)] = serial
    before_manifest = _required_digest(
        receipt.get("before_manifest_sha256"), "before peer manifest"
    )
    after_manifest = _required_digest(receipt.get("after_manifest_sha256"), "after peer manifest")
    peer_projection = [
        {
            "service_id": peer["service"],
            "lineage_sha256": _required_digest(peer.get("lineage_sha256"), "peer lineage"),
            "resource_identity_sha256": _required_digest(
                peer.get("managed_resource_identity_sha256"), "peer resource identity"
            ),
            "managed_resource_count": peer.get("managed_resource_count"),
            "serial": peer.get("serial"),
        }
        for peer in peers
    ]
    common = {
        "service_id": service_id,
        "observed": True,
        "workflow_run_id": int(workflow_run_id),
        "workflow_run_attempt": int(workflow_run_attempt),
        "commit_sha": commit_sha,
    }
    image_digest = image_match.group(1)
    attestations = ["provenance", "sbom"]
    if service_id == "core-control-plane":
        attestations.append("resolved-models")
    observations = {
        "health": {
            **common,
            "kind": "health",
            "verification": "post-apply-health",
            "new_revision": True,
            "healthy_and_active": True,
        },
        "identity": {
            **common,
            "kind": "identity",
            "verification": "sealed-target-identity",
            "context_digest": normalized_context,
        },
        "image": {
            **common,
            "kind": "image",
            "verification": "attested-and-observed-image",
            "image_digest": image_digest,
            "attestations": attestations,
        },
        "offset": {
            **common,
            "kind": "offset",
            "verification": "peer-state-serials-preserved",
            "peer_serials": peer_serials,
            "before_manifest_sha256": before_manifest,
            "after_manifest_sha256": after_manifest,
        },
        "schema": {
            **common,
            "kind": "schema",
            "verification": "service-migration-upgrade",
            "migration_branch": service_id,
        },
        "source": {
            **common,
            "kind": "source",
            "verification": "protected-plan-source",
            "plan_digest": normalized_plan,
            "context_digest": normalized_context,
        },
        "topology": {
            **common,
            "kind": "topology",
            "verification": "four-peer-isolation",
            "peer_count": peer_count,
            "peer_services": sorted(peer_services),
            "peer_projection_sha256": _canonical_digest(peer_projection),
            "before_manifest_sha256": before_manifest,
            "after_manifest_sha256": after_manifest,
        },
    }
    return {
        "schema_version": "1.0.0",
        "service_id": service_id,
        "workflow_run_id": int(workflow_run_id),
        "workflow_run_attempt": int(workflow_run_attempt),
        "commit_sha": commit_sha,
        "image_digest": image_digest,
        "plan_digest": normalized_plan,
        "context_digest": normalized_context,
        "observations": observations,
    }


def main() -> int:
    """Seal one verified peer receipt as a live-observation artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise LiveObservationError("peer receipt must be an object")
        result = build_observations(
            receipt,
            service_id=args.service,
            commit_sha=args.commit_sha,
            image_ref=args.image_ref,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            plan_digest=args.plan_digest,
            context_digest=args.context_digest,
        )
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, json.JSONDecodeError, LiveObservationError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
