"""Govern one create-only successor after a residual apply is verified incomplete."""

from __future__ import annotations

import json
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
from fdai_deployment_cli.standalone_residual_apply import (
    _DIGEST,
    _STAGES,
    _required_digest,
    _required_source_commit,
    _runtime_platform,
    _runtime_profile_digest,
    _validate_residual_claim,
    _zero_change,
    seal_terraform_plan,
)
from fdai_deployment_cli.standalone_review import validate_plan_review


def successor_prerequisite_verified(work_dir: Path, stage: str) -> bool:
    """Require completed focused private access before the one substrate successor."""

    if stage != "substrate":
        return False
    receipt_path = work_dir / "access-receipt.json"
    if not receipt_path.exists() or receipt_path.is_symlink():
        return False
    receipt = private_json(receipt_path, "focused private access receipt")
    return (
        receipt.get("schema_version") == "fdai.standalone-application-apply-receipt.v1"
        and receipt.get("state") == "applied"
        and receipt.get("control_plane_readback_verified") is True
        and receipt.get("mutation_performed") is True
    )


def prepare_residual_successor_review(
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
    residual_claim: dict[str, object],
    successor_prerequisite_verified: bool,
) -> dict[str, object]:
    """Create one fresh create-only successor plan after verified residual non-convergence."""

    _validate_residual_claim(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
    )
    if not successor_prerequisite_verified:
        raise ValueError("standalone residual successor prerequisite is not verified")
    operation = _operation(stage)
    plan_path = work_dir / f"{operation}.tfplan"
    review_path = work_dir / f"{operation}-review.json"
    claim_path = work_dir / f"{operation}-claim.json"
    if claim_path.exists() or claim_path.is_symlink():
        raise ValueError("standalone residual successor claim already exists")
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
    if completed.returncode != 2:
        plan_path.unlink(missing_ok=True)
        raise ValueError("standalone residual successor plan is unavailable")
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
        raise ValueError("standalone residual successor projection failed")
    try:
        summary = plan_summary(json.loads(shown.stdout))
    except json.JSONDecodeError as exc:
        raise ValueError("standalone residual successor projection is invalid") from exc
    counts = summary.get("action_counts")
    if (
        not isinstance(counts, dict)
        or type(counts.get("create")) is not int
        or counts["create"] <= 0
        or any(counts.get(action, 0) != 0 for action in ("update", "replace", "delete"))
    ):
        raise ValueError("standalone residual successor must contain create actions only")
    review: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": stage,
        "plan_digest": file_digest(plan_path),
        "target_binding": _required_digest(context, "target_binding"),
        "source_commit": _required_source_commit(context),
        "runtime_profile_digest": _runtime_profile_digest(context),
        "runtime_platform": _runtime_platform(context),
        "summary": summary,
        "residual_successor": {
            "operation": operation,
            "original_claim_digest": canonical_digest(original_claim),
            "residual_plan_digest": residual_review["plan_digest"],
            "residual_claim_digest": canonical_digest(residual_claim),
        },
        "expires_at": moment(datetime.now(UTC) + timedelta(hours=1)),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    review["review_digest"] = canonical_digest(review)
    replace_private_json(review_path, review)
    return review


def apply_residual_successor(
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
    residual_claim: dict[str, object],
    successor_review: dict[str, object],
    approval: dict[str, object],
    effect_readback: Callable[[], bool],
) -> dict[str, object]:
    """Apply one exact-approved create-only successor and prohibit another successor."""

    _validate_review(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
        successor_review=successor_review,
    )
    operation = _operation(stage)
    plan_path = work_dir / f"{operation}.tfplan"
    if file_digest(plan_path) != successor_review["plan_digest"]:
        raise ValueError("standalone residual successor plan changed before apply")
    claim_path = work_dir / f"{operation}-claim.json"
    claim = _claim(
        stage=stage,
        context=context,
        original_claim=original_claim,
        residual_claim=residual_claim,
        successor_review=successor_review,
        approval=approval,
    )
    try:
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
    except FileExistsError as exc:
        raise ValueError(
            "standalone residual successor claim already exists; automatic retry is blocked"
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
            f"{stage} residual successor apply failed; verification-only recovery is required"
        )
    if not effect_readback() or not _zero_change(infra=infra, variables=variables, targets=targets):
        raise ValueError(f"{stage} residual successor did not converge")
    return _write_receipt(
        work_dir=work_dir,
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
        successor_review=successor_review,
        successor_claim=claim,
        verification_only=False,
    )


