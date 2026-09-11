#!/usr/bin/env python3
"""Plan, apply, or reverify the exact pre-Foundation managed runner image locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.profile import load_profile
from genesis_approval import GenesisApproval, load_genesis_approval
from genesis_checks import CheckError, GenesisChecks
from genesis_runner_image_contract import (
    CLAIM_NAME,
    PLAN_JSON_NAME,
    PLAN_NAME,
    RECEIPT_NAME,
    add_source_image_version,
    create_private_directory,
    create_review,
    executor_identity_digest,
    hash_tree,
    load_review,
    load_runner_image_inputs,
    materialize_foundation_image_input,
    snapshot_terraform_root,
)
from genesis_runner_image_observation import verify_runner_image_effect
from genesis_subprocess import run_with_heartbeat

_DIGEST = re.compile(r"[0-9a-f]{64}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    plan = commands.add_parser("plan")
    _common(plan)
    plan.set_defaults(handler=_plan)
    apply = commands.add_parser("apply")
    _common(apply, variables=False)
    apply.add_argument("--expected-review-digest", required=True)
    apply.add_argument("--expected-plan-digest", required=True)
    apply.add_argument("--repository", required=True)
    apply.add_argument("--approval-file", type=Path)
    apply.add_argument("--approve", action="store_true")
    apply.add_argument("--resume-verification", action="store_true")
    apply.set_defaults(handler=_apply)
    handoff = commands.add_parser("foundation-input")
    handoff.add_argument("--source", type=Path, required=True)
    handoff.add_argument("--image-receipt", type=Path, required=True)
    handoff.add_argument("--profile", type=Path, required=True)
    handoff.add_argument("--destination", type=Path, required=True)
    handoff.add_argument("--output", choices=("text", "json"), default="text")
    handoff.set_defaults(handler=_foundation_input)
    return parser


def _common(parser: argparse.ArgumentParser, *, variables: bool = True) -> None:
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    if variables:
        parser.add_argument("--foundation-variables", type=Path, required=True)
    parser.add_argument("--terraform", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=7800)
    parser.add_argument("--output", choices=("text", "json"), default="text")


def _plan(args: argparse.Namespace) -> int:
    root = _repository_root()
    work_dir = _absolute(args.work_dir)
    if work_dir.exists() or work_dir.is_symlink():
        raise ValueError("runner image plan work directory must not already exist")
    _validate_timeout(args.timeout_seconds)
    create_private_directory(work_dir)
    variables = work_dir / "runner-image.auto.tfvars.json"
    inputs = load_runner_image_inputs(
        foundation_variables=_absolute(args.foundation_variables),
        profile_path=_absolute(args.profile),
        repository_root=root,
        destination=variables,
    )
    current_source = _capture(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=root,
        timeout=30,
        reason="runner image source revision is unavailable",
    ).strip()
    if current_source != inputs.source_commit:
        raise ValueError("runner image input source does not match the active checkout")
    if _capture(
        ["/usr/bin/git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        timeout=30,
        reason="runner image checkout status is unavailable",
    ).strip():
        raise ValueError("runner image planning requires a clean checkout")
    environment = _terraform_environment(
        work_dir,
        subscription_id=str(inputs.terraform_values["subscription_id"]),
        tenant_id=str(inputs.terraform_values["tenant_id"]),
    )
    checks = GenesisChecks(root, environment=environment)
    checks.verify_target(
        subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID", ""),
        tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
        region=str(inputs.terraform_values["region"]),
    )
    version = _capture(
        [
            str(_trusted_azure_cli()),
            "vm",
            "image",
            "show",
            "--location",
            str(inputs.terraform_values["region"]),
            "--urn",
            "Canonical:ubuntu-24_04-lts:server:latest",
            "--query",
            "name",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        cwd=root,
        env=environment,
        timeout=60,
        reason="runner source image resolution failed",
    ).strip()
    inputs = add_source_image_version(inputs, version=version, destination=variables)
    terraform_root = work_dir / "root"
    root_digest = snapshot_terraform_root(
        root / "infra/genesis-runner-image",
        terraform_root,
        source_commit=inputs.source_commit,
    )
    if (
        _capture(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=root,
            timeout=30,
            reason="runner image source revision is unavailable",
        ).strip()
        != current_source
        or _capture(
            ["/usr/bin/git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            timeout=30,
            reason="runner image checkout status is unavailable",
        ).strip()
    ):
        raise ValueError("runner image checkout changed during snapshot")
    terraform = _trusted_terraform(_absolute(args.terraform))
    terraform_digest = _file_digest(terraform)
    if terraform_digest != inputs.terraform_values.get("terraform_binary_sha256"):
        raise ValueError("runner image Terraform executable does not match the pinned toolchain")
    _required(
        [str(terraform), "init", "-backend=false", "-input=false", "-lockfile=readonly"],
        cwd=terraform_root,
        env=environment,
        timeout=300,
        reason="runner image Terraform initialization failed",
    )
    _required(
        [
            str(terraform),
            "plan",
            "-input=false",
            "-no-color",
            f"-var-file={variables}",
            f"-out={work_dir / PLAN_NAME}",
        ],
        cwd=terraform_root,
        env=environment,
        timeout=min(args.timeout_seconds, 900),
        reason="runner image Terraform plan failed",
    )
    projection = _capture_bytes(
        [str(terraform), "show", "-json", str(work_dir / PLAN_NAME)],
        cwd=terraform_root,
        env=environment,
        timeout=300,
        reason="runner image plan inspection failed",
    )
    _exclusive_bytes(work_dir / PLAN_JSON_NAME, projection)
    review = create_review(
        directory=work_dir,
        inputs=inputs,
        root_digest=root_digest,
        terraform_digest=terraform_digest,
        provider_digest=_execution_tree_digest(work_dir / "terraform-data"),
    )
    result = {
        "schema_version": "fdai.genesis-runner-image-plan-result.v1",
        "state": "review",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "expires_at": review["expires_at"],
        "create_count": review["create_count"],
        "retained_resource_count": review["retained_resource_count"],
        "lifecycle_actions": review["lifecycle_actions"],
        "effect_summary": review["effect_summary"],
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    _print(result, args.output, "runner image plan ready for exact review; no apply authorized")
    return 0


def _apply(args: argparse.Namespace) -> int:
    if args.approve == args.resume_verification:
        raise ValueError("runner image apply requires exactly one approval or verification resume")
    if _DIGEST.fullmatch(args.expected_plan_digest) is None:
        raise ValueError("expected runner image plan digest is invalid")
    _validate_timeout(args.timeout_seconds)
    root = _repository_root()
    work_dir = _absolute(args.work_dir)
    claim_path = work_dir / CLAIM_NAME
    receipt_path = work_dir / RECEIPT_NAME
    effect_started = claim_path.exists() or receipt_path.exists()
    review = load_review(
        work_dir,
        expected_review_digest=args.expected_review_digest,
        require_unexpired=not effect_started,
    )
    profile = load_profile(_absolute(args.profile))
    if (
        profile.target_binding != review["target_binding"]
        or profile.environment != review["environment"]
        or profile.region != review["region"]
        or canonical_digest(profile.to_mapping()) != review["profile_digest"]
    ):
        raise ValueError("runner image review does not match the provision profile")
    if (
        profile.environment != "dev"
        or profile.transport != "manual"
        or profile.approval_quorum != 1
    ):
        raise ValueError(
            "runner image local approval requires the dev manual single-approver profile"
        )
    if review["plan_digest"] != args.expected_plan_digest:
        raise ValueError("expected runner image plan digest does not match the review")
    if hash_tree(work_dir / "root") != review["terraform_root_digest"]:
        raise ValueError("runner image Terraform root changed after planning")
    terraform = _trusted_terraform(_absolute(args.terraform))
    if _file_digest(terraform) != review["terraform_digest"]:
        raise ValueError("runner image Terraform executable changed after planning")
    environment = _terraform_environment(
        work_dir,
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        tenant_id=os.environ["AZURE_TENANT_ID"],
    )
    checks = GenesisChecks(root, environment=environment)
    checks.verify_target(
        subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID", ""),
        tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
        region=_reviewed_region(work_dir),
    )
    checks.verify_source(
        source_commit=str(review["source_commit"]), repository=args.repository, apply=True
    )
    current_source = _capture(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=root,
        timeout=30,
        reason="runner image source revision is unavailable",
    ).strip()
    if current_source != review["source_commit"]:
        raise ValueError("runner image review source does not match the active checkout")
    claim = _load_apply_claim(claim_path, review=review)
    if receipt_path.exists():
        if claim is None:
            raise ValueError("runner image receipt is missing its immutable claim")
        receipt = _load_apply_receipt(receipt_path, review=review, claim=claim)
        observed = _verify_effect(
            work_dir=work_dir,
            terraform=terraform,
            review=review,
            claim=claim,
            timeout=min(args.timeout_seconds, 600),
        )
        _require_same_effect(receipt, observed)
        _print(receipt, args.output, "runner image apply already has an exact receipt")
        return 0
    if args.resume_verification:
        if claim is None:
            raise ValueError("runner image verification resume requires an existing apply claim")
    else:
        if claim is not None:
            raise ValueError(
                "runner image apply claim already exists; only verification may resume"
            )
        approval = _require_apply_approval(args.approval_file, review=review)
        credential_actor_digest = _operator_digest(str(review["run_digest"]), root=root)
        if credential_actor_digest != approval.actor_digest:
            raise ValueError("runner image approver does not match the current Azure operator")
        executor_digest = executor_identity_digest(review)
        if _execution_tree_digest(work_dir / "terraform-data") != review["provider_digest"]:
            raise ValueError("runner image provider execution tree changed after planning")
        claimed_at = _utc_now().replace(microsecond=0).isoformat()
        claim = {
            "schema_version": "fdai.genesis-runner-image-apply-claim.v1",
            "state": "applying",
            "review_digest": review["review_digest"],
            "plan_digest": review["plan_digest"],
            "target_binding": review["target_binding"],
            "source_commit": review["source_commit"],
            "run_digest": review["run_digest"],
            "environment": review["environment"],
            "region": review["region"],
            "profile_digest": review["profile_digest"],
            "approver_actor_digest": approval.actor_digest,
            "credential_actor_digest": credential_actor_digest,
            "executor_identity_digest": executor_digest,
            "idempotency_key": canonical_digest(
                {
                    "target_binding": review["target_binding"],
                    "plan_digest": review["plan_digest"],
                }
            ),
            "claimed_at": claimed_at,
            "mutation_performed": False,
            "subscription_ready": False,
        }
        write_private_output(
            claim_path, json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n"
        )
        _required(
            [str(terraform), "apply", "-input=false", "-no-color", str(work_dir / PLAN_NAME)],
            cwd=work_dir / "root",
            env=environment,
            timeout=args.timeout_seconds,
            reason="runner image exact apply failed; automatic retry is blocked",
        )
    receipt = _verify_effect(
        work_dir=work_dir,
        terraform=terraform,
        review=review,
        claim=claim,
        timeout=min(args.timeout_seconds, 600),
    )
    write_private_output(
        receipt_path, json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    )
    _print(receipt, args.output, "runner image apply and independent readback completed")
    return 0


def _foundation_input(args: argparse.Namespace) -> int:
    result = materialize_foundation_image_input(
        source=_absolute(args.source),
        image_receipt=_absolute(args.image_receipt),
        profile_path=_absolute(args.profile),
        destination=_absolute(args.destination),
    )
    safe = {key: value for key, value in result.items() if key != "target_binding"}
    _print(safe, args.output, "private Foundation image input prepared")
    return 0


def _verify_effect(
    *,
    work_dir: Path,
    terraform: Path,
    review: Mapping[str, object],
    claim: Mapping[str, object],
    timeout: int,
) -> dict[str, object]:
    environment = _terraform_environment(
        work_dir,
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        tenant_id=os.environ["AZURE_TENANT_ID"],
    )
    azure_cli = _trusted_azure_cli()

    def trusted_capture(command: list[str], *, cwd: Path, timeout: int, reason: str) -> str:
        if not command or command[0] != "az":
            raise ValueError("runner image observation command is invalid")
        return _capture(
            [str(azure_cli), *command[1:]],
            cwd=cwd,
            env=environment,
            timeout=timeout,
            reason=reason,
        )

    raw_output = _capture(
        [str(terraform), "output", "-json", "runner_image"],
        cwd=work_dir / "root",
        env=environment,
        timeout=120,
        reason="runner image Terraform output readback failed",
    )
    value = json.loads(raw_output)
    if not isinstance(value, dict):
        raise ValueError("runner image Terraform output is invalid")
    image_id = verify_runner_image_effect(
        terraform_output=value,
        review=review,
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        capture=trusted_capture,
        cwd=work_dir,
        timeout=timeout,
    )
    if value.get("runner_registered") is not False or value.get("subscription_ready") is not False:
        raise ValueError("runner image independent readback does not match the reviewed plan")
    completed = _utc_now().replace(microsecond=0).isoformat()
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "run_digest": review["run_digest"],
        "environment": review["environment"],
        "region": review["region"],
        "profile_digest": review["profile_digest"],
        "toolchain_digest": review["toolchain_digest"],
        "claim_digest": canonical_digest(dict(claim)),
        "approver_actor_digest": claim["approver_actor_digest"],
        "credential_actor_digest": claim["credential_actor_digest"],
        "executor_identity_digest": claim["executor_identity_digest"],
        "runner_image_id": image_id,
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": completed,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def _reviewed_region(work_dir: Path) -> str:
    values = json.loads((work_dir / "runner-image.auto.tfvars.json").read_text(encoding="utf-8"))
    region = values.get("region") if isinstance(values, dict) else None
    if not isinstance(region, str):
        raise ValueError("runner image reviewed region is invalid")
    return region


def _require_apply_approval(path: Path | None, *, review: Mapping[str, object]) -> GenesisApproval:
    """Require current exact-evidence authority at the mutating image boundary."""

    approval = load_genesis_approval(
        _absolute(path) if path is not None else None,
        run_binding=str(review["run_digest"]),
        source_commit=str(review["source_commit"]),
    )
    if approval is None or not approval.authorizes(
        "runner-image",
        review_digest=str(review["review_digest"]),
        plan_digest=str(review["plan_digest"]),
    ):
        raise ValueError("runner image exact approval is required")
    return approval


def _operator_digest(run_binding: str, *, root: Path) -> str:
    raw = _capture(
        [
            "/usr/bin/az",
            "account",
            "show",
            "--query",
            "{tenantId:tenantId,type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ],
        cwd=root,
        timeout=30,
        reason="authenticated operator identity is unavailable",
    )
    object_id = (
        _capture(
            [
                "/usr/bin/az",
                "ad",
                "signed-in-user",
                "show",
                "--query",
                "id",
                "--output",
                "tsv",
                "--only-show-errors",
            ],
            cwd=root,
            timeout=30,
            reason="authenticated operator identity is unavailable",
        )
        .strip()
        .casefold()
    )
    user = json.loads(raw)
    if (
        not isinstance(user, dict)
        or user.get("type") != "user"
        or not isinstance(user.get("tenantId"), str)
        or re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
            str(user["tenantId"]),
        )
        is None
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", object_id) is None
    ):
        raise ValueError("foundation image apply requires an authenticated human operator")
    return hashlib.sha256(
        f"{run_binding}:{str(user['tenantId']).casefold()}:{object_id}".encode()
    ).hexdigest()


def _load_apply_claim(path: Path, *, review: Mapping[str, object]) -> dict[str, object] | None:
    if not path.exists():
        return None
    claim = read_plan_input(path)
    expected_idempotency = canonical_digest(
        {
            "target_binding": review["target_binding"],
            "plan_digest": review["plan_digest"],
        }
    )
    claimed_at = _utc_timestamp(claim.get("claimed_at"))
    if (
        set(claim)
        != {
            "schema_version",
            "state",
            "review_digest",
            "plan_digest",
            "target_binding",
            "source_commit",
            "run_digest",
            "environment",
            "region",
            "profile_digest",
            "approver_actor_digest",
            "credential_actor_digest",
            "executor_identity_digest",
            "idempotency_key",
            "claimed_at",
            "mutation_performed",
            "subscription_ready",
        }
        or claim.get("schema_version") != "fdai.genesis-runner-image-apply-claim.v1"
        or claim.get("state") != "applying"
        or claim.get("review_digest") != review["review_digest"]
        or claim.get("plan_digest") != review["plan_digest"]
        or claim.get("target_binding") != review["target_binding"]
        or claim.get("source_commit") != review["source_commit"]
        or claim.get("run_digest") != review["run_digest"]
        or claim.get("environment") != review["environment"]
        or claim.get("region") != review["region"]
        or claim.get("profile_digest") != review["profile_digest"]
        or claim.get("idempotency_key") != expected_idempotency
        or not isinstance(claim.get("approver_actor_digest"), str)
        or _DIGEST.fullmatch(str(claim["approver_actor_digest"])) is None
        or claim.get("credential_actor_digest") != claim.get("approver_actor_digest")
        or not isinstance(claim.get("executor_identity_digest"), str)
        or _DIGEST.fullmatch(str(claim["executor_identity_digest"])) is None
        or claim.get("executor_identity_digest") == claim.get("approver_actor_digest")
        or claim.get("executor_identity_digest") != executor_identity_digest(dict(review))
        or claimed_at > _utc_now()
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
    ):
        raise ValueError("runner image apply claim does not match the reviewed plan")
    return claim


def _load_apply_receipt(
    path: Path, *, review: Mapping[str, object], claim: Mapping[str, object]
) -> dict[str, object]:
    receipt = read_plan_input(path)
    digest = receipt.pop("receipt_digest", None)
    if (
        not isinstance(digest, str)
        or canonical_digest(receipt) != digest
        or receipt.get("schema_version") != "fdai.genesis-runner-image-apply-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("review_digest") != review["review_digest"]
        or receipt.get("plan_digest") != review["plan_digest"]
        or receipt.get("target_binding") != review["target_binding"]
        or receipt.get("source_commit") != review["source_commit"]
        or receipt.get("run_digest") != review["run_digest"]
        or receipt.get("environment") != review["environment"]
        or receipt.get("region") != review["region"]
        or receipt.get("profile_digest") != review["profile_digest"]
        or receipt.get("toolchain_digest") != review["toolchain_digest"]
        or receipt.get("claim_digest") != canonical_digest(dict(claim))
        or receipt.get("approver_actor_digest") != claim.get("approver_actor_digest")
        or receipt.get("credential_actor_digest") != claim.get("credential_actor_digest")
        or receipt.get("executor_identity_digest") != claim.get("executor_identity_digest")
        or receipt.get("effect_verified") is not True
        or receipt.get("runner_registered") is not False
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
    ):
        raise ValueError("runner image receipt does not match the reviewed plan")
    receipt["receipt_digest"] = digest
    return receipt


def _require_same_effect(receipt: Mapping[str, object], observed: Mapping[str, object]) -> None:
    ignored = {"completed_at", "receipt_digest"}
    if {key: value for key, value in receipt.items() if key not in ignored} != {
        key: value for key, value in observed.items() if key not in ignored
    }:
        raise ValueError("runner image current readback differs from its exact receipt")


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("runner image claim timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("runner image claim timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("runner image claim timestamp is invalid")
    return parsed.astimezone(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint


def _terraform_environment(
    work_dir: Path, *, subscription_id: str, tenant_id: str
) -> dict[str, str]:
    if any(
        key.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG", "ARM_")) or key == "TF_WORKSPACE"
        for key in os.environ
    ):
        allowed_arm = {
            "ARM_RESOURCE_PROVIDER_REGISTRATIONS",
            "ARM_SUBSCRIPTION_ID",
            "ARM_TENANT_ID",
        }
        if any(
            key.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG"))
            or key == "TF_WORKSPACE"
            or (key.startswith("ARM_") and key not in allowed_arm)
            for key in os.environ
        ) or (
            os.environ.get("ARM_SUBSCRIPTION_ID", subscription_id) != subscription_id
            or os.environ.get("ARM_TENANT_ID", tenant_id) != tenant_id
        ):
            raise ValueError("ambient Terraform control variables are not accepted")
    terraform_home = work_dir / "terraform-home"
    terraform_home.mkdir(mode=0o700, exist_ok=True)
    if terraform_home.is_symlink() or terraform_home.stat().st_mode & 0o077:
        raise ValueError("runner image Terraform home is not private")
    cli_config = terraform_home / "terraform.rc"
    if cli_config.exists() or cli_config.is_symlink():
        if (
            cli_config.is_symlink()
            or not cli_config.is_file()
            or cli_config.stat().st_mode & 0o077
            or cli_config.read_bytes() != b""
        ):
            raise ValueError("runner image Terraform CLI configuration is not empty")
    else:
        _exclusive_bytes(cli_config, b"")
    azure_config = Path(os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))).resolve(
        strict=True
    )
    if not azure_config.is_dir() or azure_config.stat().st_mode & 0o022:
        raise ValueError("Azure CLI configuration directory is not trusted")
    github_config = Path(
        os.environ.get("GH_CONFIG_DIR", str(Path.home() / ".config" / "gh"))
    ).resolve(strict=True)
    if not github_config.is_dir() or github_config.stat().st_mode & 0o022:
        raise ValueError("GitHub CLI configuration directory is not trusted")
    trusted_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    az_cli = shutil.which("az", path=trusted_path)
    if az_cli is None or _trusted_executable(Path(az_cli), label="Azure CLI") != Path(
        "/usr/bin/az"
    ).resolve(strict=True):
        raise ValueError("Azure CLI executable is not trusted")
    return {
        "AZURE_CONFIG_DIR": str(azure_config),
        "GH_CONFIG_DIR": str(github_config),
        "HOME": str(terraform_home),
        "PATH": trusted_path,
        "TF_CLI_CONFIG_FILE": str(cli_config),
        "TF_DATA_DIR": str(work_dir / "terraform-data"),
        "TF_IN_AUTOMATION": "1",
        "ARM_SUBSCRIPTION_ID": subscription_id,
        "ARM_TENANT_ID": tenant_id,
        "ARM_RESOURCE_PROVIDER_REGISTRATIONS": "none",
    }


def _trusted_terraform(path: Path) -> Path:
    return _trusted_executable(path, label="runner image Terraform")


def _trusted_azure_cli() -> Path:
    expected = Path("/usr/bin/az").resolve(strict=True)
    return _trusted_executable(expected, label="Azure CLI")


def _trusted_executable(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    details = resolved.stat()
    if not resolved.is_file() or details.st_mode & 0o022 or not os.access(resolved, os.X_OK):
        raise ValueError(f"{label} executable is not trusted")
    return resolved


def _file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _execution_tree_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("runner image provider execution tree is invalid")
    checksum = hashlib.sha256()
    files: list[Path] = []
    for entry in sorted(root.rglob("*")):
        details = entry.lstat()
        if stat.S_ISLNK(details.st_mode) or not (
            stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode)
        ):
            raise ValueError("runner image provider execution tree is invalid")
        if stat.S_ISREG(details.st_mode):
            files.append(entry)
    if not files:
        raise ValueError("runner image provider execution tree is empty")
    for entry in files:
        relative = entry.relative_to(root).as_posix().encode("utf-8")
        checksum.update(len(relative).to_bytes(4, "big"))
        checksum.update(relative)
        checksum.update((entry.stat().st_mode & 0o777).to_bytes(2, "big"))
        with entry.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
    return checksum.hexdigest()


def _required(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> None:
    try:
        completed = run_with_heartbeat(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            capture_output=True,
            umask=0o077,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(reason) from exc
    if completed.returncode != 0:
        raise ValueError(reason)


def _capture(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = run_with_heartbeat(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            capture_output=True,
            umask=0o077,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(reason) from exc
    if completed.returncode != 0:
        raise ValueError(reason)
    return completed.stdout


def _capture_bytes(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> bytes:
    return _capture(command, cwd=cwd, timeout=timeout, reason=reason, env=env).encode("utf-8")


def _exclusive_bytes(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _validate_timeout(value: int) -> None:
    if not 900 <= value <= 14_400:
        raise ValueError("runner image timeout must be from 900 through 14400 seconds")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint


def _print(result: Mapping[str, object], output: str, text: str) -> None:
    safe = dict(result)
    if result.get("schema_version") == "fdai.genesis-runner-image-apply-receipt.v1":
        safe = {
            key: result[key]
            for key in (
                "schema_version",
                "state",
                "review_digest",
                "plan_digest",
                "toolchain_digest",
                "effect_verified",
                "runner_registered",
                "mutation_performed",
                "subscription_ready",
                "completed_at",
                "receipt_digest",
            )
        }
    print(json.dumps(safe, sort_keys=True, separators=(",", ":")) if output == "json" else text)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one local exact runner-image operation with stable failure output."""

    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        CheckError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        reason = exc.reason_code if isinstance(exc, CheckError) else str(exc)
        print(f"genesis-runner-image: {reason}", file=sys.stderr)
        return exc.exit_code if isinstance(exc, CheckError) else 3


if __name__ == "__main__":
    raise SystemExit(main())
