"""Apply one exact approved Foundation recovery plan or verify its existing claim."""

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
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import genesis_runner_image as image
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.foundation_plan import verify_foundation_plan
from fdai_deployment_cli.private_output import (
    _open_private_parent,
    read_private_bytes,
    write_private_bytes,
)
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.standalone_deploy import active_azure_target
from fdai_deployment_cli.target import compute_target_binding
from genesis_approval import load_genesis_approval
from genesis_approval_prompt import current_actor_digest
from genesis_checks import GenesisChecks
from genesis_foundation_apply import _independent_readback, _validate_handoff
from genesis_foundation_apply_contract import load_apply_claim
from genesis_foundation_recovery import validate_recovery_plan
from genesis_foundation_recovery_plan import (
    _json,
    _run,
    require_ip_policy_only,
    require_naming_only,
)
from genesis_foundation_workspace import verify_execution_copy
from genesis_vm_sku_preflight import recheck_foundation_vm

_MAX = 64 * 1024 * 1024


def require_current_approval(review: dict[str, object], approval_file: Path | None) -> str:
    """Require a current human approval bound to this recovery review and exact plan."""
    created = image._utc_timestamp(review.get("created_at"))
    expires = image._utc_timestamp(review.get("expires_at"))
    if not created <= datetime.now(UTC) < expires or expires - created != timedelta(hours=1):
        raise ValueError("Foundation recovery review is expired")
    binding = str(review["review_digest"])
    approval = load_genesis_approval(
        approval_file, run_binding=binding, source_commit=str(review["recovery_source_commit"])
    )
    if approval is None or not approval.authorizes(
        "foundation-apply", review_digest=binding, plan_digest=str(review["plan_digest"])
    ):
        raise ValueError("Foundation recovery requires exact current human approval")
    if approval.actor_digest != current_actor_digest(binding):
        raise ValueError("Foundation recovery approver differs from the authenticated human")
    return approval.actor_digest


