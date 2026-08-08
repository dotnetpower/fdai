#!/usr/bin/env python3
"""Capture and verify that an independent service deployment leaves peers unchanged."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from service_contract import (
    ServiceContractError,
    load_matrix,
    resolve_service,
    validate_image_reference,
)

_MANIFEST_SCHEMA = "fdai.service-peer-state.v1"
_RECEIPT_SCHEMA = "fdai.service-peer-isolation.v1"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class PeerStateError(ValueError):
    """Raised when peer state evidence is incomplete, unsafe, or changed."""


@dataclass(frozen=True, slots=True)
class PeerCoordinate:
    """Remote backend coordinate for one non-selected runtime service."""

    service: str
    terraform_root: str
    backend_key: str


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PeerStateError(f"{path.name} must contain a JSON object")
    return payload


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(_canonical(payload))
    os.chmod(path, 0o600)


def peer_coordinates(selected_service: str, environment: str) -> tuple[PeerCoordinate, ...]:
    """Resolve the exact four peer backends for a selected runtime service."""
    resolve_service(selected_service, environment)
    services = load_matrix()["services"]
    peers = tuple(
        PeerCoordinate(
            service=service,
            terraform_root=(contract := resolve_service(service, environment)).terraform_root,
            backend_key=contract.backend_key,
        )
        for service in sorted(services)
        if service != selected_service
    )
    if len(peers) != 4:
        raise PeerStateError("peer state evidence requires exactly four runtime peers")
    return peers


def _managed_resource_count(state: dict[str, Any]) -> int:
    resources = state.get("resources")
    if not isinstance(resources, list):
        raise PeerStateError("raw Terraform state resources must be an array")
    count = 0
    for resource in resources:
        if not isinstance(resource, dict):
            raise PeerStateError("raw Terraform state contains an invalid resource")
        if resource.get("mode", "managed") != "managed":
            continue
        instances = resource.get("instances")
        if not isinstance(instances, list):
            raise PeerStateError("raw Terraform state resource instances must be an array")
        count += len(instances)
    return count


def _state_evidence(path: Path) -> dict[str, Any]:
    state = _object(path)
    if state.get("version") != 4:
        raise PeerStateError("raw Terraform state must use version 4")
    serial = state.get("serial")
    lineage = state.get("lineage")
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
        raise PeerStateError("raw Terraform state serial must be a non-negative integer")
    if not isinstance(lineage, str) or not lineage:
        raise PeerStateError("raw Terraform state lineage must be non-empty")
    return {
        "state_sha256": _digest(state),
        "serial": serial,
        "lineage_sha256": hashlib.sha256(lineage.encode()).hexdigest(),
        "managed_resource_count": _managed_resource_count(state),
    }


def capture_manifest(
    *,
    selected_service: str,
    environment: str,
    phase: str,
    state_dir: Path,
) -> dict[str, Any]:
    """Reduce four raw peer states to non-sensitive deterministic evidence."""
    if phase not in {"before", "after"}:
        raise PeerStateError("peer state phase must be before or after")
    coordinates = peer_coordinates(selected_service, environment)
    expected_names = {f"{coordinate.service}.json" for coordinate in coordinates}
    actual_names = {path.name for path in state_dir.glob("*.json")}
    if actual_names != expected_names:
        raise PeerStateError("peer state directory must contain exactly the four peer states")
    peers = []
    for coordinate in coordinates:
        peers.append(
            {
                "service": coordinate.service,
                "terraform_root": coordinate.terraform_root,
                "backend_key": coordinate.backend_key,
                **_state_evidence(state_dir / f"{coordinate.service}.json"),
            }
        )
    return {
        "schema_version": _MANIFEST_SCHEMA,
        "selected_service": selected_service,
        "environment": environment,
        "phase": phase,
        "peer_count": len(peers),
        "peers": peers,
    }


def _validated_manifest(
    payload: dict[str, Any], *, selected_service: str, environment: str, phase: str
) -> list[dict[str, Any]]:
    expected_services = {
        coordinate.service for coordinate in peer_coordinates(selected_service, environment)
    }
    if (
        payload.get("schema_version") != _MANIFEST_SCHEMA
        or payload.get("selected_service") != selected_service
        or payload.get("environment") != environment
        or payload.get("phase") != phase
        or payload.get("peer_count") != 4
    ):
        raise PeerStateError(f"{phase} peer state manifest context is invalid")
    peers = payload.get("peers")
    if not isinstance(peers, list) or len(peers) != 4:
        raise PeerStateError(f"{phase} peer state manifest must contain four peers")
    services = {peer.get("service") for peer in peers if isinstance(peer, dict)}
    if services != expected_services or not all(isinstance(peer, dict) for peer in peers):
        raise PeerStateError(f"{phase} peer state manifest has an invalid peer set")
    return peers


def verify_peer_isolation(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    mode: str,
    selected_service: str,
    environment: str,
    repository: str,
    commit_sha: str,
    image_ref: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    plan_run_id: str,
    plan_run_attempt: str,
    plan_digest: str,
    context_digest: str,
) -> dict[str, Any]:
    """Bind unchanged peer state evidence to one exact protected plan or apply run."""
    if mode not in {"plan", "apply"}:
        raise PeerStateError("peer isolation receipt mode must be plan or apply")
    if _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise PeerStateError("commit_sha must be a lowercase 40-character git SHA")
    for name, value in (
        ("workflow_run_id", workflow_run_id),
        ("workflow_run_attempt", workflow_run_attempt),
        ("plan_run_id", plan_run_id),
        ("plan_run_attempt", plan_run_attempt),
    ):
        if not value.isdigit() or int(value) < 1:
            raise PeerStateError(f"{name} must be a positive integer")
    if mode == "plan" and (workflow_run_id, workflow_run_attempt) != (
        plan_run_id,
        plan_run_attempt,
    ):
        raise PeerStateError("plan receipt must bind its own workflow run")
    for name, value in (("plan_digest", plan_digest), ("context_digest", context_digest)):
        if _DIGEST_PATTERN.fullmatch(value) is None:
            raise PeerStateError(f"{name} must be a lowercase SHA-256 digest")
    contract = resolve_service(selected_service, environment)
    validate_image_reference(contract, repository, image_ref)
    before_peers = _validated_manifest(
        before,
        selected_service=selected_service,
        environment=environment,
        phase="before",
    )
    after_peers = _validated_manifest(
        after,
        selected_service=selected_service,
        environment=environment,
        phase="after",
    )
    if before_peers != after_peers:
        before_by_service = {peer["service"]: peer for peer in before_peers}
        after_by_service = {peer["service"]: peer for peer in after_peers}
        changed: list[str] = []
        evidence_fields = (
            "state_sha256",
            "serial",
            "lineage_sha256",
            "managed_resource_count",
        )
        for service in sorted(before_by_service):
            before_peer = before_by_service[service]
            after_peer = after_by_service[service]
            changed_fields = [
                field
                for field in evidence_fields
                if before_peer.get(field) != after_peer.get(field)
            ]
            if changed_fields:
                transitions = ", ".join(
                    f"{field}={before_peer.get(field)}->{after_peer.get(field)}"
                    for field in changed_fields
                )
                changed.append(f"{service} ({transitions})")
        raise PeerStateError(f"peer state drift detected for: {'; '.join(changed)}")
    return {
        "schema_version": _RECEIPT_SCHEMA,
        "status": "verified",
        "mode": mode,
        "service": selected_service,
        "environment": environment,
        "repository": repository,
        "commit_sha": commit_sha,
        "image_ref": image_ref,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "plan_run_id": plan_run_id,
        "plan_run_attempt": plan_run_attempt,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "peer_count": 4,
        "before_manifest_sha256": _digest(before),
        "after_manifest_sha256": _digest(after),
        "peers": before_peers,
    }


def main() -> int:
    """Resolve peer coordinates, capture state evidence, or verify isolation."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    coordinates = commands.add_parser("coordinates")
    coordinates.add_argument("--service", required=True)
    coordinates.add_argument("--environment", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--service", required=True)
    capture.add_argument("--environment", required=True)
    capture.add_argument("--phase", choices=("before", "after"), required=True)
    capture.add_argument("--state-dir", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--before", type=Path, required=True)
    verify.add_argument("--after", type=Path, required=True)
    verify.add_argument("--mode", choices=("plan", "apply"), required=True)
    verify.add_argument("--service", required=True)
    verify.add_argument("--environment", required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--commit-sha", required=True)
    verify.add_argument("--image-ref", required=True)
    verify.add_argument("--workflow-run-id", required=True)
    verify.add_argument("--workflow-run-attempt", required=True)
    verify.add_argument("--plan-run-id", required=True)
    verify.add_argument("--plan-run-attempt", required=True)
    verify.add_argument("--plan-digest", required=True)
    verify.add_argument("--context-digest", required=True)
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "coordinates":
            for coordinate in peer_coordinates(args.service, args.environment):
                print(
                    f"{coordinate.service}\t{coordinate.terraform_root}\t{coordinate.backend_key}"
                )
        elif args.command == "capture":
            _write_private(
                args.output,
                capture_manifest(
                    selected_service=args.service,
                    environment=args.environment,
                    phase=args.phase,
                    state_dir=args.state_dir,
                ),
            )
        else:
            _write_private(
                args.output,
                verify_peer_isolation(
                    before=_object(args.before),
                    after=_object(args.after),
                    mode=args.mode,
                    selected_service=args.service,
                    environment=args.environment,
                    repository=args.repository,
                    commit_sha=args.commit_sha,
                    image_ref=args.image_ref,
                    workflow_run_id=args.workflow_run_id,
                    workflow_run_attempt=args.workflow_run_attempt,
                    plan_run_id=args.plan_run_id,
                    plan_run_attempt=args.plan_run_attempt,
                    plan_digest=args.plan_digest,
                    context_digest=args.context_digest,
                ),
            )
    except (OSError, json.JSONDecodeError, ServiceContractError, PeerStateError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
