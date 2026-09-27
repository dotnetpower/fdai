"""Govern one separately approved residual apply after a partial Terraform effect."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.standalone_host_state import (
    file_digest,
    moment,
    private_json,
    replace_private_json,
)
from fdai_deployment_cli.standalone_host_values import plan_summary
from fdai_deployment_cli.standalone_review import validate_plan_review

_STAGES = frozenset({"substrate", "runtime", "database", "application"})
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")


def seal_terraform_plan(path: Path) -> None:
    """Validate and seal one Terraform-created binary plan before trust binding."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("Terraform plan output is unavailable") from exc
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size <= 0
        ):
            raise ValueError("Terraform plan output is invalid")
        os.fchmod(stream.fileno(), 0o600)
        after = os.fstat(stream.fileno())
    if (
        stat.S_IMODE(after.st_mode) != 0o600
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise ValueError("Terraform plan output changed while being sealed")


def prepare_residual_review(
    *,
    work_dir: Path,
    stage: str,
    context: dict[str, object],
    infra: Path,
    variables: Path,
    targets: tuple[str, ...],
    original_review: dict[str, object],
    original_claim: dict[str, object],
) -> dict[str, object] | None:
    """Return a separately bound residual review, or None when the original effect converged."""

    _validate_original_claim(stage, context, original_review, original_claim)
    operation = _operation(stage)
    plan_path = work_dir / f"{operation}.tfplan"
    review_path = work_dir / f"{operation}-review.json"
    plan_path.unlink(missing_ok=True)
    review_path.unlink(missing_ok=True)
    command = [
        "terraform",
        "plan",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
        f"-var-file={variables}",
        f"-out={plan_path}",
        *(f"-target={target}" for target in targets),
    ]
    completed = subprocess.run(
        command,
        cwd=infra,
        check=False,
        capture_output=True,
        timeout=1800,
        umask=0o077,
    )
    if completed.returncode == 0:
        plan_path.unlink(missing_ok=True)
        return None
    if completed.returncode != 2:
        plan_path.unlink(missing_ok=True)
        raise ValueError("standalone residual plan failed")
    seal_terraform_plan(plan_path)
    shown = subprocess.run(
        ("terraform", "show", "-json", str(plan_path)),
        cwd=infra,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        umask=0o077,
    )
    if shown.returncode != 0:
        raise ValueError("standalone residual plan projection failed")
    try:
        summary = plan_summary(json.loads(shown.stdout))
    except json.JSONDecodeError as exc:
        raise ValueError("standalone residual plan projection is invalid") from exc
    review: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": stage,
        "plan_digest": file_digest(plan_path),
        "target_binding": _required_digest(context, "target_binding"),
        "source_commit": _required_source_commit(context),
        "runtime_profile_digest": _runtime_profile_digest(context),
        "runtime_platform": _runtime_platform(context),
        "summary": summary,
        "residual_recovery": {
            "operation": operation,
            "original_plan_digest": original_review["plan_digest"],
            "original_claim_digest": canonical_digest(original_claim),
        },
        "expires_at": moment(datetime.now(UTC) + timedelta(hours=1)),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    review["review_digest"] = canonical_digest(review)
    replace_private_json(review_path, review)
    return review


def apply_residual_plan(
    *,
    work_dir: Path,
    stage: str,
    context: dict[str, object],
    infra: Path,
    variables: Path,
    targets: tuple[str, ...],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    approval: dict[str, object],
    effect_readback: Callable[[], bool],
) -> dict[str, object]:
    """Claim and apply one approved residual plan, then require readback and zero change."""

    _validate_residual_review(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
    )
    operation = _operation(stage)
    plan_path = work_dir / f"{operation}.tfplan"
    if file_digest(plan_path) != residual_review["plan_digest"]:
        raise ValueError("standalone residual plan changed before apply")
    claim_path = work_dir / f"{operation}-claim.json"
    receipt_path = work_dir / f"{stage}-receipt.json"
    if receipt_path.exists():
        return private_json(receipt_path, "standalone residual apply receipt")
    claim = _residual_claim(
        stage=stage,
        context=context,
        original_claim=original_claim,
        residual_review=residual_review,
        approval=approval,
    )
    try:
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
    except FileExistsError as exc:
        raise ValueError(
            "standalone residual apply claim already exists; automatic retry is blocked"
        ) from exc
    completed = subprocess.run(
        ("terraform", "apply", "-input=false", "-no-color", str(plan_path)),
        cwd=infra,
        check=False,
        capture_output=True,
        timeout=7200,
        umask=0o077,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"{stage} residual exact apply failed; verification-only recovery is required"
        )
    if not effect_readback():
        raise ValueError(f"{stage} residual apply effect readback is incomplete")
    if not _zero_change(
        infra=infra,
        variables=variables,
        targets=targets,
    ):
        raise ValueError(f"{stage} residual apply did not converge to zero change")
    return _write_receipt(
        receipt_path=receipt_path,
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=claim,
        verification_only=False,
    )


def recover_residual_apply(
    *,
    work_dir: Path,
    stage: str,
    context: dict[str, object],
    infra: Path,
    variables: Path,
    targets: tuple[str, ...],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    effect_readback: Callable[[], bool],
) -> dict[str, object]:
    """Verify a claimed residual effect without issuing another apply."""

    operation = _operation(stage)
    review = private_json(work_dir / f"{operation}-review.json", "standalone residual plan review")
    claim = private_json(work_dir / f"{operation}-claim.json", "standalone residual apply claim")
    _validate_residual_review(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=review,
        allow_expired=True,
    )
    expected_claim = _residual_claim_binding(
        stage=stage,
        context=context,
        original_claim=original_claim,
        residual_review=review,
    )
    if (
        claim.get("schema_version") != "fdai.standalone-residual-claim.v1"
        or any(claim.get(key) != value for key, value in expected_claim.items())
        or not isinstance(claim.get("approval_digest"), str)
        or _DIGEST.fullmatch(str(claim["approval_digest"])) is None
        or not isinstance(claim.get("claimed_at"), str)
        or claim.get("mutation_performed") is not False
    ):
        raise ValueError("standalone residual apply recovery claim is invalid")
    if not _zero_change(infra=infra, variables=variables, targets=targets):
        raise ValueError("standalone residual apply effect is not recoverably converged")
    if not effect_readback():
        raise ValueError("standalone residual apply effect readback is incomplete")
    return _write_receipt(
        receipt_path=work_dir / f"{stage}-receipt.json",
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=review,
        residual_claim=claim,
        verification_only=True,
    )


def residual_claim_exists(work_dir: Path, stage: str) -> bool:
    return (work_dir / f"{_operation(stage)}-claim.json").is_file()


def _write_receipt(
    *,
    receipt_path: Path,
    stage: str,
    context: dict[str, object],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    residual_claim: dict[str, object],
    verification_only: bool,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-residual-apply-receipt.v1",
        "state": "applied",
        "stage": stage,
        "plan_digest": residual_review["plan_digest"],
        "original_plan_digest": original_review["plan_digest"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "original_claim_digest": canonical_digest(original_claim),
        "residual_claim_digest": canonical_digest(residual_claim),
        "control_plane_readback_verified": True,
        "terraform_zero_change_verified": True,
        "residual_recovery": True,
        "verification_only_recovery": verification_only,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(receipt_path, receipt)
    return receipt


def _residual_claim(
    *,
    stage: str,
    context: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    approval: dict[str, object],
) -> dict[str, object]:
    claim: dict[str, object] = {
        "schema_version": "fdai.standalone-residual-claim.v1",
        **_residual_claim_binding(
            stage=stage,
            context=context,
            original_claim=original_claim,
            residual_review=residual_review,
        ),
        "approval_digest": canonical_digest(approval),
        "claimed_at": moment(datetime.now(UTC)),
        "mutation_performed": False,
    }
    return claim


def _residual_claim_binding(
    *,
    stage: str,
    context: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
) -> dict[str, object]:
    original_claim_digest = canonical_digest(original_claim)
    plan_digest = residual_review["plan_digest"]
    return {
        "stage": stage,
        "operation": _operation(stage),
        "original_claim_digest": original_claim_digest,
        "plan_digest": plan_digest,
        "idempotency_key": canonical_digest(
            {
                "target_binding": _required_digest(context, "target_binding"),
                "original_claim_digest": original_claim_digest,
                "plan_digest": plan_digest,
            }
        ),
    }


def _validate_original_claim(
    stage: str,
    context: dict[str, object],
    review: dict[str, object],
    claim: dict[str, object],
) -> None:
    plan_digest = review.get("plan_digest")
    if (
        claim.get("schema_version") != "fdai.standalone-application-claim.v1"
        or claim.get("stage") != stage
        or not isinstance(plan_digest, str)
        or _DIGEST.fullmatch(plan_digest) is None
        or claim.get("plan_digest") != plan_digest
        or claim.get("idempotency_key")
        != canonical_digest(
            {
                "target_binding": _required_digest(context, "target_binding"),
                "plan_digest": plan_digest,
            }
        )
    ):
        raise ValueError("standalone apply recovery claim is invalid")


def _validate_residual_review(
    *,
    stage: str,
    context: dict[str, object],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    allow_expired: bool = False,
) -> None:
    _validate_original_claim(stage, context, original_review, original_claim)
    validated_stage, _destructive = validate_plan_review(
        residual_review, allow_expired=allow_expired
    )
    binding = residual_review.get("residual_recovery")
    if (
        validated_stage != stage
        or residual_review.get("target_binding") != context.get("target_binding")
        or residual_review.get("source_commit") != context.get("source_commit")
        or _runtime_profile_digest(residual_review) != _runtime_profile_digest(context)
        or not isinstance(binding, dict)
        or binding
        != {
            "operation": _operation(stage),
            "original_plan_digest": original_review.get("plan_digest"),
            "original_claim_digest": canonical_digest(original_claim),
        }
    ):
        raise ValueError("standalone residual plan binding is invalid")


def _zero_change(*, infra: Path, variables: Path, targets: tuple[str, ...]) -> bool:
    command = [
        "terraform",
        "plan",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
        f"-var-file={variables}",
        *(f"-target={target}" for target in targets),
    ]
    completed = subprocess.run(
        command,
        cwd=infra,
        check=False,
        capture_output=True,
        timeout=1800,
        umask=0o077,
    )
    if completed.returncode not in {0, 2}:
        raise ValueError("standalone residual zero-change verification failed")
    return completed.returncode == 0


def _operation(stage: str) -> str:
    if stage not in _STAGES:
        raise ValueError("standalone residual stage is invalid")
    return f"{stage}-residual"


def _runtime_profile_digest(value: dict[str, object]) -> str:
    digest = value.get("runtime_profile_digest")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("standalone residual runtime profile binding is invalid")
    return digest


def _runtime_platform(context: dict[str, object]) -> str:
    profile = context.get("runtime_profile")
    platform = profile.get("runtime_platform") if isinstance(profile, dict) else None
    if platform not in {"aks", "container-apps"}:
        raise ValueError("standalone residual runtime platform is invalid")
    return str(platform)


def _required_digest(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _DIGEST.fullmatch(item) is None:
        raise ValueError(f"standalone residual {field} binding is invalid")
    return item


def _required_source_commit(context: dict[str, object]) -> str:
    value = context.get("source_commit")
    if not isinstance(value, str) or _SOURCE_COMMIT.fullmatch(value) is None:
        raise ValueError("standalone residual source binding is invalid")
    return value


__all__ = [
    "apply_residual_plan",
    "prepare_residual_review",
    "recover_residual_apply",
    "residual_claim_exists",
    "seal_terraform_plan",
]