def recover_residual_successor(
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
    residual_claim: dict[str, object],
    effect_readback: Callable[[], bool],
) -> dict[str, object]:
    """Verify one claimed successor without permitting any further apply."""

    operation = _operation(stage)
    review = private_json(work_dir / f"{operation}-review.json", "residual successor review")
    claim = private_json(work_dir / f"{operation}-claim.json", "residual successor claim")
    _validate_review(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
        successor_review=review,
        allow_expired=True,
    )
    expected = _claim_binding(
        stage=stage,
        context=context,
        original_claim=original_claim,
        residual_claim=residual_claim,
        successor_review=review,
    )
    if (
        claim.get("schema_version") != "fdai.standalone-residual-successor-claim.v1"
        or any(claim.get(key) != value for key, value in expected.items())
        or not isinstance(claim.get("approval_digest"), str)
        or _DIGEST.fullmatch(str(claim["approval_digest"])) is None
        or not isinstance(claim.get("claimed_at"), str)
        or claim.get("mutation_performed") is not False
    ):
        raise ValueError("standalone residual successor claim is invalid")
    if not _zero_change(infra=infra, variables=variables, targets=targets):
        raise ValueError("standalone residual successor is not recoverably converged")
    if not effect_readback():
        raise ValueError("standalone residual successor readback is incomplete")
    return _write_receipt(
        work_dir=work_dir,
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
        successor_review=review,
        successor_claim=claim,
        verification_only=True,
    )


def _validate_review(
    *,
    stage: str,
    context: dict[str, object],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    residual_claim: dict[str, object],
    successor_review: dict[str, object],
    allow_expired: bool = False,
) -> None:
    _validate_residual_claim(
        stage=stage,
        context=context,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        residual_claim=residual_claim,
    )
    validated_stage, destructive = validate_plan_review(
        successor_review, allow_expired=allow_expired
    )
    binding = successor_review.get("residual_successor")
    if (
        validated_stage != stage
        or destructive
        or successor_review.get("target_binding") != context.get("target_binding")
        or successor_review.get("source_commit") != context.get("source_commit")
        or _runtime_profile_digest(successor_review) != _runtime_profile_digest(context)
        or not isinstance(binding, dict)
        or binding
        != {
            "operation": _operation(stage),
            "original_claim_digest": canonical_digest(original_claim),
            "residual_plan_digest": residual_review.get("plan_digest"),
            "residual_claim_digest": canonical_digest(residual_claim),
        }
    ):
        raise ValueError("standalone residual successor plan binding is invalid")


def _claim(
    *,
    stage: str,
    context: dict[str, object],
    original_claim: dict[str, object],
    residual_claim: dict[str, object],
    successor_review: dict[str, object],
    approval: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "fdai.standalone-residual-successor-claim.v1",
        **_claim_binding(
            stage=stage,
            context=context,
            original_claim=original_claim,
            residual_claim=residual_claim,
            successor_review=successor_review,
        ),
        "approval_digest": canonical_digest(approval),
        "claimed_at": moment(datetime.now(UTC)),
        "mutation_performed": False,
    }


def _claim_binding(
    *,
    stage: str,
    context: dict[str, object],
    original_claim: dict[str, object],
    residual_claim: dict[str, object],
    successor_review: dict[str, object],
) -> dict[str, object]:
    original_claim_digest = canonical_digest(original_claim)
    residual_claim_digest = canonical_digest(residual_claim)
    plan_digest = successor_review["plan_digest"]
    return {
        "stage": stage,
        "operation": _operation(stage),
        "original_claim_digest": original_claim_digest,
        "residual_claim_digest": residual_claim_digest,
        "plan_digest": plan_digest,
        "idempotency_key": canonical_digest(
            {
                "target_binding": _required_digest(context, "target_binding"),
                "original_claim_digest": original_claim_digest,
                "residual_claim_digest": residual_claim_digest,
                "plan_digest": plan_digest,
            }
        ),
    }


def _write_receipt(
    *,
    work_dir: Path,
    stage: str,
    context: dict[str, object],
    original_review: dict[str, object],
    original_claim: dict[str, object],
    residual_review: dict[str, object],
    residual_claim: dict[str, object],
    successor_review: dict[str, object],
    successor_claim: dict[str, object],
    verification_only: bool,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-residual-successor-receipt.v1",
        "state": "applied",
        "stage": stage,
        "plan_digest": successor_review["plan_digest"],
        "original_plan_digest": original_review["plan_digest"],
        "residual_plan_digest": residual_review["plan_digest"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "original_claim_digest": canonical_digest(original_claim),
        "residual_claim_digest": canonical_digest(residual_claim),
        "successor_claim_digest": canonical_digest(successor_claim),
        "control_plane_readback_verified": True,
        "terraform_zero_change_verified": True,
        "residual_recovery": True,
        "residual_successor": True,
        "verification_only_recovery": verification_only,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(work_dir / f"{stage}-receipt.json", receipt)
    return receipt


def _operation(stage: str) -> str:
    if stage not in _STAGES:
        raise ValueError("standalone residual successor stage is invalid")
    return f"{stage}-residual-successor"
