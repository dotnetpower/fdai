#!/usr/bin/env python3
"""Derive decision-evidence proofs from one exact protected deployment run."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fdai.delivery.decision_evidence_policy import (
    DeploymentDecisionEvidencePolicy,
    deployment_freshness_policy_digest,
    load_deployment_decision_evidence_policy,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationProof,
    EvidenceVerificationProofKind,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest

_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_MAX_FILE_BYTES = 1024 * 1024


class DeploymentDecisionEvidenceError(ValueError):
    """Protected deployment evidence is incomplete, stale, or inconsistent."""


def build_deployment_decision_evidence(
    *,
    evidence_dir: Path,
    source_run: dict[str, Any],
    expected_commit_sha: str,
    expected_run_id: int,
    expected_run_attempt: int,
    evaluated_at: datetime,
    policy: DeploymentDecisionEvidencePolicy,
) -> tuple[
    DecisionCriticalEvidenceReceipt,
    LiveEvidenceClaimRequirement,
    DecisionEvidenceVerificationProof,
    tuple[DecisionEvidenceVerificationProof, ...],
    str,
]:
    """Validate one source run and derive content-free independent proofs."""

    now = _aware_utc(evaluated_at)
    if _COMMIT.fullmatch(expected_commit_sha) is None:
        raise DeploymentDecisionEvidenceError("expected commit SHA is invalid")
    _validate_source_run(
        source_run,
        expected_commit_sha=expected_commit_sha,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        policy=policy,
    )
    metadata = _load_json(evidence_dir / "plan-metadata.json")
    preflight = _load_json(evidence_dir / "preflight-evidence.json")
    azure_preflight = _load_json(evidence_dir / "azure-preflight-evidence.json")
    claim = _load_json(evidence_dir / "apply-claim.json")
    apply_receipt = _load_json(evidence_dir / "apply-receipt.json")
    container_url = _load_container_url(evidence_dir / "decision-evidence-container-url.txt")
    plan_id, plan_digest = _validate_deployment_records(
        metadata=metadata,
        claim=claim,
        apply_receipt=apply_receipt,
        expected_commit_sha=expected_commit_sha,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )
    applied_at = _timestamp(apply_receipt, "applied_at")
    if now < applied_at or now > applied_at + timedelta(seconds=policy.freshness_ceiling_seconds):
        raise DeploymentDecisionEvidenceError(
            "protected deployment evidence is outside its freshness window"
        )
    artifact_digests = {
        "apply_claim": content_digest(claim),
        "apply_receipt": content_digest(apply_receipt),
        "azure_preflight": content_digest(azure_preflight),
        "plan_metadata": content_digest(metadata),
        "preflight": content_digest(preflight),
    }
    source_identity = f"{policy.source_identity_prefix}:{expected_run_id}"
    authentication_evidence_digest = content_digest(
        {
            "commit_sha": expected_commit_sha,
            "run_attempt": expected_run_attempt,
            "run_id": expected_run_id,
            "workflow_path": policy.source_workflow_path,
        }
    )
    evidence_digest = content_digest(
        {
            "apply_receipt_digest": artifact_digests["apply_receipt"],
            "plan_metadata_digest": artifact_digests["plan_metadata"],
        }
    )
    completeness_evidence_digest = content_digest(
        {
            "required_artifacts": tuple(sorted(artifact_digests)),
            "artifact_digests": artifact_digests,
        }
    )
    conflict_evidence_digest = content_digest(
        {
            "apply_status": "applied",
            "plan_digest": plan_digest,
            "plan_id": plan_id,
            "relationship_status": "clear",
        }
    )
    freshness_policy_digest = deployment_freshness_policy_digest(policy)
    scope_digest = content_digest(
        {
            "context_digest": _required_digest(metadata, "context_digest"),
            "plan_id": plan_id,
        }
    )
    receipt_values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": policy.authority_class,
        "source_identity": source_identity,
        "authentication_evidence_digest": authentication_evidence_digest,
        "scope_digest": scope_digest,
        "purpose_id": policy.purpose_id,
        "producer_id": policy.producer_id,
        "producer_version": policy.producer_version,
        "method_id": policy.method_id,
        "method_version": policy.method_version,
        "source_revision": expected_commit_sha,
        "evidence_digest": evidence_digest,
        "provenance_digest": content_digest(
            {
                "artifact_digests": artifact_digests,
                "source_identity": source_identity,
            }
        ),
        "event_at": applied_at,
        "evidence_cutoff": applied_at,
        "recorded_at": now,
        "fresh_until": applied_at + timedelta(seconds=policy.freshness_ceiling_seconds),
        "freshness_policy_id": policy.freshness_policy_id,
        "freshness_policy_version": policy.freshness_policy_version,
        "freshness_policy_digest": freshness_policy_digest,
        "freshness_ceiling_seconds": policy.freshness_ceiling_seconds,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": completeness_evidence_digest,
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": conflict_evidence_digest,
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    receipt = DecisionCriticalEvidenceReceipt.model_validate(
        {
            **receipt_values,
            "receipt_digest": decision_critical_evidence_receipt_digest(**receipt_values),
        }
    )
    requirement = LiveEvidenceClaimRequirement(
        allowed_authority_classes=(receipt.authority_class,),
        allowed_source_identities=(receipt.source_identity,),
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        producer_id=receipt.producer_id,
        producer_version=receipt.producer_version,
        method_id=receipt.method_id,
        method_version=receipt.method_version,
        source_revision=receipt.source_revision,
        freshness_policy_digest=receipt.freshness_policy_digest,
        freshness_ceiling_seconds=receipt.freshness_ceiling_seconds,
        minimum_completeness_basis_points=10_000,
    )
    authentication, readback = _proofs(receipt, issued_at=now, policy=policy)
    return receipt, requirement, authentication, readback, container_url


def _proofs(
    receipt: DecisionCriticalEvidenceReceipt,
    *,
    issued_at: datetime,
    policy: DeploymentDecisionEvidencePolicy,
) -> tuple[
    DecisionEvidenceVerificationProof,
    tuple[DecisionEvidenceVerificationProof, ...],
]:
    verifier_id = policy.verifier_id
    verifier_version = policy.verifier_version
    trust_anchor_id = policy.trust_anchor_id
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=receipt.receipt_digest,
            subject_digest=subject_digest,
            proof_digest=content_digest(
                {
                    "issued_at": issued_at.isoformat(),
                    "kind": kind.value,
                    "receipt_digest": receipt.receipt_digest,
                    "subject_digest": subject_digest,
                    "trust_anchor_id": trust_anchor_id,
                    "verifier_id": verifier_id,
                    "verifier_version": verifier_version,
                }
            ),
            verifier_id=verifier_id,
            verifier_version=verifier_version,
            trust_anchor_id=trust_anchor_id,
            issued_at=issued_at,
            valid_until=receipt.fresh_until,
        )
        for kind, subject_digest in subjects.items()
    )
    authentication = next(
        proof for proof in proofs if proof.kind is EvidenceVerificationProofKind.AUTHENTICATION
    )
    readback = tuple(
        proof for proof in proofs if proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
    )
    return authentication, readback


def _validate_source_run(
    source_run: dict[str, Any],
    *,
    expected_commit_sha: str,
    expected_run_id: int,
    expected_run_attempt: int,
    policy: DeploymentDecisionEvidencePolicy,
) -> None:
    expected = {
        "id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "head_sha": expected_commit_sha,
        "head_branch": "main",
        "path": policy.source_workflow_path,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
    }
    if any(source_run.get(field) != value for field, value in expected.items()):
        raise DeploymentDecisionEvidenceError(
            "source deployment run does not match the protected evidence request"
        )


def _validate_deployment_records(
    *,
    metadata: dict[str, Any],
    claim: dict[str, Any],
    apply_receipt: dict[str, Any],
    expected_commit_sha: str,
    expected_run_id: int,
    expected_run_attempt: int,
) -> tuple[str, str]:
    if metadata.get("schema_version") != "fdai.deployment-plan.v1":
        raise DeploymentDecisionEvidenceError("deployment plan metadata schema is invalid")
    if claim.get("schema_version") != "fdai.deployment-apply-claim.v1":
        raise DeploymentDecisionEvidenceError("deployment apply claim schema is invalid")
    if apply_receipt.get("schema_version") != "fdai.deployment-apply-receipt.v1":
        raise DeploymentDecisionEvidenceError("deployment apply receipt schema is invalid")
    plan_id = _required_text(metadata, "plan_id")
    plan_digest = _required_digest(metadata, "plan_digest")
    if _PLAN_ID.fullmatch(plan_id) is None:
        raise DeploymentDecisionEvidenceError("deployment plan id is invalid")
    if (
        metadata.get("commit_sha") != expected_commit_sha
        or claim.get("plan_id") != plan_id
        or apply_receipt.get("plan_id") != plan_id
        or claim.get("plan_digest") != plan_digest
        or apply_receipt.get("plan_digest") != plan_digest
        or claim.get("workflow_run_id") != str(expected_run_id)
        or claim.get("workflow_run_attempt") != str(expected_run_attempt)
        or apply_receipt.get("workflow_run_id") != str(expected_run_id)
        or apply_receipt.get("workflow_run_attempt") != str(expected_run_attempt)
        or apply_receipt.get("status") != "applied"
    ):
        raise DeploymentDecisionEvidenceError(
            "deployment plan, claim, receipt, and source run do not agree"
        )
    return plan_id, plan_digest


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(
            _read_bounded(path, maximum=_MAX_FILE_BYTES, label=path.name).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentDecisionEvidenceError(f"{path.name} is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise DeploymentDecisionEvidenceError(f"{path.name} MUST contain an object")
    return raw


def _load_container_url(path: Path) -> str:
    try:
        value = (
            _read_bounded(
                path,
                maximum=2048,
                label="decision evidence container URL",
            )
            .decode("utf-8")
            .strip()
            .rstrip("/")
        )
    except UnicodeDecodeError as exc:
        raise DeploymentDecisionEvidenceError(
            "decision evidence container URL is not valid UTF-8"
        ) from exc
    parsed = urlsplit(value)
    segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(segments) != 1
    ):
        raise DeploymentDecisionEvidenceError(
            "decision evidence container URL MUST identify one HTTPS container"
        )
    return value


def _read_bounded(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise DeploymentDecisionEvidenceError(f"{label} MUST be a bounded regular file") from exc
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise DeploymentDecisionEvidenceError(f"{label} MUST be a bounded regular file")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise DeploymentDecisionEvidenceError(f"{label} MUST be a bounded regular file")
    return content


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DeploymentDecisionEvidenceError(f"{field} MUST be non-empty text")
    return value


def _required_digest(raw: dict[str, Any], field: str) -> str:
    value = _required_text(raw, field)
    if _DIGEST.fullmatch(value) is None:
        raise DeploymentDecisionEvidenceError(f"{field} MUST be lowercase SHA-256")
    return value


def _timestamp(raw: dict[str, Any], field: str) -> datetime:
    try:
        return _aware_utc(datetime.fromisoformat(_required_text(raw, field).replace("Z", "+00:00")))
    except ValueError as exc:
        raise DeploymentDecisionEvidenceError(f"{field} MUST be an RFC 3339 timestamp") from exc


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DeploymentDecisionEvidenceError("deployment evidence time MUST include a timezone")
    return value.astimezone(UTC)


def _write(path: Path, payload: object) -> None:
    _write_bytes(
        path,
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def _write_bytes(path: Path, content: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise DeploymentDecisionEvidenceError(
            "deployment decision evidence output MUST be a new regular file"
        ) from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def main() -> int:
    """Validate a source deployment artifact and emit five proof inputs."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--source-run-json", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_run = _load_json(args.source_run_json)
        policy = load_deployment_decision_evidence_policy(args.policy)
        evidence = build_deployment_decision_evidence(
            evidence_dir=args.evidence_dir,
            source_run=source_run,
            expected_commit_sha=args.commit_sha,
            expected_run_id=args.run_id,
            expected_run_attempt=args.run_attempt,
            evaluated_at=datetime.fromisoformat(args.evaluated_at.replace("Z", "+00:00")),
            policy=policy,
        )
        receipt, requirement, authentication, readback, container_url = evidence
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        _write(args.output_dir / "receipt.json", receipt.model_dump(mode="json"))
        _write(args.output_dir / "requirement.json", requirement.model_dump(mode="json"))
        _write(
            args.output_dir / "authentication-proof.json",
            authentication.model_dump(mode="json"),
        )
        _write(
            args.output_dir / "readback-proofs.json",
            {"proofs": [proof.model_dump(mode="json") for proof in readback]},
        )
        _write_bytes(
            args.output_dir / "container-url.txt",
            (container_url + "\n").encode(),
        )
    except (OSError, DeploymentDecisionEvidenceError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DeploymentDecisionEvidenceError",
    "build_deployment_decision_evidence",
]
