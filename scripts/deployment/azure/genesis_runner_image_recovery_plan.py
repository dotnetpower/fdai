"""Prepare a read-only residual image plan against retained authoritative local state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
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
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.standalone_deploy import active_azure_target
from fdai_deployment_cli.target import compute_target_binding
from genesis_runner_image_contract import (
    CLAIM_NAME,
    PLAN_JSON_NAME,
    hash_tree,
    load_review,
    snapshot_terraform_root,
)
from genesis_runner_image_recovery import validate_residual_plan
from genesis_subprocess import run_with_heartbeat

_MAX = 64 * 1024 * 1024


def prepare_recovery_plan(
    *,
    repository_root: Path,
    original_directory: Path,
    work_dir: Path,
    expected_review_digest: str,
    terraform: Path,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Plan without applying, copying state, refreshing original evidence, or granting approval.

    Requires the retained source execution lock and exact original review/claim. The only
    accepted configuration change is the trusted CLI poweroff fix. The original state is
    passed directly to Terraform's local backend and remains byte-for-byte unchanged.
    Partial work directories are preserved and never reused. A successful review is not
    accepted by the ordinary image apply command and cannot authorize any new effect.
    """
    deadline = DeploymentDeadline(timeout_seconds)
    if not all(
        path.is_absolute() for path in (repository_root, original_directory, work_dir, terraform)
    ):
        raise ValueError("runner image recovery requires absolute paths")
    if work_dir.resolve().is_relative_to(
        original_directory.resolve()
    ) or work_dir.resolve().is_relative_to(repository_root.resolve()):
        raise ValueError("runner image recovery output must be outside original state and source")
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
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
        ):
            raise ValueError("runner image recovery requires the original private execution lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "runner image recovery cannot run during another source execution"
            ) from None
        return _prepare_locked(
            repository_root,
            original_directory,
            work_dir,
            expected_review_digest,
            terraform,
            deadline,
        )
    finally:
        os.close(lock)


