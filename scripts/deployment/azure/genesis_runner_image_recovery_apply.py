"""Apply one separately approved residual image plan; never retry its retained claim."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import genesis_runner_image as image
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import (
    _open_private_parent,
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.standalone_deploy import active_azure_target
from fdai_deployment_cli.target import compute_target_binding
from genesis_approval import load_genesis_approval
from genesis_approval_prompt import current_actor_digest
from genesis_checks import GenesisChecks
from genesis_runner_image_contract import CLAIM_NAME, PLAN_JSON_NAME, hash_tree, load_review
from genesis_runner_image_observation import verify_runner_image_effect
from genesis_runner_image_recovery import validate_residual_plan
from genesis_runner_image_recovery_plan import require_only_wait_fix
from genesis_subprocess import run_with_heartbeat

_MAX = 64 * 1024 * 1024


def apply_recovery(
    *,
    repository_root: Path,
    original_directory: Path,
    work_dir: Path,
    terraform: Path,
    expected_review_digest: str,
    repository: str,
    approval_file: Path | None,
    verify_only: bool = False,
    timeout_seconds: int = 7800,
) -> dict[str, object]:
    """Apply fresh exact authority once, or independently verify an already claimed recovery.

    The original source lock serializes against normal execution. No original approval,
    scope confirmation or expired review authorizes a new apply. Terraform writes only
    the original local backend. Failed claims remain verification-only; original receipts
    are never forged or overwritten, and successful recovery gets its own private receipt.
    """
    image._validate_timeout(timeout_seconds)
    deadline = DeploymentDeadline(timeout_seconds)
    lock_path = original_directory.parent / "source-execution.lock"
    parent = _open_private_parent(lock_path)
    try:
        lock = os.open(lock_path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        details = os.fstat(lock)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
        ):
            raise ValueError("residual apply requires the original private execution lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _locked(
            repository_root,
            original_directory,
            work_dir,
            terraform,
            expected_review_digest,
            repository,
            approval_file,
            verify_only,
            deadline,
        )
    finally:
        os.close(lock)


def _locked(
    repository_root: Path,
    original: Path,
    work: Path,
    terraform: Path,
    expected_digest: str,
    repository: str,
    approval_file: Path | None,
    verify_only: bool,
    deadline: DeploymentDeadline,
) -> dict[str, object]:
    review = _json(work / "residual-review.json")
    digest = review.pop("review_digest", None)
    if (
        digest != expected_digest
        or canonical_digest(review) != expected_digest
        or review.get("schema_version") != "fdai.runner-image-residual-review.v1"
        or review.get("apply_authorized") is not False
        or review.get("deployment_ready") is not False
    ):
        raise ValueError("residual apply review integrity or authority is invalid")
    review["review_digest"] = digest
    if (
        review.get("state") != "review"
        or review.get("mutation_performed") is not False
        or review.get("original_state_unchanged") is not True
    ):
        raise ValueError("residual apply review state is invalid")
    claim_path = work / "residual-apply-claim.json"
    claimed = claim_path.exists() or claim_path.is_symlink()
    if claimed != verify_only:
        raise ValueError("residual apply claim permits verification only; never repeat apply")
    source = inspect_source(repository_root, expected_commit=str(review["recovery_source_commit"]))
    prior = load_review(
        original,
        expected_review_digest=str(review["original_review_digest"]),
        require_unexpired=False,
    )
    prior_claim = image._load_apply_claim(original / CLAIM_NAME, review=prior)
    if (
        prior_claim is None
        or canonical_digest(prior_claim) != review["original_claim_digest"]
        or prior["plan_digest"] != review["original_plan_digest"]
        or prior["source_commit"] != review["source_commit"]
        or prior["target_binding"] != review["target_binding"]
    ):
        raise ValueError("residual apply original claim or plan differs")
    if (
        hash_tree(original / "root") != prior["terraform_root_digest"]
        or hash_tree(work / "root") != review["terraform_root_digest"]
    ):
        raise ValueError("residual apply configuration changed")
    require_only_wait_fix(original / "root", work / "root")
    for name, field in (("residual.tfplan", "plan_digest"), ("show.stdout", "plan_json_digest")):
        if _hash(work / name) != review[field]:
            raise ValueError("residual apply saved plan changed")
    if _hash(original / PLAN_JSON_NAME) != prior["plan_json_digest"]:
        raise ValueError("residual apply original plan projection changed")
    validate_residual_plan(_json(work / "show.stdout"), _json(original / PLAN_JSON_NAME))
    variables = _json(work / "original-variables.json")
    if (
        canonical_digest(variables) != review["variables_digest"]
        or review["variables_digest"] != prior["variables_digest"]
    ):
        raise ValueError("residual apply original variables changed")
    target = active_azure_target()
    if (
        variables.get("subscription_id") != target.subscription_id
        or variables.get("tenant_id") != target.tenant_id
        or compute_target_binding(
            tenant_id=target.tenant_id, subscription_id=target.subscription_id
        )
        != review["target_binding"]
    ):
        raise ValueError("residual apply target differs from the approved review")
    binary = image._trusted_terraform(terraform)
    if image._file_digest(binary) != review["terraform_digest"] or image._execution_tree_digest(
        work / "terraform-data"
    ) != review.get("provider_digest"):
        raise ValueError("residual apply toolchain changed")
    environment = image._terraform_environment(
        work, subscription_id=target.subscription_id, tenant_id=target.tenant_id
    )
    GenesisChecks(repository_root, environment=environment).verify_source(
        source_commit=source.commit, repository=repository, apply=True
    )
    state_path = original / "root/terraform.tfstate"
    state = _json(state_path)
    if canonical_digest({"lineage": state.get("lineage")}) != review.get("original_lineage_digest"):
        raise ValueError("residual apply state lineage differs")
    if not verify_only:
        actor = _require_fresh_authority(review, approval_file, source.commit)
        if _hash(state_path) != review["original_state_digest"]:
            raise ValueError("residual apply original state changed after planning")
        if actor == prior_claim["executor_identity_digest"]:
            raise ValueError("residual apply human and executor identities must differ")
        source.reverify()
        deadline.remaining()
        claim = {
            "schema_version": "fdai.runner-image-residual-claim.v1",
            "review_digest": expected_digest,
            "plan_digest": review["plan_digest"],
            "original_claim_digest": review["original_claim_digest"],
            "approver_actor_digest": actor,
            "credential_actor_digest": actor,
            "executor_identity_digest": prior_claim["executor_identity_digest"],
            "idempotency_key": canonical_digest(
                {
                    "review_digest": expected_digest,
                    "original_state_digest": review["original_state_digest"],
                }
            ),
            "execution_source_commit": source.commit,
            "claimed_at": datetime.now(UTC).isoformat(),
        }
        write_private_bytes(claim_path, canonical_bytes(claim))
        completed = run_with_heartbeat(
            [
                str(binary),
                "apply",
                "-input=false",
                "-no-color",
                "-lock-timeout=0s",
                f"-state={state_path}",
                str(work / "residual.tfplan"),
            ],
            cwd=work / "root",
            env=environment,
            timeout=deadline.remaining(),
            capture_output=True,
            umask=0o077,
        )
        write_private_bytes(work / "apply.stdout", completed.stdout.encode())
        if completed.stderr:
            write_private_bytes(work / "apply.stderr", completed.stderr.encode())
        if completed.returncode != 0:
            raise ValueError(
                "residual apply failed; preserve the claim and verify without reapplying"
            )
    else:
        claim = _json(claim_path)
        if (
            claim.get("schema_version") != "fdai.runner-image-residual-claim.v1"
            or claim.get("review_digest") != expected_digest
            or claim.get("plan_digest") != review["plan_digest"]
            or claim.get("original_claim_digest") != review["original_claim_digest"]
            or claim.get("execution_source_commit") != source.commit
        ):
            raise ValueError("residual apply retained claim differs")
        if (
            claim.get("idempotency_key")
            != canonical_digest(
                {
                    "review_digest": expected_digest,
                    "original_state_digest": review["original_state_digest"],
                }
            )
            or claim.get("approver_actor_digest") != claim.get("credential_actor_digest")
            or claim.get("executor_identity_digest") != prior_claim["executor_identity_digest"]
            or claim.get("approver_actor_digest") == claim.get("executor_identity_digest")
        ):
            raise ValueError("residual apply retained authority differs")
    if set(claim) != {
        "schema_version",
        "review_digest",
        "plan_digest",
        "original_claim_digest",
        "approver_actor_digest",
        "credential_actor_digest",
        "executor_identity_digest",
        "idempotency_key",
        "execution_source_commit",
        "claimed_at",
    } or any(
        not isinstance(claim.get(field), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(claim[field])) is None
        for field in (
            "approver_actor_digest",
            "credential_actor_digest",
            "executor_identity_digest",
        )
    ):
        raise ValueError("residual apply retained claim schema or identity is invalid")
    claimed_at = image._utc_timestamp(claim.get("claimed_at"))
    if not image._utc_timestamp(review.get("created_at")) <= claimed_at < image._utc_timestamp(
        review.get("expires_at")
    ) or claimed_at > datetime.now(UTC):
        raise ValueError("residual apply claim is outside its reviewed time window")
    source.reverify()
    raw = image._capture(
        [str(binary), "output", f"-state={state_path}", "-json", "runner_image"],
        cwd=work / "root",
        env=environment,
        timeout=deadline.remaining(120),
        reason="residual image output is unavailable",
    )
    output = load_json_object(raw.encode(), label="residual image output", max_bytes=1024 * 1024)
    if (
        output.get("runner_registered") is not False
        or output.get("subscription_ready") is not False
    ):
        raise ValueError("residual image output has unexpected activation authority")

    def capture(command: list[str], *, cwd: Path, timeout: int, reason: str) -> str:
        if not command or command[0] != "az":
            raise ValueError("residual image observation command is invalid")
        return image._capture(
            [str(image._trusted_azure_cli()), *command[1:]],
            cwd=cwd,
            env=environment,
            timeout=deadline.remaining(timeout),
            reason=reason,
        )

    image_id = verify_runner_image_effect(
        terraform_output=output,
        review=prior,
        subscription_id=target.subscription_id,
        capture=capture,
        cwd=work,
        timeout=deadline.remaining(),
    )
    if deadline.remaining() < 600:
        raise TimeoutError("residual image verification needs its remaining bounded budget")
    image._verify_zero_change(work_dir=original, terraform=binary, environment=environment)
    deadline.remaining()
    result = {
        "schema_version": "fdai.runner-image-residual-receipt.v1",
        "state": "verified",
        "review_digest": expected_digest,
        "claim_digest": canonical_digest(claim),
        "source_commit": review["source_commit"],
        "execution_source_commit": source.commit,
        "runner_image_id": image_id,
        "effect_verified": True,
        "terraform_zero_change_verified": True,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    receipt_path = work / "residual-apply-receipt.json"
    if receipt_path.exists():
        if _json(receipt_path) != result:
            raise ValueError("residual image current observations differ from the retained receipt")
    else:
        write_private_bytes(receipt_path, canonical_bytes(result))
    return {key: value for key, value in result.items() if key != "runner_image_id"}


def _require_fresh_authority(
    review: dict[str, object], approval_file: Path | None, source_commit: str
) -> str:
    created = image._utc_timestamp(review.get("created_at"))
    expires = image._utc_timestamp(review.get("expires_at"))
    if not created <= datetime.now(UTC) < expires or expires - created != timedelta(hours=1):
        raise ValueError("residual apply review is expired")
    binding = str(review["review_digest"])
    approval = load_genesis_approval(
        approval_file, run_binding=binding, source_commit=source_commit
    )
    if approval is None or not approval.authorizes(
        "runner-image", review_digest=binding, plan_digest=str(review["plan_digest"])
    ):
        raise ValueError("residual apply requires current approval for this exact new plan")
    if approval.actor_digest != current_actor_digest(binding):
        raise ValueError("residual approver differs from the current authenticated human")
    return approval.actor_digest


def _json(path: Path) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=_MAX),
        label="residual execution evidence",
        max_bytes=_MAX,
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(read_private_bytes(path, max_bytes=_MAX)).hexdigest()


def main() -> int:
    """Execute only exact residual approval or explicit verification-only recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-directory", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--terraform", type=Path, required=True)
    parser.add_argument("--expected-review-digest", required=True)
    parser.add_argument("--repository", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--approval-file", type=Path)
    selection.add_argument("--verify-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=7800)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                apply_recovery(repository_root=Path(__file__).resolve().parents[3], **vars(args)),
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "residual image execution failed; preserve original state and recovery evidence",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
