"""Prepare a separately bound application-name recovery review; never apply Terraform."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import genesis_runner_image as image
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
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
from genesis_foundation_apply_contract import load_apply_claim
from genesis_foundation_recovery import select_public_ip_tags, validate_recovery_plan
from genesis_foundation_recovery_successor import (
    load_predecessor,
    require_pending_repairs,
    validate_successor_plan,
)
from genesis_foundation_workspace import verify_execution_copy
from genesis_runner_image_recovery_plan import materialize_provider_links
from genesis_subprocess import run_with_heartbeat
from source_foundation_execution import _copy_private_tree

_MAX = 64 * 1024 * 1024


def require_naming_only(original: Path, current: Path) -> None:
    """Require only application naming and the bounded operations-IP policy input."""
    old_main = (original / "main.tf").read_bytes()
    current_main = (current / "main.tf").read_bytes()
    old_variables = (original / "variables.tf").read_bytes()
    current_variables = (current / "variables.tf").read_bytes()
    if old_main == current_main and old_variables == current_variables:
        return
    expected = old_main
    replacements = (
        (
            _one_line(
                old_main,
                rb'^  suffix\s+= "\$\{var\.workload\}-\$\{var\.env\}-\$\{var\.region_short\}"$',
            ),
            _one_line(
                current_main,
                rb'^  suffix\s+= "\$\{var\.workload\}-\$\{var\.env\}-\$\{var\.region_short\}"$',
            )
            + b"\n"
            + _one_line(
                current_main,
                (
                    rb'^  application_suffix\s+= "\$\{coalesce\(var\.application_workload, '
                    rb'var\.workload\)\}-\$\{var\.env\}-\$\{var\.region_short\}"$'
                ),
            ),
        ),
        (
            _one_line(old_main, rb'^  name\s+= "rg-\$\{local\.suffix\}"$'),
            _one_line(current_main, rb'^  name\s+= "rg-\$\{local\.application_suffix\}"$'),
        ),
        (
            _one_line(old_main, rb"^  workload\s+= var\.workload$"),
            _one_line(current_main, rb"^  workload\s+= var\.workload$")
            + b"\n"
            + _one_line(
                current_main,
                rb"^  operations_public_ip_tags\s+= var\.operations_public_ip_tags$",
            ),
        ),
    )
    for before, after in replacements:
        if expected.count(before) != 1:
            raise ValueError("Foundation recovery original naming configuration is unsupported")
        expected = expected.replace(before, after, 1)
    if current_main != expected:
        raise ValueError("Foundation recovery changes more than application naming")
    variables = current_variables
    for name in ("application_workload", "operations_public_ip_tags"):
        variables = _without_variable(variables, name)
    if variables != old_variables:
        raise ValueError("Foundation recovery variable changes are outside naming scope")


def _one_line(content: bytes, pattern: bytes) -> bytes:
    matches = re.findall(pattern, content, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Foundation recovery naming configuration is unsupported")
    return bytes(matches[0])


def _foundation_variables(root: Path) -> Path:
    """Select the exact retained variables without changing bootstrap mode."""

    augmented = root / "foundation-variables-with-image.json"
    return (
        augmented
        if augmented.exists() or augmented.is_symlink()
        else root / "foundation-variables.json"
    )


def _without_variable(content: bytes, name: str) -> bytes:
    pattern = rb'^variable "' + name.encode() + rb'" \{\n.*?^\}\n\n'
    result, count = re.subn(pattern, b"", content, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise ValueError("Foundation recovery requires one exact added variable")
    return result


def require_ip_policy_only(original: Path, current: Path) -> None:
    """Permit only the explicit tag input on the two original public-IP resources."""
    old_variables = (original / "variables.tf").read_bytes()
    current_variables = (current / "variables.tf").read_bytes()
    if old_variables == current_variables and all(
        (original / name).read_bytes() == (current / name).read_bytes()
        for name in ("nat.tf", "bastion.tf")
    ):
        return
    before = b'  sku                 = "Standard"\n'
    after = before + b"  ip_tags             = var.operations_public_ip_tags\n"
    for name in ("nat.tf", "bastion.tf"):
        content = (original / name).read_bytes()
        if (
            content.count(before) != 1
            or content.replace(before, after, 1) != (current / name).read_bytes()
        ):
            raise ValueError("Foundation recovery bootstrap changes exceed IP policy scope")
    variables = _without_variable(current_variables, "operations_public_ip_tags")
    if variables != old_variables:
        raise ValueError("Foundation recovery bootstrap variable changes exceed IP policy scope")


def prepare_recovery_plan(
    *,
    repository_root: Path,
    original_directory: Path,
    source_snapshot: Path,
    work_dir: Path,
    terraform: Path,
    expected_review_digest: str,
    application_workload: str,
    timeout_seconds: int = 900,
    predecessor_directory: Path | None = None,
) -> dict[str, object]:
    """Plan under the original state lock without applying, adopting or overwriting evidence."""
    paths = (repository_root, original_directory, source_snapshot, work_dir, terraform)
    if (
        not all(path.is_absolute() for path in paths)
        or re.fullmatch(r"[a-z][a-z0-9]{1,11}", application_workload) is None
    ):
        raise ValueError(
            "Foundation recovery requires absolute paths and a valid application token"
        )
    if any(
        work_dir.resolve().is_relative_to(path.resolve())
        for path in (repository_root, original_directory, source_snapshot)
    ):
        raise ValueError("Foundation recovery output must be outside source and original state")
    if not 60 <= timeout_seconds <= 1800:
        raise ValueError("Foundation recovery planning budget must be from 60 through 1800 seconds")
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
            raise ValueError("Foundation recovery requires its original private execution lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _prepare_locked(
            repository_root,
            original_directory,
            source_snapshot,
            work_dir,
            terraform,
            expected_review_digest,
            application_workload,
            deadline,
            predecessor_directory,
        )
    finally:
        os.close(lock)


def _prepare_locked(
    repository_root: Path,
    original: Path,
    snapshot: Path,
    work: Path,
    terraform: Path,
    expected_digest: str,
    application_workload: str,
    deadline: DeploymentDeadline,
    predecessor_directory: Path | None = None,
) -> dict[str, object]:
    profile = load_profile(original.parent / "profile.json")
    if profile.environment != "dev" or profile.transport != "manual":
        raise ValueError("Foundation recovery requires the retained manual development profile")
    verify_foundation_plan(
        directory=original,
        profile=profile,
        expected_review_digest=expected_digest,
        require_unexpired=False,
    )
    review = _json(original / "foundation-plan.json")
    context = review["context"]
    if (
        not isinstance(context, dict)
        or review["schema_version"] != "fdai.foundation-saved-source-plan.v1"
    ):
        raise ValueError("Foundation recovery requires an original source plan")
    claim_path = original / "foundation-apply-claim.json"
    claim = load_apply_claim(claim_path, review=review, profile=profile)
    if claim is None or (original / "foundation-apply-receipt.json").exists():
        raise ValueError("Foundation recovery requires an incomplete claimed apply")
    claim_bytes = read_private_bytes(claim_path, max_bytes=_MAX)
    original_source = verify_source_snapshot(
        snapshot, expected_digest=str(context["source_snapshot_digest"])
    )
    if canonical_digest(original_source) != context["source_input_digest"]:
        raise ValueError("Foundation recovery original source binding changed")
    source = inspect_source(repository_root)
    current_infra = source.root / "infra/genesis-foundation"
    original_infra = snapshot / "tree/infra/genesis-foundation"
    require_naming_only(original_infra, current_infra)
    require_ip_policy_only(original_infra.parent / "bootstrap", current_infra.parent / "bootstrap")
    binary = image._trusted_terraform(terraform)
    if image._file_digest(binary) != context["terraform_digest"]:
        raise ValueError("Foundation recovery Terraform differs from original evidence")
    target = active_azure_target()
    if (
        compute_target_binding(tenant_id=target.tenant_id, subscription_id=target.subscription_id)
        != profile.target_binding
    ):
        raise ValueError("Foundation recovery active target changed")
    state_path = (
        original / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
    )
    state_bytes = read_private_bytes(state_path, max_bytes=_MAX)
    state = load_json_object(state_bytes, label="Foundation recovery state", max_bytes=_MAX)
    predecessor = None
    if predecessor_directory is not None:
        predecessor = load_predecessor(
            predecessor_directory,
            original_review_digest=expected_digest,
            original_claim_digest=canonical_digest(claim),
            source_commit=str(context["source_commit"]),
            target_binding=profile.target_binding,
        )
        require_pending_repairs(
            original_infra.parent / "bootstrap/main.tf",
            current_infra.parent / "bootstrap/main.tf",
        )
        if (
            canonical_digest({"lineage": state["lineage"]})
            != predecessor[0]["original_lineage_digest"]
        ):
            raise ValueError("Foundation successor original state lineage differs")
    parent = _open_private_parent(work)
    try:
        os.mkdir(work.name, 0o700, dir_fd=parent)
    finally:
        os.close(parent)
    reference = work / "reference"
    reference.mkdir(mode=0o700)
    _copy_private_tree(snapshot / "tree/infra", reference / "infra")
    verify_execution_copy(
        original / "foundation-apply-bundle/source", authenticated_source=reference
    )
    source_bytes = {}
    for name in (
        "genesis-foundation/main.tf",
        "genesis-foundation/variables.tf",
        "bootstrap/nat.tf",
        "bootstrap/bastion.tf",
        "bootstrap/variables.tf",
    ):
        source_bytes[name] = (current_infra.parent / name).read_bytes()
    if predecessor is not None:
        source_bytes["bootstrap/main.tf"] = (
            current_infra.parent / "bootstrap/main.tf"
        ).read_bytes()

    def ignore(directory: str, names: list[str]) -> list[str]:
        if not Path(directory).is_relative_to(reference / "infra"):
            return []
        relative = Path(directory).relative_to(reference / "infra")
        return [name for name in names if (relative / name).as_posix() in source_bytes]

    candidate = work / "source"
    shutil.copytree(reference, candidate, ignore=ignore)
    root = candidate / "infra/genesis-foundation"
    for name, content in source_bytes.items():
        write_private_bytes(candidate / "infra" / name, content)
    configuration_digest = image._execution_tree_digest(candidate)
    normalized = work / "original-variables.json"
    variables_source = _foundation_variables(original.parent)
    snapshot_foundation_input(
        variables_source,
        normalized,
        expected_target_binding=profile.target_binding,
        expected_region=profile.region,
        expected_environment=profile.environment,
    )
    variables = _json(normalized)
    if canonical_digest(variables) != context["variables_digest"]:
        raise ValueError("Foundation recovery original variables changed")
    variables["application_workload"] = application_workload
    variables["operations_public_ip_tags"] = select_public_ip_tags(state)
    if (
        predecessor is not None
        and canonical_digest(variables) != predecessor[0]["variables_digest"]
    ):
        raise ValueError("Foundation successor must preserve predecessor variables")
    write_private_bytes(work / "recovery-variables.json", canonical_bytes(variables))
    environment = image._terraform_environment(
        work, subscription_id=target.subscription_id, tenant_id=target.tenant_id
    )
    old_environment = {
        **environment,
        "TF_DATA_DIR": str(original / "terraform-data"),
        "TF_CLI_CONFIG_FILE": str(original / "source.tfrc"),
    }
    old_projection = _run(
        [str(binary), "show", "-json", str(original / "foundation.tfplan")],
        cwd=original_infra,
        environment=old_environment,
        deadline=deadline,
        work=work,
        label="original-show",
    )
    if hashlib.sha256(old_projection).hexdigest() != review["plan_json_digest"]:
        raise ValueError("Foundation recovery original plan projection changed")
    provider_digest = image._execution_tree_digest(original / "terraform-data")
    _run(
        [
            str(binary),
            "init",
            "-backend=false",
            "-input=false",
            "-lockfile=readonly",
            f"-plugin-dir={original / 'terraform-data/providers'}",
        ],
        cwd=root,
        environment=environment,
        deadline=deadline,
        work=work,
        label="init",
    )
    materialize_provider_links(
        original / "terraform-data", work / "terraform-data", provider_digest
    )
    _run(
        [str(binary), "validate", "-no-color"],
        cwd=root,
        environment=environment,
        deadline=deadline,
        work=work,
        label="validate",
    )
    _run(
        [
            str(binary),
            "plan",
            "-input=false",
            "-no-color",
            "-lock-timeout=0s",
            f"-state={state_path}",
            f"-var-file={work / 'recovery-variables.json'}",
            f"-out={work / 'recovery.tfplan'}",
        ],
        cwd=root,
        environment=environment,
        deadline=deadline,
        work=work,
        label="plan",
    )
    projection_bytes = _run(
        [str(binary), "show", "-json", str(work / "recovery.tfplan")],
        cwd=root,
        environment=environment,
        deadline=deadline,
        work=work,
        label="show",
    )
    projection = load_json_object(
        projection_bytes, label="Foundation recovery plan", max_bytes=_MAX
    )
    summary = (
        validate_successor_plan(projection, predecessor[2], state)
        if predecessor is not None
        else validate_recovery_plan(
            projection,
            load_json_object(old_projection, label="original Foundation plan", max_bytes=_MAX),
            state,
            application_workload=application_workload,
        )
    )
    application_preserved = (
        predecessor is not None or summary.get("application_group_preserved") is True
    )
    changes = cast(list[dict[str, Any]], projection["resource_changes"])
    application = next(
        entry["change"]["after"]
        for entry in changes
        if entry["address"] == "azapi_resource.app_resource_group"
    )
    exists = image._capture(
        [
            str(image._trusted_azure_cli()),
            "group",
            "show" if predecessor is not None or application_preserved else "exists",
            "--subscription",
            target.subscription_id,
            "--name",
            application["name"],
            *(("--query", "id") if predecessor is not None or application_preserved else ()),
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        cwd=work,
        env=environment,
        timeout=deadline.remaining(30),
        reason="Foundation recovery application group availability is unknown",
    )
    expected_group = (
        str(application.get("id")) if predecessor is not None or application_preserved else "false"
    )
    if exists.strip().casefold() != expected_group.casefold():
        raise ValueError("Foundation recovery application group does not match required ownership")
    source.reverify()
    if predecessor_directory is not None and predecessor != load_predecessor(
        predecessor_directory,
        original_review_digest=expected_digest,
        original_claim_digest=canonical_digest(claim),
        source_commit=str(context["source_commit"]),
        target_binding=profile.target_binding,
    ):
        raise ValueError("Foundation predecessor changed during planning")
    verify_execution_copy(
        original / "foundation-apply-bundle/source", authenticated_source=reference
    )
    if (
        read_private_bytes(state_path, max_bytes=_MAX) != state_bytes
        or read_private_bytes(claim_path, max_bytes=_MAX) != claim_bytes
        or image._execution_tree_digest(candidate) != configuration_digest
        or image._execution_tree_digest(original / "terraform-data") != provider_digest
    ):
        raise ValueError("Foundation recovery evidence changed during planning")
    deadline.remaining()
    moment = datetime.now(UTC).replace(microsecond=0)
    result = {
        **summary,
        "schema_version": "fdai.foundation-recovery-review.v1",
        "source_commit": context["source_commit"],
        "recovery_source_commit": source.commit,
        "original_review_digest": expected_digest,
        "original_claim_digest": canonical_digest(claim),
        "original_state_digest": hashlib.sha256(state_bytes).hexdigest(),
        "original_state_serial": state["serial"],
        "original_lineage_digest": canonical_digest({"lineage": state["lineage"]}),
        "target_binding": profile.target_binding,
        "variables_digest": canonical_digest(variables),
        "configuration_digest": configuration_digest,
        "provider_digest": image._execution_tree_digest(work / "terraform-data"),
        "terraform_digest": context["terraform_digest"],
        "plan_digest": hashlib.sha256(
            read_private_bytes(work / "recovery.tfplan", max_bytes=_MAX)
        ).hexdigest(),
        "plan_json_digest": hashlib.sha256(projection_bytes).hexdigest(),
        "application_group_absent": not application_preserved,
        "original_state_unchanged": True,
        "created_at": moment.isoformat(),
        "expires_at": (moment + timedelta(hours=1)).isoformat(),
    }
    if application_preserved:
        result["application_group_preserved"] = True
    if predecessor is not None:
        result.update(
            {
                "predecessor_directory": str(predecessor_directory),
                "predecessor_review_digest": predecessor[0]["review_digest"],
                "predecessor_claim_digest": canonical_digest(predecessor[1]),
                "application_group_preserved": True,
            }
        )
    result["review_digest"] = canonical_digest(result)
    write_private_bytes(work / "recovery-review.json", canonical_bytes(result))
    return result


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    deadline: DeploymentDeadline,
    work: Path,
    label: str,
) -> bytes:
    print(f"Foundation recovery planning: {label}", file=sys.stderr, flush=True)
    result = run_with_heartbeat(
        command,
        cwd=cwd,
        env=environment,
        timeout=deadline.remaining(),
        capture_output=True,
        umask=0o077,
    )
    output = str(result.stdout).encode()
    errors = str(result.stderr).encode()
    if len(output) > _MAX or len(errors) > _MAX:
        raise ValueError("Foundation recovery diagnostics exceed the private output bound")
    write_private_bytes(work / f"{label}.stdout", output)
    if errors:
        write_private_bytes(work / f"{label}.stderr", errors)
    if result.returncode:
        raise ValueError(f"Foundation recovery {label} failed; preserve private diagnostics")
    return output


def _json(path: Path) -> dict[str, object]:
    return dict(
        load_json_object(
            read_private_bytes(path, max_bytes=_MAX),
            label="Foundation recovery evidence",
            max_bytes=_MAX,
        )
    )


def main() -> int:
    """Prepare a read-only review in a fresh private directory; there is no apply option."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-directory", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--terraform", type=Path, required=True)
    parser.add_argument("--expected-review-digest", required=True)
    parser.add_argument("--application-workload", required=True)
    parser.add_argument("--predecessor-directory", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        result = prepare_recovery_plan(
            repository_root=Path(__file__).resolve().parents[3], **vars(args)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(
            "Foundation recovery planning failed; preserve original state and private diagnostics",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