def _prepare_locked(
    repository_root: Path,
    original: Path,
    work: Path,
    expected_digest: str,
    terraform: Path,
    deadline: DeploymentDeadline,
) -> dict[str, object]:
    review = load_review(original, expected_review_digest=expected_digest, require_unexpired=False)
    claim = image._load_apply_claim(original / CLAIM_NAME, review=review)
    if claim is None:
        raise ValueError("runner image recovery requires an original apply claim")
    original_plan_bytes = read_private_bytes(original / PLAN_JSON_NAME, max_bytes=_MAX)
    if hashlib.sha256(original_plan_bytes).hexdigest() != review["plan_json_digest"]:
        raise ValueError("runner image recovery original plan projection changed")
    original_plan = load_json_object(
        original_plan_bytes, label="original image plan", max_bytes=_MAX
    )
    original_root = original / "root"
    if hash_tree(original_root) != review["terraform_root_digest"]:
        raise ValueError("runner image recovery original configuration changed")
    variable_bytes = read_private_bytes(
        original / "runner-image.auto.tfvars.json", max_bytes=1024 * 1024
    )
    variables = load_json_object(variable_bytes, label="original image variables")
    if canonical_digest(variables) != review["variables_digest"]:
        raise ValueError("runner image recovery variables differ from the approved plan")
    profile = load_profile(original.parent / "profile.json")
    if (
        canonical_digest(profile.to_mapping()) != review["profile_digest"]
        or profile.environment != "dev"
        or profile.transport != "manual"
    ):
        raise ValueError("runner image recovery profile differs from the original run")
    target = active_azure_target()
    if (
        variables.get("subscription_id") != target.subscription_id
        or variables.get("tenant_id") != target.tenant_id
        or compute_target_binding(
            tenant_id=target.tenant_id, subscription_id=target.subscription_id
        )
        != review["target_binding"]
    ):
        raise ValueError("runner image recovery target differs from original evidence")
    source = inspect_source(repository_root)
    binary = image._trusted_terraform(terraform)
    if image._file_digest(binary) != review["terraform_digest"]:
        raise ValueError("runner image recovery Terraform differs from the original plan")
    state_path = original_root / "terraform.tfstate"
    state_bytes = read_private_bytes(state_path, max_bytes=_MAX)
    state = load_json_object(state_bytes, label="original image state", max_bytes=_MAX)
    if (
        state.get("version") != 4
        or type(state.get("serial")) is not int
        or not isinstance(state.get("lineage"), str)
    ):
        raise ValueError("runner image recovery requires complete retained Terraform state")
    parent = _open_private_parent(work)
    try:
        os.mkdir(work.name, 0o700, dir_fd=parent)
    finally:
        os.close(parent)
    root = work / "root"
    root_digest = snapshot_terraform_root(
        repository_root / "infra/genesis-runner-image", root, source_commit=source.commit
    )
    require_only_wait_fix(original_root, root)
    write_private_bytes(work / "original-variables.json", variable_bytes)
    environment = image._terraform_environment(
        work, subscription_id=target.subscription_id, tenant_id=target.tenant_id
    )
    steps = (
        (
            "init",
            [
                str(binary),
                "init",
                "-backend=false",
                "-input=false",
                "-lockfile=readonly",
                f"-plugin-dir={original / 'terraform-data/providers'}",
            ],
        ),
        ("validate", [str(binary), "validate", "-no-color"]),
        (
            "plan",
            [
                str(binary),
                "plan",
                "-input=false",
                "-no-color",
                "-lock-timeout=0s",
                f"-state={state_path}",
                f"-var-file={work / 'original-variables.json'}",
                f"-out={work / 'residual.tfplan'}",
            ],
        ),
        ("show", [str(binary), "show", "-json", str(work / "residual.tfplan")]),
    )
    projection_bytes = b""
    for label, command in steps:
        print(f"runner image residual planning: {label}", file=sys.stderr, flush=True)
        result = run_with_heartbeat(
            command,
            cwd=root,
            env=environment,
            timeout=deadline.remaining(),
            capture_output=True,
            umask=0o077,
        )
        if len(result.stdout.encode()) > _MAX or len(result.stderr.encode()) > _MAX:
            raise ValueError("runner image recovery diagnostics exceed their bound")
        write_private_bytes(work / f"{label}.stdout", result.stdout.encode())
        if result.stderr:
            write_private_bytes(work / f"{label}.stderr", result.stderr.encode())
        if result.returncode != 0:
            raise ValueError("runner image residual planning failed; preserve private diagnostics")
        projection_bytes = result.stdout.encode()
        deadline.remaining()
    source.reverify()
    if (
        read_private_bytes(state_path, max_bytes=_MAX) != state_bytes
        or hash_tree(original_root) != review["terraform_root_digest"]
        or image._load_apply_claim(original / CLAIM_NAME, review=review) != claim
    ):
        raise ValueError("runner image recovery original evidence changed during planning")
    projection = load_json_object(projection_bytes, label="residual image plan", max_bytes=_MAX)
    try:
        summary = validate_residual_plan(projection, original_plan)
    except ValueError:
        write_private_bytes(
            work / "blocked.json",
            canonical_bytes(
                {
                    "state": "blocked",
                    "reason_code": "residual_plan_outside_original_scope",
                    "apply_authorized": False,
                    "deployment_ready": False,
                }
            ),
        )
        raise
    moment = datetime.now(UTC).replace(microsecond=0)
    result_record = {
        **summary,
        "schema_version": "fdai.runner-image-residual-review.v1",
        "source_commit": review["source_commit"],
        "recovery_source_commit": source.commit,
        "target_binding": review["target_binding"],
        "original_review_digest": review["review_digest"],
        "original_plan_digest": review["plan_digest"],
        "original_claim_digest": canonical_digest(claim),
        "original_state_digest": hashlib.sha256(state_bytes).hexdigest(),
        "original_state_serial": state["serial"],
        "variables_digest": review["variables_digest"],
        "terraform_root_digest": root_digest,
        "terraform_digest": review["terraform_digest"],
        "plan_digest": hashlib.sha256(
            read_private_bytes(work / "residual.tfplan", max_bytes=_MAX)
        ).hexdigest(),
        "plan_json_digest": hashlib.sha256(projection_bytes).hexdigest(),
        "created_at": moment.isoformat(),
        "expires_at": (moment + timedelta(hours=1)).isoformat(),
        "original_state_unchanged": True,
    }
    result_record["review_digest"] = canonical_digest(result_record)
    write_private_bytes(work / "residual-review.json", canonical_bytes(result_record))
    return result_record


def require_only_wait_fix(original: Path, corrected: Path) -> None:
    """Require identical configuration bytes apart from the three known CLI-path edits."""

    def files(root: Path) -> dict[str, Path]:
        return {
            path.relative_to(root).as_posix(): path
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith("terraform.tfstate")
        }

    before, after = files(original), files(corrected)
    if set(before) != set(after):
        raise ValueError("runner image recovery configuration inventory changed")
    substitutions = (
        (b'$("$AZ_CLI" vm get-instance-view', b"$(az vm get-instance-view"),
        (b'      AZ_CLI = abspath("/usr/bin/az")\n', b""),
        (
            b"      VM_ID  = azurerm_linux_virtual_machine.builder.id",
            b"      VM_ID = azurerm_linux_virtual_machine.builder.id",
        ),
    )
    for name, path in before.items():
        content = read_private_bytes(path, max_bytes=4 * 1024 * 1024)
        if name == "main.tf":
            for old, new in substitutions:
                if content.count(old) != 1:
                    raise ValueError(
                        "runner image recovery original wait is not the supported failure"
                    )
                content = content.replace(old, new, 1)
        if content != read_private_bytes(after[name], max_bytes=4 * 1024 * 1024):
            raise ValueError(
                "runner image recovery includes changes beyond the trusted CLI wait fix"
            )


def main() -> int:
    """Prepare an explicitly selected residual review; this command has no apply operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-directory", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--expected-review-digest", required=True)
    parser.add_argument("--terraform", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        receipt = prepare_recovery_plan(
            repository_root=Path(__file__).resolve().parents[3], **vars(args)
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "runner image residual planning failed; preserve original state and new diagnostics",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