def apply_recovery(
    *,
    repository_root: Path,
    original_directory: Path,
    source_snapshot: Path,
    work_dir: Path,
    terraform: Path,
    expected_review_digest: str,
    repository: str,
    approval_file: Path | None = None,
    verify_only: bool = False,
    timeout_seconds: int = 7800,
) -> dict[str, object]:
    """Execute a fresh claim once against original state; retained claims allow readback only.

    Original source, review, claim and state ownership remain distinct from recovery evidence.
    This command never forges an ordinary Foundation receipt or reports application readiness.
    """
    if not all(
        path.is_absolute()
        for path in (repository_root, original_directory, source_snapshot, work_dir, terraform)
    ):
        raise ValueError("Foundation recovery requires absolute execution paths")
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
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise ValueError("Foundation recovery requires the original private execution lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _locked(
            repository_root,
            original_directory,
            source_snapshot,
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
    snapshot: Path,
    work: Path,
    terraform: Path,
    expected_digest: str,
    repository: str,
    approval_file: Path | None,
    verify_only: bool,
    deadline: DeploymentDeadline,
) -> dict[str, object]:
    review = _json(work / "recovery-review.json")
    if (
        review.get("review_digest") != expected_digest
        or canonical_digest({key: value for key, value in review.items() if key != "review_digest"})
        != expected_digest
    ):
        raise ValueError("Foundation recovery review digest differs")
    if (
        review.get("schema_version") != "fdai.foundation-recovery-review.v1"
        or review.get("state") != "review"
        or any(
            review.get(key) is not False
            for key in ("apply_authorized", "mutation_performed", "deployment_ready")
        )
        or any(
            review.get(key) is not True
            for key in ("original_state_unchanged", "application_group_absent")
        )
    ):
        raise ValueError("Foundation recovery review authority or state is invalid")
    claim_path = work / "recovery-apply-claim.json"
    if (claim_path.exists() or claim_path.is_symlink()) != verify_only:
        raise ValueError("Foundation recovery claim permits verification only; never repeat apply")
    source = inspect_source(repository_root, expected_commit=str(review["recovery_source_commit"]))
    profile = load_profile(original.parent / "profile.json")
    if profile.environment != "dev" or profile.transport != "manual":
        raise ValueError("Foundation recovery requires manual development scope")
    verify_foundation_plan(
        directory=original,
        profile=profile,
        expected_review_digest=str(review["original_review_digest"]),
        require_unexpired=False,
    )
    prior = _json(original / "foundation-plan.json")
    context = cast(dict[str, Any], prior["context"])
    original_claim = load_apply_claim(
        original / "foundation-apply-claim.json", review=prior, profile=profile
    )
    if (
        original_claim is None
        or canonical_digest(original_claim) != review["original_claim_digest"]
        or context["source_commit"] != review["source_commit"]
    ):
        raise ValueError("Foundation recovery original claim binding differs")
    prior_source = verify_source_snapshot(
        snapshot, expected_digest=str(context["source_snapshot_digest"])
    )
    if canonical_digest(prior_source) != context["source_input_digest"]:
        raise ValueError("Foundation recovery original snapshot differs")
    verify_execution_copy(work / "reference/infra", authenticated_source=snapshot / "tree/infra")
    verify_execution_copy(
        original / "foundation-apply-bundle/source", authenticated_source=work / "reference"
    )
    if image._execution_tree_digest(work / "source") != review["configuration_digest"]:
        raise ValueError("Foundation recovery configuration changed")
    require_naming_only(
        snapshot / "tree/infra/genesis-foundation", work / "source/infra/genesis-foundation"
    )
    require_ip_policy_only(snapshot / "tree/infra/bootstrap", work / "source/infra/bootstrap")
    for name, digest in (
        ("recovery.tfplan", review["plan_digest"]),
        ("show.stdout", review["plan_json_digest"]),
        ("original-show.stdout", prior["plan_json_digest"]),
    ):
        if _hash(work / name) != digest:
            raise ValueError("Foundation recovery saved plan or projection changed")
    variables = _json(work / "recovery-variables.json")
    if canonical_digest(variables) != review["variables_digest"]:
        raise ValueError("Foundation recovery variables changed")
    target = active_azure_target()
    if (
        compute_target_binding(tenant_id=target.tenant_id, subscription_id=target.subscription_id)
        != review["target_binding"]
        or review["target_binding"] != profile.target_binding
        or variables.get("subscription_id") != target.subscription_id
        or variables.get("tenant_id") != target.tenant_id
    ):
        raise ValueError("Foundation recovery target changed")
    binary = image._trusted_terraform(terraform)
    if (
        image._file_digest(binary) != review["terraform_digest"]
        or review["terraform_digest"] != context["terraform_digest"]
        or image._execution_tree_digest(work / "terraform-data") != review["provider_digest"]
    ):
        raise ValueError("Foundation recovery toolchain changed")
    environment = image._terraform_environment(
        work, subscription_id=target.subscription_id, tenant_id=target.tenant_id
    )
    GenesisChecks(repository_root, environment=environment).verify_source(
        source_commit=source.commit, repository=repository, apply=True
    )
    state_path = (
        original / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
    )
    state = _json(state_path)
    if canonical_digest({"lineage": state.get("lineage")}) != review["original_lineage_digest"]:
        raise ValueError("Foundation recovery state lineage changed")
    root = work / "source/infra/genesis-foundation"
    if not verify_only:
        if _hash(state_path) != review["original_state_digest"]:
            raise ValueError("Foundation recovery state changed after planning")
        projection = _json(work / "show.stdout")
        validate_recovery_plan(
            projection,
            _json(work / "original-show.stdout"),
            state,
            application_workload=str(variables["application_workload"]),
        )
        entries = cast(list[dict[str, Any]], projection["resource_changes"])
        group = next(
            entry["change"]["after"]["name"]
            for entry in entries
            if entry["address"] == "azapi_resource.app_resource_group"
        )
        exists = image._capture(
            [
                str(image._trusted_azure_cli()),
                "group",
                "exists",
                "--subscription",
                target.subscription_id,
                "--name",
                group,
                "--output",
                "tsv",
                "--only-show-errors",
            ],
            cwd=work,
            env=environment,
            timeout=deadline.remaining(30),
            reason="Foundation recovery group availability is unknown",
        )
        if exists.strip().casefold() != "false":
            raise ValueError("Foundation recovery cannot adopt an existing application group")
        if deadline.remaining() < 180:
            raise TimeoutError("Foundation recovery lacks its bounded VM verification budget")
        recheck_foundation_vm(
            repository_root=repository_root,
            variables_file=work / "recovery-variables.json",
            evidence_directory=work,
        )
        actor = require_current_approval(review, approval_file)
        source.reverify()
        deadline.remaining()
        if (
            _hash(state_path) != review["original_state_digest"]
            or _hash(work / "recovery.tfplan") != review["plan_digest"]
            or image._execution_tree_digest(work / "source") != review["configuration_digest"]
            or image._execution_tree_digest(work / "terraform-data") != review["provider_digest"]
            or image._file_digest(binary) != review["terraform_digest"]
            or datetime.now(UTC) >= image._utc_timestamp(review["expires_at"])
        ):
            raise ValueError("Foundation recovery pre-claim evidence changed or review expired")
        claim: dict[str, object] = {
            "schema_version": "fdai.foundation-recovery-claim.v1",
            "review_digest": expected_digest,
            "plan_digest": review["plan_digest"],
            "original_claim_digest": review["original_claim_digest"],
            "original_state_digest": review["original_state_digest"],
            "actor_digest": actor,
            "execution_source_commit": source.commit,
            "idempotency_key": canonical_digest(
                {
                    "review_digest": expected_digest,
                    "original_state_digest": review["original_state_digest"],
                }
            ),
            "claimed_at": datetime.now(UTC).isoformat(),
        }
        write_private_bytes(claim_path, canonical_bytes(claim))
        _run(
            [
                str(binary),
                "apply",
                "-input=false",
                "-no-color",
                "-lock-timeout=0s",
                f"-state={state_path}",
                str(work / "recovery.tfplan"),
            ],
            cwd=root,
            environment=environment,
            deadline=deadline,
            work=work,
            label="apply",
        )
    else:
        claim = _json(claim_path)
        _validate_claim(claim, review)
    source.reverify()
    raw = image._capture(
        [str(binary), "output", f"-state={state_path}", "-json", "private_handoff"],
        cwd=root,
        env=environment,
        timeout=deadline.remaining(120),
        reason="Foundation recovery handoff output is unavailable",
    )
    handoff = json.loads(raw)
    _validate_handoff(handoff, prior)

    def capture(command: list[str], *, cwd: Path, timeout: int, reason: str) -> str:
        if not command or command[0] != "az":
            raise ValueError("Foundation recovery observer command is invalid")
        return image._capture(
            [str(image._trusted_azure_cli()), *command[1:]],
            cwd=cwd,
            env=environment,
            timeout=deadline.remaining(timeout),
            reason=reason,
        )

    _independent_readback(handoff, work, capture=capture)
    verification = Path(tempfile.mkdtemp(prefix="verification-", dir=work))
    _run(
        [
            str(binary),
            "plan",
            "-input=false",
            "-no-color",
            "-detailed-exitcode",
            "-lock-timeout=0s",
            f"-state={state_path}",
            f"-var-file={work / 'recovery-variables.json'}",
        ],
        cwd=root,
        environment=environment,
        deadline=deadline,
        work=verification,
        label="zero-change",
    )
    handoff_path = work / "recovery-private-handoff.json"
    if handoff_path.exists():
        if _json(handoff_path) != handoff:
            raise ValueError("Foundation recovery handoff changed on readback")
    else:
        write_private_bytes(handoff_path, canonical_bytes(handoff))
    receipt = {
        "schema_version": "fdai.foundation-recovery-receipt.v1",
        "state": "verified",
        "review_digest": expected_digest,
        "claim_digest": canonical_digest(claim),
        "source_commit": review["source_commit"],
        "execution_source_commit": source.commit,
        "state_digest": _hash(state_path),
        "handoff_digest": canonical_digest(handoff),
        "control_plane_readback_verified": True,
        "zero_change_verified": True,
        "remote_backend_authority_verified": False,
        "runner_attested": False,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_path = work / "recovery-apply-receipt.json"
    if receipt_path.exists():
        if _json(receipt_path) != receipt:
            raise ValueError("Foundation recovery observations differ from retained receipt")
    else:
        write_private_bytes(receipt_path, canonical_bytes(receipt))
    return receipt


def _validate_claim(claim: dict[str, object], review: dict[str, object]) -> None:
    expected = {
        "schema_version": "fdai.foundation-recovery-claim.v1",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "original_claim_digest": review["original_claim_digest"],
        "original_state_digest": review["original_state_digest"],
        "execution_source_commit": review["recovery_source_commit"],
        "idempotency_key": canonical_digest(
            {
                "review_digest": review["review_digest"],
                "original_state_digest": review["original_state_digest"],
            }
        ),
    }
    if (
        set(claim) != set(expected) | {"actor_digest", "claimed_at"}
        or any(claim.get(key) != value for key, value in expected.items())
        or re.fullmatch(r"[0-9a-f]{64}", str(claim.get("actor_digest", ""))) is None
    ):
        raise ValueError("Foundation recovery retained claim differs")
    claimed_at = image._utc_timestamp(claim.get("claimed_at"))
    if not image._utc_timestamp(review["created_at"]) <= claimed_at < image._utc_timestamp(
        review["expires_at"]
    ) or claimed_at > datetime.now(UTC):
        raise ValueError("Foundation recovery claim timestamp is invalid")


def _hash(path: Path) -> str:
    return hashlib.sha256(read_private_bytes(path, max_bytes=_MAX)).hexdigest()


def main() -> int:
    """Run one exact-approved recovery or verification-only operation with bounded diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-directory", "source-snapshot", "work-dir", "terraform"):
        parser.add_argument(f"--{name}", type=Path, required=True)
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
            "Foundation recovery execution failed; "
            "retain claim and private diagnostics without repeating apply",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
