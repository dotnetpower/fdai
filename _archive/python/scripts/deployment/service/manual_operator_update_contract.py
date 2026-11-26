"""Shared exact-plan contracts for manual existing-host Operator updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_COMMIT = re.compile(r"[0-9a-f]{40}")
_GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
_IMAGE = re.compile(
    r"ghcr[.]io/[a-z0-9_.-]+/[a-z0-9_.-]+/"
    r"fdai-operator-service@sha256:[0-9a-f]{64}"
)
_TARGET_FIELDS = {
    "schema_version",
    "environment",
    "repository",
    "tenant_id",
    "subscription_id",
    "state_resource_group",
    "state_storage_account",
    "state_container",
    "deploy_identity_client_id",
    "deploy_identity_principal_id",
}


class ManualOperatorUpdateError(ValueError):
    """Raised when a manual Operator update crosses a reviewed boundary."""


def _target(path: Path) -> dict[str, Any]:
    value = _read_private_object(path, "manual Operator target")
    if (
        set(value) != _TARGET_FIELDS
        or value.get("schema_version") != "fdai.manual-operator-target.v1"
    ):
        raise ManualOperatorUpdateError("manual Operator target fields are invalid")
    if value.get("environment") != "dev" or value.get("repository") != "dotnetpower/fdai":
        raise ManualOperatorUpdateError(
            "manual Operator target must be the existing dev installation"
        )
    for key in (
        "tenant_id",
        "subscription_id",
        "deploy_identity_client_id",
        "deploy_identity_principal_id",
    ):
        if not isinstance(value.get(key), str) or _GUID.fullmatch(value[key]) is None:
            raise ManualOperatorUpdateError(f"manual Operator target {key} is invalid")
    for key in ("state_resource_group", "state_storage_account", "state_container"):
        _text(value.get(key), f"manual Operator target {key}")
    return value


def _review(path: Path) -> dict[str, Any]:
    value = _read_private_object(path, "manual Operator review")
    digest = value.get("review_digest")
    if value.get("schema_version") not in {
        "fdai.manual-operator-update-review.v1",
        "fdai.manual-operator-platform-review.v1",
    } or digest != _canonical_digest(
        {key: item for key, item in value.items() if key != "review_digest"}
    ):
        raise ManualOperatorUpdateError("manual Operator review digest is invalid")
    if _timestamp(value.get("expires_at"), "expiry") <= datetime.now(timezone.utc):  # noqa: UP017 - Python 3.10 host
        raise ManualOperatorUpdateError("manual Operator review is expired")
    return value


def _approval(path: Path, review: dict[str, Any]) -> dict[str, Any]:
    value = _read_private_object(path, "manual Operator approval")
    digest = value.get("approval_digest")
    if (
        value.get("schema_version") != "fdai.manual-operator-update-approval.v1"
        or value.get("review_digest") != review["review_digest"]
        or value.get("plan_digest") != review["plan_digest"]
        or value.get("target_binding") != review["target_binding"]
        or value.get("expires_at") != review["expires_at"]
        or digest
        != _canonical_digest({key: item for key, item in value.items() if key != "approval_digest"})
    ):
        raise ManualOperatorUpdateError("manual Operator approval is invalid")
    return value


def _verified_source(source_root: Path) -> str:
    if not source_root.is_absolute() or not source_root.is_dir() or source_root.is_symlink():
        raise ManualOperatorUpdateError("manual Operator source must be an absolute directory")
    head = _capture(("git", "-C", str(source_root), "rev-parse", "HEAD"), 30, "source").strip()
    protected = _capture(
        ("git", "-C", str(source_root), "rev-parse", "refs/remotes/origin/main"),
        30,
        "source",
    ).strip()
    status = _capture(
        ("git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=no"),
        30,
        "source",
    )
    if _COMMIT.fullmatch(head) is None or head != protected or status:
        raise ManualOperatorUpdateError(
            "manual Operator source must be clean protected origin/main"
        )
    return head


def _validate_image(image_ref: str, source_commit: str, repository: str) -> None:
    if _IMAGE.fullmatch(image_ref) is None or _COMMIT.fullmatch(source_commit) is None:
        raise ManualOperatorUpdateError("manual Operator image context is invalid")
    _run(
        (
            "gh",
            "attestation",
            "verify",
            f"oci://{image_ref}",
            "--bundle-from-oci",
            "--repo",
            repository,
            "--source-digest",
            source_commit,
            "--predicate-type",
            "https://slsa.dev/provenance/v1",
            "--signer-workflow",
            f"{repository}/.github/workflows/container-supply-chain.yml",
        ),
        timeout=90,
        label="Operator image attestation",
        discard_output=True,
    )


def _image_attestation(path: Path, image_ref: str, source_commit: str) -> dict[str, Any]:
    value = _read_private_object(path, "manual Operator image attestation")
    digest = value.get("attestation_digest")
    if (
        value.get("schema_version") != "fdai.manual-operator-image-attestation.v1"
        or value.get("repository") != "dotnetpower/fdai"
        or value.get("image_ref") != image_ref
        or value.get("source_commit") != source_commit
        or value.get("predicate_type") != "https://slsa.dev/provenance/v1"
        or value.get("signer_workflow")
        != "dotnetpower/fdai/.github/workflows/container-supply-chain.yml"
        or value.get("mutation_performed") is not False
        or digest
        != _canonical_digest(
            {key: item for key, item in value.items() if key != "attestation_digest"}
        )
    ):
        raise ManualOperatorUpdateError("manual Operator image attestation is invalid")
    verified_at = _timestamp(value.get("verified_at"), "image attestation timestamp")
    if datetime.now(timezone.utc) - verified_at > timedelta(hours=1):  # noqa: UP017 - Python 3.10 host
        raise ManualOperatorUpdateError("manual Operator image attestation is stale")
    return value


def _login_identity(source_root: Path, target: dict[str, Any]) -> None:
    if os.environ.get("GITHUB_ACTIONS", "").casefold() == "true":
        raise ManualOperatorUpdateError(
            "manual Operator deployment cannot run inside GitHub Actions"
        )
    _run(
        (
            "bash",
            str(source_root / "scripts/deployment/azure/login-deploy-identity.sh"),
            str(target["subscription_id"]),
            str(target["tenant_id"]),
            str(target["deploy_identity_client_id"]),
            str(target["deploy_identity_principal_id"]),
        ),
        timeout=120,
        label="deployment identity login",
        discard_output=True,
    )


def _terraform_init(root: Path, target: dict[str, Any], key: str) -> None:
    _run(
        (
            "terraform",
            f"-chdir={root}",
            "init",
            "-input=false",
            "-lockfile=readonly",
            "-reconfigure",
            f"-backend-config=resource_group_name={target['state_resource_group']}",
            f"-backend-config=storage_account_name={target['state_storage_account']}",
            f"-backend-config=container_name={target['state_container']}",
            f"-backend-config=key={key}",
            "-backend-config=use_azuread_auth=true",
        ),
        timeout=600,
        label="Terraform backend initialization",
        discard_output=True,
    )


def _terraform_outputs(root: Path) -> dict[str, Any]:
    raw = _json_command(
        ("terraform", f"-chdir={root}", "output", "-json"),
        timeout=120,
        label="Terraform outputs",
    )
    result: dict[str, Any] = {}
    for key, item in raw.items():
        output = _object(item, f"Terraform output {key}")
        result[key] = output.get("value")
    return result


def _platform_binding(outputs: dict[str, Any]) -> dict[str, Any]:
    """Map shared-root output names into the independent service input contract."""

    return {
        "resource_group_name": outputs.get("resource_group_name"),
        "container_app_environment_id": outputs.get("container_app_environment_id"),
        "acr_login_server": outputs.get("container_registry_login_server"),
        "kafka_bootstrap_servers": outputs.get("event_bus_kafka_bootstrap"),
        "cost_pseudonym_key_secret_id": outputs.get("cost_pseudonym_key_secret_id"),
    }


def _target_binding(target: dict[str, Any]) -> str:
    return _canonical_digest(
        {"tenant_id": target["tenant_id"], "subscription_id": target["subscription_id"]}
    )


def _executor_digest(target: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{_target_binding(target)}:{str(target['deploy_identity_principal_id']).casefold()}".encode()
    ).hexdigest()


def _timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ManualOperatorUpdateError(f"manual Operator {label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ManualOperatorUpdateError(f"manual Operator {label} is invalid")
    return parsed


def _canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_private_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ManualOperatorUpdateError(f"{label} must be an owner-only regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManualOperatorUpdateError(f"{label} is invalid JSON") from exc
    return _object(value, label)


def _write_private(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def _json_command(command: tuple[str, ...], *, timeout: int, label: str) -> dict[str, Any]:
    raw = _capture(command, timeout, label)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManualOperatorUpdateError(f"{label} returned invalid JSON") from exc
    return _object(value, label)


def _capture(command: tuple[str, ...], timeout: int, label: str) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ManualOperatorUpdateError(f"{label} failed")
    return completed.stdout


def _run(
    command: tuple[str, ...], *, timeout: int, label: str, discard_output: bool = False
) -> None:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL if discard_output else None,
        stderr=subprocess.DEVNULL if discard_output else None,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ManualOperatorUpdateError(f"{label} failed")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManualOperatorUpdateError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManualOperatorUpdateError(f"{label} must be a non-empty string")
    return value


def _resource_id(value: object, label: str) -> str:
    result = _text(value, label)
    if not result.casefold().startswith("/subscriptions/"):
        raise ManualOperatorUpdateError(f"{label} must be an Azure resource id")
    return result
