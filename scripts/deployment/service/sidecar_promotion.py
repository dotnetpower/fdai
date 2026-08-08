#!/usr/bin/env python3
"""Seal and verify separately approved ClamAV digest promotions and rollback."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from deployment_recovery import rollback_command
from plan_bundle import PlanBundleError, planned_sidecar_contract
from service_contract import ServiceContractError, resolve_service

_SCHEMA_VERSION = "fdai.sidecar-promotion.v1"
_APPROVAL_SCHEMA = "fdai.sidecar-promotion-approval.v1"
_ATTESTATION_SCHEMA = "fdai.sidecar-attestation-proof.v1"
_SCAN_SCHEMA = "fdai.sidecar-scan-proof.v1"
_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:([0-9a-f]{64})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SERVICE = "document-processing-worker"
_SIDECAR = "clamav"


class SidecarPromotionError(ValueError):
    """Raised when promotion or rollback evidence is incomplete or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SidecarPromotionError(f"{path.name} must contain a JSON object")
    return value


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise SidecarPromotionError(f"{label} is missing")
    return value


def _image_digest(image_ref: str, *, label: str) -> str:
    match = _DIGEST_IMAGE.fullmatch(image_ref)
    if match is None:
        raise SidecarPromotionError(f"{label} must be pinned by sha256 digest")
    return f"sha256:{match.group(1)}"


def _sidecar(resource: dict[str, Any]) -> dict[str, Any]:
    templates = resource.get("template")
    template = templates[0] if isinstance(templates, list) and len(templates) == 1 else None
    containers = template.get("container") if isinstance(template, dict) else None
    if not isinstance(containers, list):
        raise SidecarPromotionError("promotion plan has no container set")
    matches = [
        container
        for container in containers
        if isinstance(container, dict) and container.get("name") == _SIDECAR
    ]
    if len(matches) != 1:
        raise SidecarPromotionError("promotion plan must contain exactly one ClamAV sidecar")
    return matches[0]


def _sealed_sidecar(context: dict[str, Any]) -> dict[str, str]:
    if context.get("service") != _SERVICE:
        raise SidecarPromotionError("promotion context must target document-processing-worker")
    target = context.get("target")
    sidecars = target.get("sidecar_containers") if isinstance(target, dict) else None
    if not isinstance(sidecars, list) or len(sidecars) != 1 or not isinstance(sidecars[0], dict):
        raise SidecarPromotionError("sealed plan context must contain one sidecar contract")
    sidecar = sidecars[0]
    expected_keys = {"name", "image_ref", "config_digest", "probe_digest"}
    if set(sidecar) != expected_keys or sidecar.get("name") != _SIDECAR:
        raise SidecarPromotionError("sealed plan context has an invalid ClamAV contract")
    if (
        _DIGEST_IMAGE.fullmatch(str(sidecar.get("image_ref", ""))) is None
        or _SHA256.fullmatch(str(sidecar.get("config_digest", ""))) is None
        or _SHA256.fullmatch(str(sidecar.get("probe_digest", ""))) is None
    ):
        raise SidecarPromotionError("sealed plan context has an invalid ClamAV contract")
    return {key: str(sidecar[key]) for key in sorted(expected_keys)}


def _validate_approval(
    approval: dict[str, Any],
    *,
    old_image_ref: str,
    new_image_ref: str,
    plan_context_digest: str,
) -> None:
    expected_keys = {
        "schema_version",
        "status",
        "service",
        "sidecar",
        "old_image_ref",
        "new_image_ref",
        "plan_context_digest",
        "approval_id",
        "requested_by",
        "approved_by",
    }
    if set(approval) != expected_keys:
        raise SidecarPromotionError("sidecar promotion approval has unknown or missing fields")
    expected = {
        "schema_version": _APPROVAL_SCHEMA,
        "status": "approved",
        "service": _SERVICE,
        "sidecar": _SIDECAR,
        "old_image_ref": old_image_ref,
        "new_image_ref": new_image_ref,
        "plan_context_digest": plan_context_digest,
    }
    if any(approval.get(key) != value for key, value in expected.items()):
        raise SidecarPromotionError("sidecar promotion approval does not match exact request")
    approval_id = _required(approval, "approval_id", label="approval id")
    requester = _required(approval, "requested_by", label="promotion requester")
    approvers = approval.get("approved_by")
    if (
        not approval_id
        or not isinstance(approvers, list)
        or not approvers
        or not all(isinstance(approver, str) and approver for approver in approvers)
        or len(set(approvers)) != len(approvers)
        or requester in approvers
    ):
        raise SidecarPromotionError("sidecar promotion requires separate named approval")


