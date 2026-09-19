#!/usr/bin/env python3
"""Plan and apply the existing-platform Operator pseudonym key prerequisite."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import manual_operator_update as service_update
import manual_operator_update_contract as common

_ADDRESSES = {
    "random_id.cost_pseudonym_key[0]",
    "azurerm_key_vault_secret.cost_pseudonym_key[0]",
    "azurerm_role_assignment.operator_cost_pseudonym_secret_reader[0]",
}
_SECRET_ID = re.compile(
    r"https://[a-z0-9-]{3,24}[.]vault[.]azure[.]net/secrets/"
    r"[A-Za-z0-9-]{1,127}/[A-Za-z0-9-]{1,64}"
)


def prepare(
    *, source_root: Path, target_path: Path, work_dir: Path, ttl_seconds: int = 1200
) -> dict[str, Any]:
    """Create a saved three-resource platform prerequisite plan."""

    if not 60 <= ttl_seconds <= 1200:
        raise common.ManualOperatorUpdateError(
            "manual Operator platform plan TTL must be 60-1200 seconds"
        )
    source_commit = common._verified_source(source_root)
    target = common._target(target_path)
    if work_dir.exists() or work_dir.is_symlink():
        raise common.ManualOperatorUpdateError(
            "manual Operator platform work directory already exists"
        )
    work_dir.mkdir(mode=0o700)
    common._login_identity(source_root, target)
    platform_root = source_root / "infra"
    common._terraform_init(platform_root, target, "fdai-dev.tfstate")
    outputs = common._terraform_outputs(platform_root)
    existing_secret = outputs.get("cost_pseudonym_key_secret_id")
    if isinstance(existing_secret, str) and existing_secret:
        raise common.ManualOperatorUpdateError(
            "platform Cost pseudonym key prerequisite already exists"
        )
    key_vault_id = common._resource_id(outputs.get("key_vault_id"), "platform Key Vault")
    identities = common._object(
        outputs.get("runtime_identity_bindings"), "platform runtime identities"
    )
    operator = common._object(identities.get("operator"), "platform Operator identity")
    principal_id = common._text(operator.get("principal_id"), "Operator principal id")
    if common._GUID.fullmatch(principal_id) is None:
        raise common.ManualOperatorUpdateError("platform Operator principal id is invalid")
    key_vault = common._json_command(
        (
            "az",
            "resource",
            "show",
            "--ids",
            key_vault_id,
            "--api-version",
            "2023-07-01",
            "--only-show-errors",
            "--output",
            "json",
        ),
        timeout=60,
        label="platform Key Vault readback",
    )
    tags = key_vault.get("tags")
    if not isinstance(tags, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in tags.items()
    ):
        raise common.ManualOperatorUpdateError("platform Key Vault tags are invalid")

    root = source_root / "infra/operator-platform-prerequisite"
    common._write_private(
        work_dir / "platform.tfvars.json",
        {
            "subscription_id": target["subscription_id"],
            "tenant_id": target["tenant_id"],
            "key_vault_id": key_vault_id,
            "operator_principal_id": principal_id,
            "tags": tags,
        },
    )
    common._terraform_init(root, target, "fdai-dev.tfstate")
    plan_path = work_dir / "platform.tfplan"
    command = [
        "terraform",
        f"-chdir={root}",
        "plan",
        "-input=false",
        "-lock-timeout=5m",
        f"-var-file={work_dir / 'platform.tfvars.json'}",
        f"-out={plan_path}",
    ]
    command.extend(f"-target={address}" for address in sorted(_ADDRESSES))
    common._run(tuple(command), timeout=1800, label="Operator platform prerequisite plan")
    os.chmod(plan_path, 0o600)
    plan_json_path = work_dir / "platform-plan.json"
    plan_json = common._json_command(
        ("terraform", f"-chdir={root}", "show", "-json", str(plan_path)),
        timeout=300,
        label="Operator platform plan projection",
    )
    _validate_plan(plan_json)
    common._write_private(plan_json_path, plan_json)
    created_at = datetime.now(UTC)
    review: dict[str, Any] = {
        "schema_version": "fdai.manual-operator-platform-review.v1",
        "source_commit": source_commit,
        "target_binding": common._target_binding(target),
        "plan_digest": common._file_digest(plan_path),
        "plan_json_digest": common._file_digest(plan_json_path),
        "resource_addresses": sorted(_ADDRESSES),
        "action": "terraform_apply_saved_platform_prerequisite_plan",
        "stop_condition": "plan_or_target_drift_or_failed_effect_readback",
        "rollback_action": "state_forward_only_verify_before_service_apply",
        "blast_radius": "one_key_vault_secret_and_one_exact_role_assignment",
        "idempotency_key": common._canonical_digest(
            {
                "target_binding": common._target_binding(target),
                "resource_addresses": sorted(_ADDRESSES),
            }
        ),
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "mutation_performed": False,
    }
    review["review_digest"] = common._canonical_digest(review)
    common._write_private(work_dir / "review.json", review)
    common._write_private(work_dir / "target.json", target)
    return review


def apply(
    *, source_root: Path, work_dir: Path, approval_path: Path, timeout_seconds: int = 1800
) -> dict[str, Any]:
    """Apply the saved prerequisite once and verify secret plus role readback."""

    review = common._review(work_dir / "review.json")
    if review.get("schema_version") != "fdai.manual-operator-platform-review.v1":
        raise common.ManualOperatorUpdateError("manual Operator platform review is invalid")
    target = common._target(work_dir / "target.json")
    approval = common._approval(approval_path, review)
    if common._verified_source(source_root) != review["source_commit"]:
        raise common.ManualOperatorUpdateError(
            "manual Operator platform source changed after planning"
        )
    common._login_identity(source_root, target)
    if approval["actor_digest"] == common._executor_digest(target):
        raise common.ManualOperatorUpdateError(
            "manual Operator platform approver and executor must differ"
        )
    plan_path = work_dir / "platform.tfplan"
    plan_json_path = work_dir / "platform-plan.json"
    if common._file_digest(plan_path) != review["plan_digest"]:
        raise common.ManualOperatorUpdateError(
            "manual Operator platform plan changed after approval"
        )
    if common._file_digest(plan_json_path) != review["plan_json_digest"]:
        raise common.ManualOperatorUpdateError(
            "manual Operator platform projection changed after approval"
        )
    _validate_plan(common._read_private_object(plan_json_path, "platform plan projection"))
    root = source_root / "infra/operator-platform-prerequisite"
    common._terraform_init(root, target, "fdai-dev.tfstate")
    lock_descriptor = os.open(
        work_dir / "target.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise common.ManualOperatorUpdateError(
                "manual Operator platform target is locked"
            ) from exc
        receipt_path = work_dir / "receipt.json"
        if receipt_path.is_file():
            return _receipt(receipt_path, review)
        if (work_dir / "claim.json").exists():
            raise common.ManualOperatorUpdateError(
                "manual Operator platform claim exists; verify before recovery"
            )
        claim: dict[str, Any] = {
            "schema_version": "fdai.manual-operator-platform-claim.v1",
            "review_digest": review["review_digest"],
            "approval_digest": approval["approval_digest"],
            "plan_digest": review["plan_digest"],
            "idempotency_key": review["idempotency_key"],
            "executor_digest": common._executor_digest(target),
            "claimed_at": datetime.now(UTC).isoformat(),
            "mutation_performed": False,
        }
        claim["claim_digest"] = common._canonical_digest(claim)
        common._write_private(work_dir / "claim.json", claim)
        common._run(
            (
                "terraform",
                f"-chdir={root}",
                "apply",
                "-input=false",
                "-lock-timeout=5m",
                str(plan_path),
            ),
            timeout=timeout_seconds,
            label="Operator platform prerequisite apply",
        )
        outputs = common._terraform_outputs(root)
        inputs = common._read_private_object(
            work_dir / "platform.tfvars.json", "Operator platform inputs"
        )
        secret_id = common._text(
            outputs.get("cost_pseudonym_key_secret_id"), "Cost pseudonym key secret id"
        )
        if _SECRET_ID.fullmatch(secret_id) is None:
            raise common.ManualOperatorUpdateError("Cost pseudonym key secret readback is invalid")
        observed_secret = common._capture(
            (
                "az",
                "keyvault",
                "secret",
                "show",
                "--id",
                secret_id,
                "--query",
                "id",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            60,
            "Cost pseudonym key readback",
        ).strip()
        if observed_secret.casefold() != secret_id.casefold():
            raise common.ManualOperatorUpdateError(
                "Cost pseudonym key readback differs from Terraform"
            )
        role_count = common._capture(
            (
                "az",
                "role",
                "assignment",
                "list",
                "--assignee-object-id",
                str(inputs["operator_principal_id"]),
                "--scope",
                f"{str(inputs['key_vault_id']).rstrip('/')}/secrets/fdai-cost-pseudonym-key",
                "--query",
                "[?roleDefinitionName=='Key Vault Secrets User'] | length(@)",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            60,
            "Cost pseudonym role readback",
        ).strip()
        if role_count != "1":
            raise common.ManualOperatorUpdateError(
                "Cost pseudonym key role assignment is not exact"
            )
        receipt: dict[str, Any] = {
            "schema_version": "fdai.manual-operator-platform-receipt.v1",
            "state": "applied",
            "review_digest": review["review_digest"],
            "plan_digest": review["plan_digest"],
            "secret_reference_digest": common._canonical_digest(secret_id.casefold()),
            "secret_readback_verified": True,
            "role_readback_verified": True,
            "completed_at": datetime.now(UTC).isoformat(),
            "mutation_performed": True,
        }
        receipt["receipt_digest"] = common._canonical_digest(receipt)
        common._write_private(receipt_path, receipt)
        return receipt
    finally:
        os.close(lock_descriptor)


def _validate_plan(plan: dict[str, Any]) -> None:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise common.ManualOperatorUpdateError(
            "Operator platform plan resource changes are invalid"
        )
    observed: set[str] = set()
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise common.ManualOperatorUpdateError(
                "Operator platform plan contains an invalid resource"
            )
        actions = common._object(entry.get("change"), "platform resource change").get("actions")
        if entry["address"] not in _ADDRESSES or actions != ["create"]:
            raise common.ManualOperatorUpdateError(
                "Operator platform plan exceeds the prerequisite boundary"
            )
        observed.add(entry["address"])
    if observed != _ADDRESSES:
        raise common.ManualOperatorUpdateError("Operator platform prerequisite plan is incomplete")
    output_changes = plan.get("output_changes")
    if not isinstance(output_changes, dict) or set(output_changes) != {
        "cost_pseudonym_key_secret_id"
    }:
        raise common.ManualOperatorUpdateError("Operator platform plan output changes are invalid")
    output_change = common._object(
        output_changes["cost_pseudonym_key_secret_id"], "platform output change"
    )
    if output_change.get("actions") not in (["create"], ["update"]):
        raise common.ManualOperatorUpdateError("Operator platform secret output action is invalid")
    if plan.get("resource_drift") not in (None, []) or plan.get("deferred_changes") not in (
        None,
        [],
    ):
        raise common.ManualOperatorUpdateError("Operator platform plan contains unresolved drift")


def _receipt(path: Path, review: dict[str, Any]) -> dict[str, Any]:
    value = common._read_private_object(path, "manual Operator platform receipt")
    digest = value.get("receipt_digest")
    if (
        value.get("schema_version") != "fdai.manual-operator-platform-receipt.v1"
        or value.get("review_digest") != review["review_digest"]
        or value.get("secret_readback_verified") is not True
        or value.get("role_readback_verified") is not True
        or value.get("mutation_performed") is not True
        or digest
        != common._canonical_digest(
            {key: item for key, item in value.items() if key != "receipt_digest"}
        )
    ):
        raise common.ManualOperatorUpdateError("manual Operator platform receipt is invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--source-root", type=Path, required=True)
    plan.add_argument("--target", type=Path, required=True)
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--ttl-seconds", type=int, default=1200)
    approval = commands.add_parser("approve")
    approval.add_argument("--target", type=Path, required=True)
    approval.add_argument("--review", type=Path, required=True)
    approval.add_argument("--output", type=Path, required=True)
    apply_command = commands.add_parser("apply")
    apply_command.add_argument("--source-root", type=Path, required=True)
    apply_command.add_argument("--work-dir", type=Path, required=True)
    apply_command.add_argument("--approval", type=Path, required=True)
    apply_command.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = prepare(
                source_root=args.source_root.resolve(),
                target_path=args.target.resolve(),
                work_dir=args.work_dir.resolve(),
                ttl_seconds=args.ttl_seconds,
            )
        elif args.command == "approve":
            result = service_update.approve(
                target_path=args.target.resolve(),
                review_path=args.review.resolve(),
                output=args.output.resolve(),
            )
        else:
            result = apply(
                source_root=args.source_root.resolve(),
                work_dir=args.work_dir.resolve(),
                approval_path=args.approval.resolve(),
                timeout_seconds=args.timeout_seconds,
            )
    except (OSError, subprocess.SubprocessError, common.ManualOperatorUpdateError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
