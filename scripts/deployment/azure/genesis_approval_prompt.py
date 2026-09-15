#!/usr/bin/env python3
"""Prompt for one current exact Genesis checkpoint approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from genesis_checks import trusted_tool
from genesis_runner_image_review import show_image_vm_selection

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE = re.compile(r"[0-9a-f]{40}")
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_EVIDENCE_FIELDS = {
    "runner-image": ("review_digest", "plan_digest"),
    "foundation-apply": ("review_digest", "plan_digest"),
    "runner-enrollment": ("foundation_receipt_digest",),
    "foundation-state": (
        "foundation_receipt_digest",
        "enrollment_receipt_digest",
    ),
    "application-apply": (
        "context_digest",
        "plan_digest",
        "plan_reference_digest",
    ),
    "repository-config": ("plan_digest",),
    "entra-config": ("plan_digest",),
}


def create_approval(
    *,
    stage: str,
    evidence: dict[str, str],
    run_binding: str,
    source_commit: str,
    actor_digest: str,
    output: Path,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stderr,
    now: datetime | None = None,
) -> dict[str, object]:
    """Prompt on a TTY and write one actor-bound approval for exact evidence."""

    if stage not in _EVIDENCE_FIELDS or set(evidence) != set(_EVIDENCE_FIELDS[stage]):
        raise ValueError("Genesis prompt evidence fields are invalid")
    if any(_DIGEST.fullmatch(value) is None for value in evidence.values()):
        raise ValueError("Genesis prompt evidence digest is invalid")
    if (
        _DIGEST.fullmatch(run_binding) is None
        or _SOURCE.fullmatch(source_commit) is None
        or _DIGEST.fullmatch(actor_digest) is None
    ):
        raise ValueError("Genesis prompt context is invalid")
    if not input_stream.isatty():
        raise ValueError("Genesis exact approval requires an interactive terminal")
    digest_text = " ".join(f"{name}={value}" for name, value in sorted(evidence.items()))
    prompt = (
        f"Approve exact {stage} checkpoint? {digest_text}\n"
        "Type the exact stage name to approve, or anything else to deny: "
    )
    output_stream.write(prompt)
    output_stream.flush()
    answer = input_stream.readline().strip()
    if answer != stage:
        raise PermissionError("Genesis exact checkpoint approval was not granted")
    approved_at = (now or datetime.now(UTC)).replace(microsecond=0)
    value: dict[str, object] = {
        "schema_version": "fdai.genesis-approval.v1",
        "run_binding": run_binding,
        "source_commit": source_commit,
        "stage": stage,
        "approved": True,
        "approved_at": approved_at.isoformat(),
        "expires_at": (approved_at + timedelta(minutes=30)).isoformat(),
        "actor_digest": actor_digest,
        "evidence": evidence,
    }
    write_private_output(output, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return value


def current_actor_digest(run_binding: str) -> str:
    """Bind approval to the currently authenticated Azure human without persisting identity."""

    environment = _azure_identity_environment()
    azure_cli = trusted_tool("az")
    account = subprocess.run(
        [
            azure_cli,
            "account",
            "show",
            "--query",
            "{tenantId:tenantId,type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    principal = subprocess.run(
        [
            azure_cli,
            "ad",
            "signed-in-user",
            "show",
            "--query",
            "id",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    if account.returncode != 0 or principal.returncode != 0:
        raise ValueError("authenticated Azure operator identity is unavailable")
    value = json.loads(account.stdout)
    object_id = principal.stdout.strip().casefold()
    if (
        not isinstance(value, dict)
        or value.get("type") != "user"
        or not isinstance(value.get("tenantId"), str)
        or re.fullmatch(_UUID, str(value["tenantId"])) is None
        or re.fullmatch(_UUID, object_id) is None
    ):
        raise ValueError("Genesis exact approval requires an authenticated human operator")
    return hashlib.sha256(
        f"{run_binding}:{str(value['tenantId']).casefold()}:{object_id}".encode()
    ).hexdigest()


def _azure_identity_environment() -> dict[str, str]:
    azure_config = Path(os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))).resolve(
        strict=True
    )
    if not azure_config.is_dir() or azure_config.stat().st_mode & 0o022:
        raise ValueError("Azure CLI configuration directory is not trusted")
    return {
        "AZURE_CONFIG_DIR": str(azure_config),
        "HOME": str(azure_config.parent),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }


def _load_status(path: Path) -> dict[str, object]:
    """Read a bounded private Genesis status record."""

    return load_json_object(
        read_private_bytes(path, max_bytes=1_048_576),
        label="Genesis status",
        max_bytes=1_048_576,
    )


def _approval_from_status(status: dict[str, object]) -> tuple[str, dict[str, str]]:
    report = status.get("foundation_report")
    if not isinstance(report, dict):
        raise ValueError("Genesis status has no private Foundation report")
    current = status.get("current_stage")
    if current == "runner-image-apply":
        stage = "runner-image"
        source = report.get("runner_image_plan")
    elif current == "foundation-apply":
        stage = "foundation-apply"
        source = report.get("foundation_plan")
    elif current == "runner-enrollment":
        stage = "runner-enrollment"
        source = report.get("foundation_apply")
    elif current == "foundation-state":
        stage = "foundation-state"
        source = report
    else:
        raise ValueError("Genesis status is not at an approvable checkpoint")
    if not isinstance(source, dict):
        raise ValueError("Genesis status checkpoint evidence is unavailable")
    if stage in {"runner-image", "foundation-apply"}:
        evidence = {name: source.get(name) for name in _EVIDENCE_FIELDS[stage]}
    elif stage == "runner-enrollment":
        evidence = {"foundation_receipt_digest": source.get("receipt_digest")}
    else:
        foundation = report.get("foundation_apply")
        enrollment = report.get("runner_enrollment")
        if not isinstance(foundation, dict) or not isinstance(enrollment, dict):
            raise ValueError("Genesis state-handoff evidence is unavailable")
        evidence = {
            "foundation_receipt_digest": foundation.get("receipt_digest"),
            "enrollment_receipt_digest": enrollment.get("receipt_digest"),
        }
    if any(not isinstance(value, str) for value in evidence.values()):
        raise ValueError("Genesis status checkpoint evidence is invalid")
    return stage, {name: str(value) for name, value in evidence.items()}


def _approval_from_residual_review(
    path: Path, *, foundation: bool = False
) -> tuple[str, str, dict[str, str]]:
    """Bind a fresh residual review and its saved plan to the existing human-only prompt."""
    from genesis_foundation_recovery_successor import group_evidence_valid

    review = _load_status(path)
    digest = review.pop("review_digest", None)
    if (
        not isinstance(digest, str)
        or canonical_digest(review) != digest
        or review.get("schema_version")
        != (
            "fdai.foundation-recovery-review.v1"
            if foundation
            else "fdai.runner-image-residual-review.v1"
        )
        or review.get("state") != "review"
        or review.get("apply_authorized") is not False
        or review.get("mutation_performed") is not False
        or review.get("deployment_ready") is not False
        or review.get("original_state_unchanged") is not True
        or (foundation and not group_evidence_valid(review))
    ):
        raise ValueError("Genesis residual review integrity or state is invalid")
    source = review.get("recovery_source_commit")
    if not isinstance(source, str) or _SOURCE.fullmatch(source) is None:
        raise ValueError("Genesis residual recovery source is invalid")
    for field in ("plan_digest", "provider_digest", "original_lineage_digest"):
        value = review.get(field)
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise ValueError("Genesis residual review execution binding is invalid")
    created = datetime.fromisoformat(str(review.get("created_at")))
    expires = datetime.fromisoformat(str(review.get("expires_at")))
    if (
        created.tzinfo != UTC
        or expires.tzinfo != UTC
        or not created <= datetime.now(UTC) < expires
        or not timedelta(0) < expires - created <= timedelta(hours=1)
    ):
        raise ValueError("Genesis residual review is expired or has an invalid window")
    plan = read_private_bytes(
        path.parent / ("recovery.tfplan" if foundation else "residual.tfplan"),
        max_bytes=64 * 1024 * 1024,
    )
    if hashlib.sha256(plan).hexdigest() != review["plan_digest"]:
        raise ValueError("Genesis residual saved plan differs from its review")
    return digest, source, {"review_digest": digest, "plan_digest": str(review["plan_digest"])}


def _approval_from_recovered_foundation(path: Path) -> tuple[str, str, dict[str, str]]:
    """Bind a separate enrollment approval to a verified recovery receipt and current source."""
    from fdai_deployment_cli.source_input import inspect_source

    receipt = _load_status(path)
    digest = receipt.pop("receipt_digest", None)
    if (
        not isinstance(digest, str)
        or canonical_digest(receipt) != digest
        or receipt.get("schema_version") != "fdai.foundation-recovery-receipt.v1"
        or receipt.get("state") != "verified"
        or receipt.get("control_plane_readback_verified") is not True
        or receipt.get("zero_change_verified") is not True
        or receipt.get("remote_backend_authority_verified") is not False
        or receipt.get("runner_attested") is not False
        or receipt.get("deployment_ready") is not False
    ):
        raise ValueError("recovered Foundation receipt is invalid for enrollment approval")
    source = inspect_source(Path(__file__).resolve().parents[3])
    return digest, source.commit, {"foundation_receipt_digest": digest}


def _recovered_state_evidence(path: Path, foundation_digest: str) -> dict[str, str]:
    """Require recovered-host attestation before offering state migration approval."""
    from genesis_foundation_state_contract import load_receipt

    receipt = load_receipt(
        path, schema="fdai.genesis-runner-enrollment-receipt.v1", expected_digest=None
    )
    if (
        receipt.get("state") != "attested"
        or receipt.get("foundation_receipt_digest") != foundation_digest
        or receipt.get("foundation_evidence_schema") != "fdai.foundation-recovery-receipt.v1"
        or any(
            receipt.get(field) is not True
            for field in (
                "identity_attested",
                "services_attested",
                "manual_host_readback_verified",
                "effect_verified",
            )
        )
        or receipt.get("mutation_performed") is not False
    ):
        raise ValueError("recovered host receipt is invalid for state migration approval")
    return {
        "foundation_receipt_digest": foundation_digest,
        "enrollment_receipt_digest": str(receipt["receipt_digest"]),
    }


def main() -> int:
    """Prompt from a private checkpoint, recovery review or verified recovery receipt."""

    parser = argparse.ArgumentParser(description=__doc__)
    context = parser.add_mutually_exclusive_group(required=True)
    context.add_argument("--status", type=Path)
    context.add_argument("--residual-review", type=Path)
    context.add_argument("--foundation-recovery-review", type=Path)
    context.add_argument("--recovered-foundation-receipt", type=Path)
    parser.add_argument("--recovered-enrollment-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.recovered_enrollment_receipt is not None and args.recovered_foundation_receipt is None:
        raise ValueError("recovered enrollment evidence requires its recovered Foundation receipt")
    if args.recovered_foundation_receipt is not None:
        run_binding, source_commit, evidence = _approval_from_recovered_foundation(
            args.recovered_foundation_receipt
        )
        stage = "runner-enrollment"
        if args.recovered_enrollment_receipt is not None:
            evidence = _recovered_state_evidence(args.recovered_enrollment_receipt, run_binding)
            stage = "foundation-state"
    elif args.foundation_recovery_review is not None:
        run_binding, source_commit, evidence = _approval_from_residual_review(
            args.foundation_recovery_review, foundation=True
        )
        stage = "foundation-apply"
    elif args.residual_review is not None:
        run_binding, source_commit, evidence = _approval_from_residual_review(args.residual_review)
        stage = "runner-image"
    else:
        status = _load_status(args.status)
        status_binding = status.get("target_binding")
        status_source = status.get("source_commit")
        if not isinstance(status_binding, str) or not isinstance(status_source, str):
            raise ValueError("Genesis status context is invalid")
        run_binding, source_commit = status_binding, status_source
        stage, evidence = _approval_from_status(status)
        if stage == "runner-image":
            show_image_vm_selection(
                status=status, work_dir=args.status.parent, evidence=evidence, output=sys.stderr
            )
    create_approval(
        stage=stage,
        evidence=evidence,
        run_binding=run_binding,
        source_commit=source_commit,
        actor_digest=current_actor_digest(run_binding),
        output=args.output,
    )
    details = args.output.lstat()
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
        raise ValueError("Genesis approval output is not private")
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