def _validate_attestation(attestation: dict[str, Any], *, new_digest: str) -> None:
    expected_keys = {
        "schema_version",
        "verified",
        "subject_digest",
        "source_revision",
        "signer_workflow",
        "predicate_type",
    }
    if set(attestation) != expected_keys:
        raise SidecarPromotionError("sidecar attestation proof has unknown or missing fields")
    if (
        attestation.get("schema_version") != _ATTESTATION_SCHEMA
        or attestation.get("verified") is not True
        or attestation.get("subject_digest") != new_digest
        or attestation.get("predicate_type") != "https://slsa.dev/provenance/v1"
        or _COMMIT.fullmatch(str(attestation.get("source_revision", ""))) is None
    ):
        raise SidecarPromotionError("sidecar attestation does not verify the new digest")
    _required(attestation, "signer_workflow", label="attestation signer workflow")


def _validate_scan(scan: dict[str, Any], *, new_digest: str) -> None:
    expected_keys = {
        "schema_version",
        "passed",
        "subject_digest",
        "scanner",
        "severities",
        "report_digest",
    }
    if set(scan) != expected_keys:
        raise SidecarPromotionError("sidecar scan proof has unknown or missing fields")
    if (
        scan.get("schema_version") != _SCAN_SCHEMA
        or scan.get("passed") is not True
        or scan.get("subject_digest") != new_digest
        or scan.get("scanner") != "trivy"
        or scan.get("severities") != ["MEDIUM", "HIGH", "CRITICAL"]
        or _SHA256.fullmatch(str(scan.get("report_digest", ""))) is None
    ):
        raise SidecarPromotionError("sidecar scan does not prove the new digest is clean")


def build_promotion_context(
    *,
    plan: dict[str, Any],
    plan_context: dict[str, Any],
    plan_context_digest: str,
    approval: dict[str, Any],
    attestation: dict[str, Any],
    scan: dict[str, Any],
    old_image_ref: str,
    new_image_ref: str,
) -> dict[str, Any]:
    """Seal one sidecar-only digest change with independent evidence and rollback."""
    if _SHA256.fullmatch(plan_context_digest) is None:
        raise SidecarPromotionError("plan context digest must be a lowercase SHA-256 value")
    old_digest = _image_digest(old_image_ref, label="old ClamAV image")
    new_digest = _image_digest(new_image_ref, label="new ClamAV image")
    if old_digest == new_digest:
        raise SidecarPromotionError("ClamAV promotion requires distinct old and new digests")
    sealed_sidecar = _sealed_sidecar(plan_context)
    if sealed_sidecar["image_ref"] != old_image_ref:
        raise SidecarPromotionError("old ClamAV digest does not match sealed plan context")

    environment = _required(plan_context, "environment", label="deployment environment")
    contract = resolve_service(_SERVICE, environment)
    changes = plan.get("resource_changes")
    if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict):
        raise SidecarPromotionError("promotion plan must contain exactly one resource change")
    entry = changes[0]
    change = entry.get("change")
    if entry.get("address") != contract.allowed_resource_address or not isinstance(change, dict):
        raise SidecarPromotionError("promotion plan targets an unapproved resource")
    if change.get("actions") != ["update"]:
        raise SidecarPromotionError("promotion plan must contain one update action")
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise SidecarPromotionError("promotion plan must contain before and after resources")
    before_sidecar = _sidecar(before)
    try:
        before_contract = planned_sidecar_contract(before_sidecar, name=_SIDECAR)
    except PlanBundleError as exc:
        raise SidecarPromotionError(str(exc)) from exc
    if before_contract != sealed_sidecar or before_sidecar.get("image") != old_image_ref:
        raise SidecarPromotionError("promotion plan old sidecar does not match sealed context")
    expected_after = copy.deepcopy(before)
    _sidecar(expected_after)["image"] = new_image_ref
    if after != expected_after:
        raise SidecarPromotionError("promotion plan contains unknown configuration changes")
    if plan.get("resource_drift") not in (None, []) or plan.get("deferred_changes") not in (
        None,
        [],
    ):
        raise SidecarPromotionError("promotion plan contains unbounded drift or deferred changes")

    _validate_approval(
        approval,
        old_image_ref=old_image_ref,
        new_image_ref=new_image_ref,
        plan_context_digest=plan_context_digest,
    )
    _validate_attestation(attestation, new_digest=new_digest)
    _validate_scan(scan, new_digest=new_digest)
    target = plan_context.get("target")
    if not isinstance(target, dict):
        raise SidecarPromotionError("sealed plan context has no target")
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "ready",
        "service": _SERVICE,
        "environment": environment,
        "sidecar": _SIDECAR,
        "old_image_ref": old_image_ref,
        "new_image_ref": new_image_ref,
        "plan_context_digest": plan_context_digest,
        "promotion_plan_digest": _digest(plan),
        "target": {
            "service_resource_id": _required(
                target, "service_resource_id", label="service resource id"
            ),
            "service_name": _required(target, "service_name", label="service name"),
            "sidecar_contract": sealed_sidecar,
        },
        "evidence": {
            "approval_digest": _digest(approval),
            "attestation_digest": _digest(attestation),
            "scan_digest": _digest(scan),
        },
        "rollback": {
            "image_ref": old_image_ref,
            "sidecar_contract": sealed_sidecar,
        },
    }


