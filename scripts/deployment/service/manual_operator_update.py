#!/usr/bin/env python3
"""Plan and apply one exact existing-host Operator Container Apps update."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from manual_operator_update_contract import (
    _GUID,
    ManualOperatorUpdateError,
    _approval,
    _canonical_digest,
    _executor_digest,
    _file_digest,
    _image_attestation,
    _json_command,
    _login_identity,
    _object,
    _platform_binding,
    _read_private_object,
    _resource_id,
    _review,
    _run,
    _target,
    _target_binding,
    _terraform_init,
    _terraform_outputs,
    _text,
    _validate_image,
    _verified_source,
    _write_private,
)
from recover_operator_tfvars import recover_operator_tfvars

_TARGET_ADDRESS = "module.operator_service.module.container_app.azurerm_container_app.service"


def prepare(
    *,
    source_root: Path,
    target_path: Path,
    image_ref: str,
    image_source_commit: str,
    attestation_path: Path,
    work_dir: Path,
    ttl_seconds: int = 1200,
) -> dict[str, Any]:
    """Prepare a guarded saved plan under the exact deployment identity."""

    if not 60 <= ttl_seconds <= 1200:
        raise ManualOperatorUpdateError("manual Operator plan TTL must be 60-1200 seconds")
    source_commit = _verified_source(source_root)
    target = _target(target_path)
    attestation = _image_attestation(attestation_path, image_ref, image_source_commit)
    if work_dir.exists() or work_dir.is_symlink():
        raise ManualOperatorUpdateError("manual Operator work directory already exists")
    work_dir.mkdir(mode=0o700)
    _login_identity(source_root, target)
    platform_root = source_root / "infra"
    service_root = source_root / "infra/services/operator-service"
    _terraform_init(platform_root, target, "fdai-dev.tfstate")
    _terraform_init(service_root, target, "services/operator-service/dev.tfstate")
    platform_outputs = _terraform_outputs(platform_root)
    service_outputs = _terraform_outputs(service_root)
    service = _object(service_outputs.get("service"), "Operator service output")
    resource_id = _resource_id(service.get("id"), "Operator resource")
    app = _json_command(
        (
            "az",
            "containerapp",
            "show",
            "--ids",
            resource_id,
            "--only-show-errors",
            "--output",
            "json",
        ),
        timeout=60,
        label="Operator ARM readback",
    )
    platform = _platform_binding(platform_outputs)
    tfvars = recover_operator_tfvars(app, platform)
    tfvars_path = work_dir / "operator.tfvars.json"
    _write_private(tfvars_path, tfvars)
    previous_revision = _text(
        _object(app.get("properties"), "Operator properties").get("latestReadyRevisionName"),
        "Operator rollback revision",
    )
    previous_image = _current_image(app)
    if previous_image == image_ref:
        raise ManualOperatorUpdateError("Operator already uses the requested image")

    plan_path = work_dir / "operator.tfplan"
    _run(
        (
            "terraform",
            f"-chdir={service_root}",
            "plan",
            "-input=false",
            "-lock-timeout=5m",
            f"-target={_TARGET_ADDRESS}",
            f"-var-file={tfvars_path}",
            f"-var=image={image_ref}",
            f"-out={plan_path}",
        ),
        timeout=3600,
        label="Operator Terraform plan",
    )
    os.chmod(plan_path, 0o600)
    plan_json_path = work_dir / "operator-plan.json"
    plan_json = _json_command(
        ("terraform", f"-chdir={service_root}", "show", "-json", str(plan_path)),
        timeout=300,
        label="Operator Terraform plan projection",
    )
    _write_private(plan_json_path, plan_json)
    _guard(
        source_root,
        plan_json_path,
        image_ref,
        expected_cost_secret_id=str(platform["cost_pseudonym_key_secret_id"]),
    )
    planned_target = _planned_target(plan_json, image_ref, target["subscription_id"])
    if planned_target["service_resource_id"].casefold() != resource_id.casefold():
        raise ManualOperatorUpdateError("planned Operator target differs from current state")
    plan_digest = _file_digest(plan_path)
    plan_json_digest = _file_digest(plan_json_path)
    created_at = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 host
    review: dict[str, Any] = {
        "schema_version": "fdai.manual-operator-update-review.v1",
        "source_commit": source_commit,
        "image_source_commit": image_source_commit,
        "image_ref": image_ref,
        "image_attestation_digest": attestation["attestation_digest"],
        "target_binding": _target_binding(target),
        "target": planned_target,
        "plan_digest": plan_digest,
        "plan_json_digest": plan_json_digest,
        "previous_revision": previous_revision,
        "previous_image": previous_image,
        "action": "terraform_apply_saved_operator_plan",
        "stop_condition": "plan_or_target_drift_or_unhealthy_revision",
        "rollback_action": "copy_verified_previous_revision",
        "blast_radius": "one_existing_operator_container_app",
        "idempotency_key": _canonical_digest(
            {
                "target_binding": _target_binding(target),
                "service_resource_id": resource_id.casefold(),
                "image_ref": image_ref,
            }
        ),
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "mutation_performed": False,
    }
    review["review_digest"] = _canonical_digest(review)
    _write_private(work_dir / "review.json", review)
    _write_private(work_dir / "target.json", target)
    return review


def attest_image(
    *, image_ref: str, source_commit: str, repository: str, output: Path
) -> dict[str, Any]:
    """Verify public OCI provenance and retain a bounded content-only receipt."""

    _validate_image(image_ref, source_commit, repository)
    receipt: dict[str, Any] = {
        "schema_version": "fdai.manual-operator-image-attestation.v1",
        "repository": repository,
        "image_ref": image_ref,
        "source_commit": source_commit,
        "predicate_type": "https://slsa.dev/provenance/v1",
        "signer_workflow": f"{repository}/.github/workflows/container-supply-chain.yml",
        "verified_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
        "mutation_performed": False,
    }
    receipt["attestation_digest"] = _canonical_digest(receipt)
    _write_private(output, receipt)
    return receipt


def approve(*, target_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    """Bind one current Azure human to the exact prepared review."""

    target = _target(target_path)
    review = _review(review_path)
    if review["target_binding"] != _target_binding(target):
        raise ManualOperatorUpdateError("approval target differs from the prepared review")
    account = _json_command(
        (
            "az",
            "account",
            "show",
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        timeout=30,
        label="Azure human approval identity",
    )
    if (
        account.get("subscription_id") != target["subscription_id"]
        or account.get("tenant_id") != target["tenant_id"]
        or str(account.get("user_type", "")).casefold() != "user"
    ):
        raise ManualOperatorUpdateError("manual Operator approval requires the active Azure human")
    signed_in_user = _json_command(
        (
            "az",
            "ad",
            "signed-in-user",
            "show",
            "--query",
            "{object_id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        timeout=30,
        label="Azure human object identity",
    )
    object_id = signed_in_user.get("object_id")
    if not isinstance(object_id, str) or _GUID.fullmatch(object_id) is None:
        raise ManualOperatorUpdateError("manual Operator human object identity is invalid")
    approval: dict[str, Any] = {
        "schema_version": "fdai.manual-operator-update-approval.v1",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "target_binding": review["target_binding"],
        "actor_digest": hashlib.sha256(
            f"{review['target_binding']}:{object_id.casefold()}".encode()
        ).hexdigest(),
        "approved_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
        "expires_at": review["expires_at"],
    }
    approval["approval_digest"] = _canonical_digest(approval)
    _write_private(output, approval)
    return approval


def apply(
    *, source_root: Path, work_dir: Path, approval_path: Path, timeout_seconds: int = 1800
) -> dict[str, Any]:
    """Apply a saved plan once, verify effect, or restore the reviewed revision."""

    review = _review(work_dir / "review.json")
    target = _target(work_dir / "target.json")
    approval = _approval(approval_path, review)
    if _verified_source(source_root) != review["source_commit"]:
        raise ManualOperatorUpdateError("manual Operator source changed after planning")
    _login_identity(source_root, target)
    if approval["actor_digest"] == _executor_digest(target):
        raise ManualOperatorUpdateError("manual Operator approver and executor must differ")
    plan_path = work_dir / "operator.tfplan"
    plan_json_path = work_dir / "operator-plan.json"
    if _file_digest(plan_path) != review["plan_digest"]:
        raise ManualOperatorUpdateError("manual Operator saved plan changed after approval")
    if _file_digest(plan_json_path) != review["plan_json_digest"]:
        raise ManualOperatorUpdateError("manual Operator plan projection changed after approval")
    tfvars = _read_private_object(work_dir / "operator.tfvars.json", "Operator inputs")
    _guard(
        source_root,
        plan_json_path,
        str(review["image_ref"]),
        expected_cost_secret_id=_text(
            tfvars.get("cost_pseudonym_key_secret_id"), "Cost pseudonym key binding"
        ),
    )
    service_root = source_root / "infra/services/operator-service"
    _terraform_init(service_root, target, "services/operator-service/dev.tfstate")

    lock_descriptor = os.open(
        work_dir / "target.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ManualOperatorUpdateError(
                "manual Operator target is locked by another operation"
            ) from exc
        receipt_path = work_dir / "receipt.json"
        if receipt_path.is_file():
            return _receipt(receipt_path, review)
        if (work_dir / "claim.json").exists():
            raise ManualOperatorUpdateError(
                "manual Operator claim already exists; verify the effect before recovery"
            )
        before = _read_app(str(_object(review["target"], "review target")["service_resource_id"]))
        if _current_image(before) != review["previous_image"]:
            raise ManualOperatorUpdateError("Operator rollback baseline changed after planning")
        if _latest_ready_revision(before) != review["previous_revision"]:
            raise ManualOperatorUpdateError("Operator rollback revision changed after planning")
        claim: dict[str, Any] = {
            "schema_version": "fdai.manual-operator-update-claim.v1",
            "review_digest": review["review_digest"],
            "approval_digest": approval["approval_digest"],
            "plan_digest": review["plan_digest"],
            "idempotency_key": review["idempotency_key"],
            "executor_digest": _executor_digest(target),
            "claimed_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
            "mutation_performed": False,
        }
        claim["claim_digest"] = _canonical_digest(claim)
        _write_private(work_dir / "claim.json", claim)
        try:
            _run(
                (
                    "terraform",
                    f"-chdir={service_root}",
                    "apply",
                    "-input=false",
                    "-lock-timeout=5m",
                    str(plan_path),
                ),
                timeout=timeout_seconds,
                label="Operator exact Terraform apply",
            )
            observed = _wait_for_image(
                review,
                expected_image=str(review["image_ref"]),
                previous_revision=str(review["previous_revision"]),
                timeout_seconds=1200,
            )
        except (OSError, subprocess.SubprocessError, ManualOperatorUpdateError) as apply_error:
            _restore_revision(review, timeout_seconds=1200)
            failure = {
                "schema_version": "fdai.manual-operator-update-failure.v1",
                "state": "rolled_back",
                "review_digest": review["review_digest"],
                "plan_digest": review["plan_digest"],
                "previous_revision": review["previous_revision"],
                "rollback_verified": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
            }
            failure["receipt_digest"] = _canonical_digest(failure)
            _write_private(work_dir / "failure.json", failure)
            raise ManualOperatorUpdateError(
                "manual Operator update failed and the previous revision was restored"
            ) from apply_error
        receipt: dict[str, Any] = {
            "schema_version": "fdai.manual-operator-update-receipt.v1",
            "state": "applied",
            "review_digest": review["review_digest"],
            "plan_digest": review["plan_digest"],
            "target_binding": review["target_binding"],
            "image_ref": review["image_ref"],
            "observed_revision_digest": hashlib.sha256(
                _latest_ready_revision(observed).encode()
            ).hexdigest(),
            "health_verified": True,
            "effect_readback_verified": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
            "mutation_performed": True,
        }
        receipt["receipt_digest"] = _canonical_digest(receipt)
        _write_private(receipt_path, receipt)
        return receipt
    finally:
        os.close(lock_descriptor)


def _receipt(path: Path, review: dict[str, Any]) -> dict[str, Any]:
    value = _read_private_object(path, "manual Operator receipt")
    digest = value.get("receipt_digest")
    if (
        value.get("schema_version") != "fdai.manual-operator-update-receipt.v1"
        or value.get("review_digest") != review["review_digest"]
        or value.get("mutation_performed") is not True
        or value.get("effect_readback_verified") is not True
        or digest
        != _canonical_digest({key: item for key, item in value.items() if key != "receipt_digest"})
    ):
        raise ManualOperatorUpdateError("manual Operator receipt is invalid")
    return value


def _guard(
    source_root: Path,
    plan_json: Path,
    image_ref: str,
    *,
    expected_cost_secret_id: str,
) -> None:
    payload = _read_private_object(plan_json, "Operator plan projection")
    normalized = _normalize_cost_pseudonym_adoption(
        payload, expected_secret_id=expected_cost_secret_id
    )
    with tempfile.TemporaryDirectory(prefix="fdai-operator-guard-") as directory:
        normalized_path = Path(directory) / "plan.json"
        _write_private(normalized_path, normalized)
        _run(
            (
                sys.executable,
                str(source_root / "scripts/deployment/service/guard_plan.py"),
                "--plan-json",
                str(normalized_path),
                "--service",
                "operator-service",
                "--environment",
                "dev",
                "--image-ref",
                image_ref,
                "--operator-channel-edge-transition",
                "none",
                "--document-channel-intake-transition",
                "none",
            ),
            timeout=120,
            label="Operator plan guard",
            discard_output=True,
        )


def _normalize_cost_pseudonym_adoption(
    payload: dict[str, Any], *, expected_secret_id: str
) -> dict[str, Any]:
    """Verify one exact platform-owned secret adoption and remove it for shared guarding."""

    changes = payload.get("resource_changes")
    if not isinstance(changes, list):
        raise ManualOperatorUpdateError("Operator plan resource changes are invalid")
    matches = [
        entry
        for entry in changes
        if isinstance(entry, dict) and entry.get("address") == _TARGET_ADDRESS
    ]
    if len(matches) != 1:
        raise ManualOperatorUpdateError("Operator plan must contain exactly one target")
    change = _object(matches[0].get("change"), "Operator plan change")
    before = _object(change.get("before"), "current Operator resource")
    after = _object(change.get("after"), "planned Operator resource")
    before_secrets = _named_objects(before.get("secret"), "current Operator secrets")
    after_secrets = _named_objects(after.get("secret"), "planned Operator secrets")
    if (
        "cost-pseudonym-key" in before_secrets
        or set(after_secrets) - set(before_secrets) != {"cost-pseudonym-key"}
        or set(before_secrets) - set(after_secrets)
        or any(after_secrets[name] != secret for name, secret in before_secrets.items())
    ):
        raise ManualOperatorUpdateError("Operator Cost pseudonym secret adoption is invalid")
    secret = after_secrets["cost-pseudonym-key"]
    identity = secret.get("identity")
    identities = _planned_identity_ids(after)
    if (
        secret.get("key_vault_secret_id") != expected_secret_id
        or not isinstance(identity, str)
        or identity.casefold() not in identities
    ):
        raise ManualOperatorUpdateError("Operator Cost pseudonym secret binding is invalid")
    before_environment = _planned_environment(before)
    after_environment = _planned_environment(after)
    if (
        "FDAI_COST_PSEUDONYM_KEY" in before_environment
        or set(after_environment) - set(before_environment) != {"FDAI_COST_PSEUDONYM_KEY"}
        or set(before_environment) - set(after_environment)
        or any(after_environment[name] != item for name, item in before_environment.items())
        or after_environment["FDAI_COST_PSEUDONYM_KEY"]
        != {"name": "FDAI_COST_PSEUDONYM_KEY", "secret_name": "cost-pseudonym-key"}
    ):
        raise ManualOperatorUpdateError("Operator Cost pseudonym environment adoption is invalid")
    normalized = copy.deepcopy(payload)
    normalized_change = next(
        entry["change"]
        for entry in normalized["resource_changes"]
        if entry.get("address") == _TARGET_ADDRESS
    )
    normalized_after = normalized_change["after"]
    normalized_after["secret"] = [
        item for item in normalized_after["secret"] if item.get("name") != "cost-pseudonym-key"
    ]
    container = normalized_after["template"][0]["container"][0]
    container["env"] = [
        item for item in container["env"] if item.get("name") != "FDAI_COST_PSEUDONYM_KEY"
    ]
    return normalized


def _named_objects(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ManualOperatorUpdateError(f"{label} must be an array of objects")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        name = item.get("name")
        if not isinstance(name, str) or not name or name in result:
            raise ManualOperatorUpdateError(f"{label} contains invalid names")
        result[name] = item
    return result


def _planned_environment(resource: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        environment = resource["template"][0]["container"][0]["env"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ManualOperatorUpdateError("Operator planned environment is invalid") from exc
    return _named_objects(environment, "Operator planned environment")


def _planned_identity_ids(resource: dict[str, Any]) -> frozenset[str]:
    try:
        identities = resource["identity"][0]["identity_ids"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ManualOperatorUpdateError("Operator planned identities are invalid") from exc
    if not isinstance(identities, list) or not all(isinstance(item, str) for item in identities):
        raise ManualOperatorUpdateError("Operator planned identities are invalid")
    return frozenset(item.casefold() for item in identities)


def _planned_target(plan: dict[str, Any], image_ref: str, subscription_id: str) -> dict[str, str]:
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise ManualOperatorUpdateError("Operator plan resource changes are invalid")
    matches = [
        entry
        for entry in changes
        if isinstance(entry, dict) and entry.get("address") == _TARGET_ADDRESS
    ]
    if len(matches) != 1:
        raise ManualOperatorUpdateError("Operator plan must contain exactly one target")
    change = _object(matches[0].get("change"), "Operator plan change")
    after = _object(change.get("after"), "Operator planned resource")
    name = _text(after.get("name"), "planned Operator name")
    resource_group = _text(after.get("resource_group_name"), "planned Operator resource group")
    containers = after.get("template")
    try:
        planned_image = containers[0]["container"][0]["image"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ManualOperatorUpdateError("planned Operator container is invalid") from exc
    if planned_image != image_ref:
        raise ManualOperatorUpdateError("planned Operator image differs from the candidate")
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
        f"Microsoft.App/containerApps/{name}"
    )
    return {
        "service_resource_id": resource_id,
        "resource_group": resource_group,
        "service_name": name,
    }


def _read_app(resource_id: str) -> dict[str, Any]:
    return _json_command(
        (
            "az",
            "containerapp",
            "show",
            "--ids",
            resource_id,
            "--only-show-errors",
            "--output",
            "json",
        ),
        timeout=60,
        label="Operator effect readback",
    )


def _wait_for_image(
    review: dict[str, Any], *, expected_image: str, previous_revision: str, timeout_seconds: int
) -> dict[str, Any]:
    resource_id = str(_object(review["target"], "review target")["service_resource_id"])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app = _read_app(resource_id)
        revision = _latest_ready_revision(app)
        if revision != previous_revision and _current_image(app) == expected_image:
            properties = _object(app.get("properties"), "Operator properties")
            if properties.get("provisioningState") == "Succeeded":
                return app
        time.sleep(5)
    raise ManualOperatorUpdateError("Operator candidate did not reach healthy readback")


def _restore_revision(review: dict[str, Any], *, timeout_seconds: int) -> None:
    target = _object(review["target"], "review target")
    revision_suffix = f"rollback-{str(review['review_digest'])[:12]}"
    _run(
        (
            "az",
            "containerapp",
            "revision",
            "copy",
            "--resource-group",
            str(target["resource_group"]),
            "--name",
            str(target["service_name"]),
            "--from-revision",
            str(review["previous_revision"]),
            "--revision-suffix",
            revision_suffix,
            "--only-show-errors",
            "--output",
            "none",
        ),
        timeout=60,
        label="Operator rollback activation",
        discard_output=True,
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app = _read_app(str(target["service_resource_id"]))
        recovery_revision = _latest_ready_revision(app)
        if recovery_revision != review["previous_revision"]:
            revision = _json_command(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "show",
                    "--resource-group",
                    str(target["resource_group"]),
                    "--name",
                    str(target["service_name"]),
                    "--revision",
                    recovery_revision,
                    "--only-show-errors",
                    "--output",
                    "json",
                ),
                timeout=60,
                label="Operator rollback revision readback",
            )
            properties = _object(
                revision.get("properties"), "Operator rollback revision properties"
            )
            try:
                rollback_image = properties["template"]["containers"][0]["image"]
            except (IndexError, KeyError, TypeError) as exc:
                raise ManualOperatorUpdateError(
                    "Operator rollback revision image is invalid"
                ) from exc
            if (
                rollback_image == review["previous_image"]
                and properties.get("provisioningState") == "Provisioned"
                and properties.get("healthState") == "Healthy"
                and properties.get("active") is True
            ):
                return
        time.sleep(5)
    raise ManualOperatorUpdateError("Operator rollback could not be verified")


def _current_image(app: dict[str, Any]) -> str:
    try:
        value = app["properties"]["template"]["containers"][0]["image"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ManualOperatorUpdateError("Operator image readback is invalid") from exc
    return _text(value, "Operator image readback")


def _latest_ready_revision(app: dict[str, Any]) -> str:
    return _text(
        _object(app.get("properties"), "Operator properties").get("latestReadyRevisionName"),
        "Operator ready revision",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    attestation = subcommands.add_parser("attest")
    attestation.add_argument("--image-ref", required=True)
    attestation.add_argument("--source-commit", required=True)
    attestation.add_argument("--repository", default="dotnetpower/fdai")
    attestation.add_argument("--output", type=Path, required=True)
    plan = subcommands.add_parser("plan")
    plan.add_argument("--source-root", type=Path, required=True)
    plan.add_argument("--target", type=Path, required=True)
    plan.add_argument("--image-ref", required=True)
    plan.add_argument("--image-source-commit", required=True)
    plan.add_argument("--attestation", type=Path, required=True)
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--ttl-seconds", type=int, default=1200)
    approval = subcommands.add_parser("approve")
    approval.add_argument("--target", type=Path, required=True)
    approval.add_argument("--review", type=Path, required=True)
    approval.add_argument("--output", type=Path, required=True)
    apply_command = subcommands.add_parser("apply")
    apply_command.add_argument("--source-root", type=Path, required=True)
    apply_command.add_argument("--work-dir", type=Path, required=True)
    apply_command.add_argument("--approval", type=Path, required=True)
    apply_command.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        if args.command == "attest":
            result = attest_image(
                image_ref=args.image_ref,
                source_commit=args.source_commit,
                repository=args.repository,
                output=args.output.resolve(),
            )
        elif args.command == "plan":
            result = prepare(
                source_root=args.source_root.resolve(),
                target_path=args.target.resolve(),
                image_ref=args.image_ref,
                image_source_commit=args.image_source_commit,
                attestation_path=args.attestation.resolve(),
                work_dir=args.work_dir.resolve(),
                ttl_seconds=args.ttl_seconds,
            )
        elif args.command == "approve":
            result = approve(
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
    except (OSError, subprocess.SubprocessError, ManualOperatorUpdateError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
