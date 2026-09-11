#!/usr/bin/env python3
"""Validate and persist private exact-plan contracts for the Genesis runner image."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile

PLAN_NAME = "runner-image.tfplan"
PLAN_JSON_NAME = "runner-image-plan.json"
REVIEW_NAME = "runner-image-review.json"
CLAIM_NAME = "runner-image-apply-claim.json"
RECEIPT_NAME = "runner-image-apply-receipt.json"
_MAX_PLAN_BYTES = 64 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TOOLCHAIN_FIELDS = {
    "schema_version",
    "azure_cli_package_version",
    "azure_cli_version",
    "github_runner_sha256",
    "github_runner_version",
    "microsoft_package_key_fingerprint",
    "opa_sha256",
    "opa_version",
    "terraform_binary_sha256",
    "terraform_sha256",
    "terraform_version",
}


@dataclass(frozen=True, slots=True)
class RunnerImageInputs:
    """Normalized private Terraform values and their non-authoritative bindings."""

    terraform_values: dict[str, object]
    target_binding: str
    source_commit: str
    run_digest: str
    toolchain_digest: str


def load_runner_image_inputs(
    *, foundation_variables: Path, profile_path: Path, repository_root: Path, destination: Path
) -> RunnerImageInputs:
    """Derive image inputs from the reviewed Foundation profile without copying its image claim."""

    profile = load_profile(profile_path)
    with TemporaryDirectory(prefix="fdai-runner-image-input-") as temporary:
        normalized = Path(temporary) / "foundation.json"
        snapshot_foundation_input(
            foundation_variables,
            normalized,
            expected_target_binding=profile.target_binding,
            expected_region=profile.region,
            expected_environment=profile.environment,
        )
        foundation = read_plan_input(normalized)
    toolchain_path = repository_root / "infra/genesis-runner-image/toolchain.json"
    toolchain = load_json_object(
        toolchain_path.read_bytes(), label="runner image toolchain", max_bytes=65_536
    )
    _validate_toolchain(toolchain)
    variables: dict[str, object] = {
        "subscription_id": foundation["subscription_id"],
        "tenant_id": foundation["tenant_id"],
        "workload": foundation["workload"],
        "env": profile.environment,
        "region": profile.region,
        "region_short": foundation["region_short"],
        "source_commit": foundation["source_commit"],
        "run_digest": foundation["run_digest"],
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    write_plan_input(destination, variables)
    manifest = {
        "schema_version": "fdai.genesis-runner-image.v1",
        "source_commit": variables["source_commit"],
        "source_image_version": variables.get("source_image_version"),
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    return RunnerImageInputs(
        terraform_values=variables,
        target_binding=profile.target_binding,
        source_commit=str(foundation["source_commit"]),
        run_digest=str(foundation["run_digest"]),
        toolchain_digest=canonical_digest(manifest),
    )


def add_source_image_version(
    inputs: RunnerImageInputs, *, version: str, destination: Path
) -> RunnerImageInputs:
    """Seal one exact Marketplace version into the generated Terraform input."""

    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) is None or version == "latest":
        raise ValueError("runner source image version is not exact")
    values = {**inputs.terraform_values, "source_image_version": version}
    destination.unlink(missing_ok=True)
    write_plan_input(destination, values)
    manifest = {
        "schema_version": "fdai.genesis-runner-image.v1",
        "source_commit": inputs.source_commit,
        "source_image_version": version,
        **{
            key: value
            for key, value in values.items()
            if key
            in {
                "azure_cli_package_version",
                "azure_cli_version",
                "github_runner_sha256",
                "github_runner_version",
                "microsoft_package_key_fingerprint",
                "opa_sha256",
                "opa_version",
                "terraform_binary_sha256",
                "terraform_sha256",
                "terraform_version",
            }
        },
    }
    return RunnerImageInputs(
        terraform_values=values,
        target_binding=inputs.target_binding,
        source_commit=inputs.source_commit,
        run_digest=inputs.run_digest,
        toolchain_digest=canonical_digest(manifest),
    )


def snapshot_terraform_root(source: Path, destination: Path) -> str:
    """Copy a link-free Terraform root and return its exact content digest."""

    def ignored(_: str, names: list[str]) -> set[str]:
        return {
            name for name in names if name == ".terraform" or name.startswith("terraform.tfstate")
        }

    shutil.copytree(source, destination, symlinks=False, ignore=ignored)
    for entry in destination.rglob("*"):
        details = entry.lstat()
        if stat.S_ISLNK(details.st_mode) or not (entry.is_dir() or entry.is_file()):
            raise ValueError("runner image Terraform root contains an unsafe entry")
        if entry.is_dir():
            entry.chmod(0o700)
        else:
            entry.chmod(0o600)
    return hash_tree(destination)


def hash_tree(root: Path) -> str:
    """Hash relative paths and bytes for one private regular-file tree."""

    checksum = hashlib.sha256()
    files = sorted(
        entry
        for entry in root.rglob("*")
        if entry.is_file() and not entry.name.startswith("terraform.tfstate")
    )
    if not files:
        raise ValueError("runner image Terraform root is empty")
    for entry in files:
        if entry.is_symlink():
            raise ValueError("runner image Terraform root contains a symbolic link")
        relative = entry.relative_to(root).as_posix().encode("utf-8")
        payload = entry.read_bytes()
        checksum.update(len(relative).to_bytes(4, "big"))
        checksum.update(relative)
        checksum.update(len(payload).to_bytes(8, "big"))
        checksum.update(payload)
    return checksum.hexdigest()


def create_review(
    *, directory: Path, inputs: RunnerImageInputs, root_digest: str, terraform_digest: str
) -> dict[str, object]:
    """Validate the private plan projection and write one expiring no-authority review."""

    plan = read_private_bytes(directory / PLAN_NAME, max_bytes=_MAX_PLAN_BYTES)
    projection_bytes = read_private_bytes(directory / PLAN_JSON_NAME, max_bytes=16 * 1024 * 1024)
    projection = load_json_object(
        projection_bytes, label="runner image plan", max_bytes=16 * 1024 * 1024
    )
    create_count = _validate_projection(projection, inputs.terraform_values)
    now = datetime.now(timezone.utc).replace(  # noqa: UP017 - Python 3.10 entrypoint
        microsecond=0
    )
    review: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-plan.v1",
        "state": "review",
        "target_binding": inputs.target_binding,
        "source_commit": inputs.source_commit,
        "run_digest": inputs.run_digest,
        "toolchain_digest": inputs.toolchain_digest,
        "variables_digest": canonical_digest(inputs.terraform_values),
        "terraform_root_digest": root_digest,
        "terraform_digest": terraform_digest,
        "plan_digest": hashlib.sha256(plan).hexdigest(),
        "plan_json_digest": hashlib.sha256(projection_bytes).hexdigest(),
        "create_count": create_count,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    review["review_digest"] = canonical_digest(review)
    write_private_output(
        directory / REVIEW_NAME, json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return review


def load_review(
    directory: Path,
    *,
    expected_review_digest: str,
    require_unexpired: bool = True,
) -> dict[str, object]:
    """Verify one exact private review and its current plan bytes."""

    if _DIGEST.fullmatch(expected_review_digest) is None:
        raise ValueError("expected runner image review digest is invalid")
    review = read_plan_input(directory / REVIEW_NAME)
    digest = review.pop("review_digest", None)
    if digest != expected_review_digest or canonical_digest(review) != expected_review_digest:
        raise ValueError("runner image review digest does not match")
    if (
        review.get("schema_version") != "fdai.genesis-runner-image-plan.v1"
        or review.get("state") != "review"
        or review.get("apply_authorized") is not False
        or review.get("mutation_performed") is not False
        or review.get("subscription_ready") is not False
    ):
        raise ValueError("runner image review authority is invalid")
    created = datetime.fromisoformat(str(review["created_at"]))
    expires = datetime.fromisoformat(str(review["expires_at"]))
    now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
    if (
        created.tzinfo is None
        or created.utcoffset() != timedelta(0)
        or expires.tzinfo is None
        or expires.utcoffset() != timedelta(0)
        or expires - created != timedelta(hours=1)
        or created > now
        or (require_unexpired and now >= expires)
    ):
        raise ValueError("runner image review is expired")
    plan = read_private_bytes(directory / PLAN_NAME, max_bytes=_MAX_PLAN_BYTES)
    if hashlib.sha256(plan).hexdigest() != review.get("plan_digest"):
        raise ValueError("runner image plan digest does not match")
    review["review_digest"] = digest
    return review


def create_private_directory(path: Path) -> None:
    """Create one new owner-only work directory without replacing an existing path."""

    os.mkdir(path, 0o700)
    path.chmod(0o700)


def materialize_foundation_image_input(
    *, source: Path, image_receipt: Path, profile_path: Path, destination: Path
) -> dict[str, object]:
    """Publish a new private Foundation input from one exact verified image receipt."""

    updated, receipt = _foundation_image_values(
        source=source,
        image_receipt=image_receipt,
        profile_path=profile_path,
    )
    source_commit = str(receipt["source_commit"])
    target_binding = str(receipt["target_binding"])
    toolchain_digest = str(receipt["toolchain_digest"])
    temporary = destination.parent / f".{destination.name}.candidate"
    normalized = destination.parent / f".{destination.name}.normalized"
    temporary.unlink(missing_ok=True)
    normalized.unlink(missing_ok=True)
    write_plan_input(temporary, updated)
    try:
        profile = load_profile(profile_path)
        snapshot_foundation_input(
            temporary,
            normalized,
            expected_target_binding=profile.target_binding,
            expected_region=profile.region,
            expected_environment=profile.environment,
        )
        normalized.unlink()
        os.link(temporary, destination, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)
    return {
        "schema_version": "fdai.genesis-foundation-image-input.v1",
        "state": "prepared",
        "source_commit": source_commit,
        "target_binding": target_binding,
        "toolchain_digest": toolchain_digest,
        "variables_digest": canonical_digest(updated),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def verify_foundation_image_input(
    *, source: Path, image_receipt: Path, profile_path: Path, destination: Path
) -> dict[str, object]:
    """Verify an existing effective Foundation input against its exact image receipt."""

    expected, receipt = _foundation_image_values(
        source=source,
        image_receipt=image_receipt,
        profile_path=profile_path,
    )
    if read_plan_input(destination) != expected:
        raise ValueError("Foundation image input changed after materialization")
    return {
        "schema_version": "fdai.genesis-foundation-image-input.v1",
        "state": "prepared",
        "source_commit": receipt["source_commit"],
        "target_binding": receipt["target_binding"],
        "toolchain_digest": receipt["toolchain_digest"],
        "variables_digest": canonical_digest(expected),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _foundation_image_values(
    *, source: Path, image_receipt: Path, profile_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    receipt = read_plan_input(image_receipt)
    receipt_digest = receipt.pop("receipt_digest", None)
    if (
        receipt.get("schema_version") != "fdai.genesis-runner-image-apply-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("effect_verified") is not True
        or receipt.get("runner_registered") is not False
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
        or not isinstance(receipt_digest, str)
        or canonical_digest(receipt) != receipt_digest
    ):
        raise ValueError("runner image apply receipt is invalid")
    image_id = receipt.get("runner_image_id")
    toolchain_digest = receipt.get("toolchain_digest")
    source_commit = receipt.get("source_commit")
    target_binding = receipt.get("target_binding")
    if (
        not isinstance(image_id, str)
        or not isinstance(toolchain_digest, str)
        or _DIGEST.fullmatch(toolchain_digest) is None
        or not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or not isinstance(target_binding, str)
        or _DIGEST.fullmatch(target_binding) is None
    ):
        raise ValueError("runner image apply receipt binding is invalid")
    profile = load_profile(profile_path)
    values = read_plan_input(source)
    if (
        profile.target_binding != target_binding
        or values.get("target_binding") != target_binding
        or values.get("source_commit") != source_commit
    ):
        raise ValueError("runner image receipt does not match the Foundation input")
    return {
        **values,
        "runner_source_image_id": image_id,
        "runner_image_toolchain_digest": toolchain_digest,
    }, receipt


def _validate_toolchain(value: dict[str, object]) -> None:
    if (
        set(value) != _TOOLCHAIN_FIELDS
        or value["schema_version"] != "fdai.genesis-runner-toolchain.v1"
    ):
        raise ValueError("runner image toolchain fields are invalid")
    for key, item in value.items():
        if not isinstance(item, str) or not item:
            raise ValueError("runner image toolchain values must be nonempty strings")
        if key.endswith("_sha256") and _DIGEST.fullmatch(item) is None:
            raise ValueError("runner image toolchain digest is invalid")


def _validate_projection(plan: dict[str, object], variables: dict[str, object]) -> int:
    if (
        plan.get("format_version") not in {"1.1", "1.2"}
        or plan.get("complete") is not True
        or plan.get("errored") is not False
        or plan.get("applyable") is not True
        or plan.get("deferred_changes")
    ):
        raise ValueError("runner image plan is incomplete or unsupported")
    actual = plan.get("variables")
    if not isinstance(actual, dict) or any(
        actual.get(key) != {"value": value} for key, value in variables.items()
    ):
        raise ValueError("runner image plan variables do not match the sealed input")
    create_count = 0
    changes = plan.get("resource_changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("runner image plan contains no managed changes")
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("change"), dict):
            raise ValueError("runner image plan contains an invalid resource change")
        actions = entry["change"].get("actions")
        if actions == ["create"]:
            create_count += 1
        elif actions not in (["read"], ["no-op"]):
            raise ValueError("runner image plan contains an update, replacement, or deletion")
    if create_count == 0:
        raise ValueError("runner image plan contains no create action")
    return create_count