def verify_promotion_context(
    promotion_context: dict[str, Any],
    **inputs: Any,
) -> None:
    """Recompute every promotion binding before the separate apply lane proceeds."""
    if promotion_context != build_promotion_context(**inputs):
        raise SidecarPromotionError("sealed sidecar promotion context does not match inputs")


def promotion_rollback_command(
    *,
    promotion_context: dict[str, Any],
    snapshot: dict[str, Any],
    revision_suffix: str,
) -> list[str]:
    """Build rollback only when the snapshot proves the exact pre-promotion sidecar."""
    if promotion_context.get("schema_version") != _SCHEMA_VERSION:
        raise SidecarPromotionError("sidecar promotion context schema is invalid")
    target = promotion_context.get("target")
    rollback = promotion_context.get("rollback")
    if not isinstance(target, dict) or not isinstance(rollback, dict):
        raise SidecarPromotionError("sidecar promotion rollback context is incomplete")
    if (
        snapshot.get("service") != _SERVICE
        or str(snapshot.get("service_resource_id", "")).lower()
        != str(target.get("service_resource_id", "")).lower()
        or snapshot.get("service_name") != target.get("service_name")
    ):
        raise SidecarPromotionError("rollback snapshot does not match promotion target")
    sidecar_contracts = snapshot.get("previous_sidecar_contracts")
    expected_contract = rollback.get("sidecar_contract")
    if (
        not isinstance(sidecar_contracts, dict)
        or sidecar_contracts.get(_SIDECAR) != expected_contract
        or rollback.get("image_ref") != promotion_context.get("old_image_ref")
    ):
        raise SidecarPromotionError("rollback snapshot does not prove exact old ClamAV digest")
    return rollback_command(snapshot, revision_suffix=revision_suffix)


def _promotion_inputs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "plan": _object(args.plan_json),
        "plan_context": _object(args.plan_context),
        "plan_context_digest": _file_digest(args.plan_context),
        "approval": _object(args.approval),
        "attestation": _object(args.attestation),
        "scan": _object(args.scan),
        "old_image_ref": args.old_image_ref,
        "new_image_ref": args.new_image_ref,
    }


def main() -> int:
    """Seal or verify a promotion, or emit its bounded rollback command."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seal", "verify"):
        subcommand = commands.add_parser(name)
        subcommand.add_argument("--plan-json", type=Path, required=True)
        subcommand.add_argument("--plan-context", type=Path, required=True)
        subcommand.add_argument("--approval", type=Path, required=True)
        subcommand.add_argument("--attestation", type=Path, required=True)
        subcommand.add_argument("--scan", type=Path, required=True)
        subcommand.add_argument("--old-image-ref", required=True)
        subcommand.add_argument("--new-image-ref", required=True)
        subcommand.add_argument("--promotion-context", type=Path, required=name == "verify")
        subcommand.add_argument("--output", type=Path, required=name == "seal")
    rollback = commands.add_parser("rollback-command")
    rollback.add_argument("--promotion-context", type=Path, required=True)
    rollback.add_argument("--snapshot", type=Path, required=True)
    rollback.add_argument("--revision-suffix", required=True)
    args = parser.parse_args()
    try:
        if args.command == "seal":
            promotion_context = build_promotion_context(**_promotion_inputs(args))
            args.output.write_bytes(_canonical(promotion_context))
        elif args.command == "verify":
            verify_promotion_context(_object(args.promotion_context), **_promotion_inputs(args))
        else:
            rollback_values = promotion_rollback_command(
                promotion_context=_object(args.promotion_context),
                snapshot=_object(args.snapshot),
                revision_suffix=args.revision_suffix,
            )
            sys.stdout.buffer.write("\0".join(rollback_values).encode() + b"\0")
    except (
        OSError,
        json.JSONDecodeError,
        PlanBundleError,
        ServiceContractError,
        SidecarPromotionError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
