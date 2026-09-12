#!/usr/bin/env python3
"""Validate and persist private exact-plan contracts for the Genesis runner image."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile
from genesis_runner_image_skus import require_selection_projection

PLAN_NAME = "runner-image.tfplan"
PLAN_JSON_NAME = "runner-image-plan.json"
REVIEW_NAME = "runner-image-review.json"
CLAIM_NAME = "runner-image-apply-claim.json"
RECEIPT_NAME = "runner-image-apply-receipt.json"
_MAX_PLAN_BYTES = 64 * 1024 * 1024
_MONTHLY_FIXED_COST_UPPER_BOUND_USD = 500
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE_OBJECT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_TOOLCHAIN_FIELDS = {
    "schema_version",
    "azure_cli_package_version",
    "azure_cli_version",
    "github_runner_sha256",
    "github_runner_version",
    "microsoft_package_key_fingerprint",
    "opa_sha256",
    "opa_version",
    "oras_binary_sha256",
    "oras_sha256",
    "oras_version",
    "terraform_binary_sha256",
    "terraform_sha256",
    "terraform_version",
}
_LEGACY_TOOLCHAIN_FIELDS = _TOOLCHAIN_FIELDS - {
    "oras_binary_sha256",
    "oras_sha256",
    "oras_version",
}
_ORAS_DEFAULTS = {
    "oras_binary_sha256": "90d7256c6209ffb8e2c6a2d3e14388cb41f9d0583a99116f2649f56df9854f53",
    "oras_sha256": "b4efc97a91f471f323f193ea4b4d63d8ff443ca3aab514151a30751330852827",
    "oras_version": "1.2.3",
}
_EXPECTED_CREATE_ADDRESSES = frozenset(
    {
        "azapi_resource_action.builder_deallocate",
        "azapi_resource_action.builder_generalize",
        "azapi_resource_action.verifier_deallocate",
        "azapi_resource.builder_deprovision",
        "azurerm_image.runner",
        "azurerm_linux_virtual_machine.builder",
        "azurerm_linux_virtual_machine.verifier",
        "azurerm_firewall.builder",
        "azurerm_firewall_policy.builder",
        "azurerm_firewall_policy_rule_collection_group.builder",
        "azurerm_network_interface.builder",
        "azurerm_network_interface.verifier",
        "azurerm_network_interface_security_group_association.builder",
        "azurerm_network_interface_security_group_association.verifier",
        "azurerm_network_security_group.builder",
        "azurerm_public_ip.firewall",
        "azurerm_public_ip.firewall_management",
        "azurerm_resource_group.image",
        "azurerm_resource_group.staging",
        "azurerm_route.builder_default",
        "azurerm_route_table.builder",
        "azurerm_subnet.builder",
        "azurerm_subnet.firewall",
        "azurerm_subnet.firewall_management",
        "azurerm_subnet_network_security_group_association.builder",
        "azurerm_subnet_route_table_association.builder",
        "azurerm_virtual_machine_extension.builder",
        "azurerm_virtual_machine_extension.verifier",
        "azurerm_virtual_network.builder",
        "terraform_data.await_builder_poweroff",
    }
)
_EXPECTED_READ_ADDRESSES = frozenset({"data.azapi_resource.runner_image"})
_EXPECTED_RESOURCE_TYPES = {
    **{
        address: "azapi_resource_action"
        for address in _EXPECTED_CREATE_ADDRESSES
        if address.startswith("azapi_resource_action.")
    },
    "azapi_resource.builder_deprovision": "azapi_resource",
    "azurerm_image.runner": "azurerm_image",
    "azurerm_linux_virtual_machine.builder": "azurerm_linux_virtual_machine",
    "azurerm_linux_virtual_machine.verifier": "azurerm_linux_virtual_machine",
    "azurerm_firewall.builder": "azurerm_firewall",
    "azurerm_firewall_policy.builder": "azurerm_firewall_policy",
    "azurerm_firewall_policy_rule_collection_group.builder": (
        "azurerm_firewall_policy_rule_collection_group"
    ),
    "azurerm_network_interface.builder": "azurerm_network_interface",
    "azurerm_network_interface.verifier": "azurerm_network_interface",
    "azurerm_network_interface_security_group_association.builder": (
        "azurerm_network_interface_security_group_association"
    ),
    "azurerm_network_interface_security_group_association.verifier": (
        "azurerm_network_interface_security_group_association"
    ),
    "azurerm_network_security_group.builder": "azurerm_network_security_group",
    "azurerm_public_ip.firewall": "azurerm_public_ip",
    "azurerm_public_ip.firewall_management": "azurerm_public_ip",
    "azurerm_resource_group.image": "azurerm_resource_group",
    "azurerm_resource_group.staging": "azurerm_resource_group",
    "azurerm_route.builder_default": "azurerm_route",
    "azurerm_route_table.builder": "azurerm_route_table",
    "azurerm_subnet.builder": "azurerm_subnet",
    "azurerm_subnet.firewall": "azurerm_subnet",
    "azurerm_subnet.firewall_management": "azurerm_subnet",
    "azurerm_subnet_network_security_group_association.builder": (
        "azurerm_subnet_network_security_group_association"
    ),
    "azurerm_subnet_route_table_association.builder": ("azurerm_subnet_route_table_association"),
    "azurerm_virtual_machine_extension.builder": "azurerm_virtual_machine_extension",
    "azurerm_virtual_machine_extension.verifier": "azurerm_virtual_machine_extension",
    "azurerm_virtual_network.builder": "azurerm_virtual_network",
    "terraform_data.await_builder_poweroff": "terraform_data",
    "data.azapi_resource.runner_image": "azapi_resource",
}


@dataclass(frozen=True, slots=True)
class RunnerImageInputs:
    """Normalized private Terraform values and their non-authoritative bindings."""

    terraform_values: dict[str, object]
    target_binding: str
    source_commit: str
    run_digest: str
    toolchain_digest: str
    monthly_cost_ceiling: int
    environment: str
    region: str
    profile_digest: str
    sku_selection: dict[str, object] | None = None


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
            preserve_runner_image_networks=True,
        )
        foundation = read_plan_input(normalized)
    source_commit = str(foundation["source_commit"])
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("runner image source commit is invalid")
    if os.environ.get("FDAI_SIGNED_SOURCE_EVIDENCE") is not None:
        toolchain_raw = (repository_root / "infra/genesis-runner-image/toolchain.json").read_bytes()
    else:
        toolchain_blob = subprocess.run(
            [
                "/usr/bin/git",
                "show",
                f"{source_commit}:infra/genesis-runner-image/toolchain.json",
            ],
            cwd=repository_root,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if toolchain_blob.returncode != 0:
            raise ValueError("runner image toolchain object is unavailable")
        toolchain_raw = toolchain_blob.stdout
    toolchain = load_json_object(toolchain_raw, label="runner image toolchain", max_bytes=65_536)
    _validate_toolchain(toolchain)
    if profile.monthly_cost_ceiling < _MONTHLY_FIXED_COST_UPPER_BOUND_USD:
        raise ValueError(
            "runner image retained build graph exceeds the approved monthly cost ceiling"
        )
    variables: dict[str, object] = {
        "subscription_id": foundation["subscription_id"],
        "tenant_id": foundation["tenant_id"],
        "workload": foundation["workload"],
        "env": profile.environment,
        "region": profile.region,
        "region_short": foundation["region_short"],
        "source_commit": foundation["source_commit"],
        "run_digest": foundation["run_digest"],
        "execution_transport": foundation.get("execution_transport", "github-actions"),
        "runner_ssh_public_key": foundation["runner_ssh_public_key"],
        "build_address_space": foundation["build_address_space"],
        "build_subnet_prefix": foundation["build_subnet_prefix"],
        "firewall_subnet_prefix": foundation["firewall_subnet_prefix"],
        "firewall_management_subnet_prefix": foundation["firewall_management_subnet_prefix"],
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    write_plan_input(destination, variables)
    manifest = {
        "schema_version": "fdai.genesis-runner-image.v1",
        "source_commit": variables["source_commit"],
        "source_image_version": variables.get("source_image_version"),
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    if variables["execution_transport"] == "manual":
        manifest["execution_transport"] = "manual"
    return RunnerImageInputs(
        terraform_values=variables,
        target_binding=profile.target_binding,
        source_commit=source_commit,
        run_digest=str(foundation["run_digest"]),
        toolchain_digest=canonical_digest(manifest),
        monthly_cost_ceiling=profile.monthly_cost_ceiling,
        environment=profile.environment,
        region=profile.region,
        profile_digest=canonical_digest(profile.to_mapping()),
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
                "oras_binary_sha256",
                "oras_sha256",
                "oras_version",
                "terraform_binary_sha256",
                "terraform_sha256",
                "terraform_version",
            }
        },
    }
    if values["execution_transport"] == "manual":
        manifest["execution_transport"] = "manual"
    return replace(
        inputs,
        terraform_values=values,
        toolchain_digest=canonical_digest(manifest),
    )


def snapshot_terraform_root(source: Path, destination: Path, *, source_commit: str) -> str:
    """Copy a link-free Terraform root and return its exact content digest."""
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("runner image source commit is invalid")
    if os.environ.get("FDAI_SIGNED_SOURCE_EVIDENCE") is not None:
        if source.is_symlink() or not source.is_dir() or destination.exists():
            raise ValueError("signed runner image Terraform root is invalid")
        destination.mkdir(mode=0o700)
        files = sorted(path for path in source.rglob("*") if path.is_file())
        if not files:
            raise ValueError("signed runner image Terraform root has no files")
        for entry in sorted(source.rglob("*")):
            details = entry.lstat()
            if stat.S_ISLNK(details.st_mode) or not (
                stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode)
            ):
                raise ValueError("signed runner image Terraform root is unsafe")
            target = destination / entry.relative_to(source)
            if stat.S_ISDIR(details.st_mode):
                target.mkdir(mode=0o700, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(entry, target)
            target.chmod(0o700 if details.st_mode & stat.S_IXUSR else 0o600)
        return hash_tree(destination)
    repository_root = source.parents[1]
    relative_root = source.relative_to(repository_root)
    completed = subprocess.run(
        [
            "/usr/bin/git",
            "ls-tree",
            "-r",
            "-z",
            source_commit,
            "--",
            relative_root.as_posix(),
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("runner image tracked source inventory is unavailable")
    tracked_files: list[tuple[Path, str]] = []
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.decode("ascii").split()
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("runner image tracked source inventory is invalid")
        mode, kind, object_id = fields
        if (
            mode not in {"100644", "100755"}
            or kind != "blob"
            or _SOURCE_OBJECT.fullmatch(object_id) is None
        ):
            raise ValueError("runner image Terraform root contains an unsafe Git object")
        try:
            relative = Path(raw_path.decode("utf-8")).relative_to(relative_root)
        except (UnicodeDecodeError, ValueError):
            raise ValueError("runner image tracked source path is invalid") from None
        tracked_files.append((relative, object_id))
    if not tracked_files:
        raise ValueError("runner image Terraform root has no tracked files")
    destination.mkdir(mode=0o700)
    for relative, object_id in tracked_files:
        if relative.name.startswith("terraform.tfstate") or relative.name.endswith(".auto.tfvars"):
            raise ValueError("runner image Terraform root contains an unsafe tracked artifact")
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        blob = subprocess.run(
            ["/usr/bin/git", "cat-file", "blob", object_id],
            cwd=repository_root,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if blob.returncode != 0:
            raise ValueError("runner image tracked source object is unavailable")
        target.write_bytes(blob.stdout)
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
    *,
    directory: Path,
    inputs: RunnerImageInputs,
    root_digest: str,
    terraform_digest: str,
    provider_digest: str,
) -> dict[str, object]:
    """Validate the private plan projection and write one expiring no-authority review."""

    plan = read_private_bytes(directory / PLAN_NAME, max_bytes=_MAX_PLAN_BYTES)
    projection_bytes = read_private_bytes(directory / PLAN_JSON_NAME, max_bytes=16 * 1024 * 1024)
    projection = load_json_object(
        projection_bytes, label="runner image plan", max_bytes=16 * 1024 * 1024
    )
    create_count = _validate_projection(projection, inputs.terraform_values)
    retained_resource_count = create_count - sum(
        address.startswith(("azapi_resource_action.", "terraform_data."))
        for address in _EXPECTED_CREATE_ADDRESSES
    )
    lifecycle_actions = [
        "builder-customize",
        "builder-deprovision",
        "builder-deallocate",
        "builder-generalize",
        "image-capture",
        "verifier-boot",
        "verifier-validate",
        "verifier-deallocate",
    ]
    retained_types = Counter(
        str(entry["type"])
        for entry in projection["resource_changes"]
        if entry["change"]["actions"] == ["create"]
        and not str(entry["address"]).startswith(("azapi_resource_action.", "terraform_data."))
    )
    effect_summary = {
        "egress_class": "fqdn-allowlisted-firewall-basic",
        "public_ip_count": retained_types["azurerm_public_ip"],
        "policy_managed_fields": [
            "azurerm_public_ip.firewall.ip_tags",
            "azurerm_public_ip.firewall_management.ip_tags",
        ],
        "retained_type_counts": dict(sorted(retained_types.items())),
        "monthly_fixed_cost_upper_bound_usd": _MONTHLY_FIXED_COST_UPPER_BOUND_USD,
        "approved_monthly_cost_ceiling_usd": inputs.monthly_cost_ceiling,
    }
    if inputs.sku_selection is not None:
        require_selection_projection(
            projection_bytes, region=inputs.region, selection=inputs.sku_selection
        )
        effect_summary["vm_skus"] = inputs.sku_selection
    now = datetime.now(timezone.utc).replace(  # noqa: UP017 - Python 3.10 entrypoint
        microsecond=0
    )
    review: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-plan.v1",
        "state": "review",
        "target_binding": inputs.target_binding,
        "source_commit": inputs.source_commit,
        "run_digest": inputs.run_digest,
        "environment": inputs.environment,
        "region": inputs.region,
        "profile_digest": inputs.profile_digest,
        "toolchain_digest": inputs.toolchain_digest,
        "variables_digest": canonical_digest(inputs.terraform_values),
        "terraform_root_digest": root_digest,
        "terraform_digest": terraform_digest,
        "provider_digest": provider_digest,
        "plan_digest": hashlib.sha256(plan).hexdigest(),
        "plan_json_digest": hashlib.sha256(projection_bytes).hexdigest(),
        "create_count": create_count,
        "retained_resource_count": retained_resource_count,
        "lifecycle_actions": lifecycle_actions,
        "effect_summary": effect_summary,
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
        or not isinstance(review.get("provider_digest"), str)
        or _DIGEST.fullmatch(str(review["provider_digest"])) is None
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


def executor_identity_digest(review: dict[str, object]) -> str:
    """Derive the deterministic software executor identity from sealed artifacts."""

    fields = {
        "component": "fdai.genesis-runner-image-executor.v1",
        "source_commit": review.get("source_commit"),
        "terraform_digest": review.get("terraform_digest"),
        "provider_digest": review.get("provider_digest"),
        "plan_digest": review.get("plan_digest"),
    }
    if (
        not isinstance(fields["source_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", str(fields["source_commit"])) is None
        or any(
            not isinstance(fields[name], str) or _DIGEST.fullmatch(str(fields[name])) is None
            for name in ("terraform_digest", "provider_digest", "plan_digest")
        )
    ):
        raise ValueError("runner image executor identity inputs are invalid")
    return canonical_digest(fields)


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
        set(receipt)
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
            "toolchain_digest",
            "claim_digest",
            "approver_actor_digest",
            "credential_actor_digest",
            "executor_identity_digest",
            "runner_image_id",
            "state_ref",
            "effect_verified",
            "public_ip_policy_effect_verified",
            "terraform_zero_change_verified",
            "runner_registered",
            "mutation_performed",
            "subscription_ready",
            "completed_at",
        }
        or receipt.get("schema_version") != "fdai.genesis-runner-image-apply-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("effect_verified") is not True
        or receipt.get("public_ip_policy_effect_verified") is not True
        or receipt.get("terraform_zero_change_verified") is not True
        or receipt.get("runner_registered") is not False
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
        or not isinstance(receipt_digest, str)
        or canonical_digest(receipt) != receipt_digest
    ):
        raise ValueError("runner image apply receipt is invalid")
    review = load_review(
        image_receipt.parent,
        expected_review_digest=str(receipt.get("review_digest", "")),
        require_unexpired=False,
    )
    claim = read_plan_input(image_receipt.with_name(CLAIM_NAME))
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
        or claim.get("review_digest") != receipt.get("review_digest")
        or claim.get("plan_digest") != receipt.get("plan_digest")
        or claim.get("target_binding") != receipt.get("target_binding")
        or claim.get("source_commit") != receipt.get("source_commit")
        or claim.get("run_digest") != receipt.get("run_digest")
        or claim.get("environment") != receipt.get("environment")
        or claim.get("region") != receipt.get("region")
        or claim.get("profile_digest") != receipt.get("profile_digest")
        or claim.get("approver_actor_digest") != receipt.get("approver_actor_digest")
        or claim.get("credential_actor_digest") != receipt.get("credential_actor_digest")
        or claim.get("executor_identity_digest") != receipt.get("executor_identity_digest")
        or claim.get("executor_identity_digest") != executor_identity_digest(review)
        or claim.get("credential_actor_digest") != claim.get("approver_actor_digest")
        or claim.get("executor_identity_digest") == claim.get("approver_actor_digest")
        or any(
            not isinstance(claim.get(name), str) or _DIGEST.fullmatch(str(claim[name])) is None
            for name in (
                "approver_actor_digest",
                "credential_actor_digest",
                "executor_identity_digest",
            )
        )
        or claim.get("idempotency_key")
        != canonical_digest(
            {
                "target_binding": receipt.get("target_binding"),
                "plan_digest": receipt.get("plan_digest"),
            }
        )
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
        or receipt.get("claim_digest") != canonical_digest(claim)
        or any(
            receipt.get(name) != review.get(name)
            for name in (
                "plan_digest",
                "target_binding",
                "source_commit",
                "run_digest",
                "environment",
                "region",
                "profile_digest",
                "toolchain_digest",
            )
        )
    ):
        raise ValueError("runner image apply claim is invalid")
    try:
        claimed_at = datetime.fromisoformat(str(claim["claimed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("runner image apply claim timestamp is invalid") from exc
    if claimed_at.tzinfo is None or claimed_at.utcoffset() != timedelta(0):
        raise ValueError("runner image apply claim timestamp is invalid")
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
        or receipt.get("environment") != profile.environment
        or receipt.get("region") != profile.region
        or receipt.get("profile_digest") != canonical_digest(profile.to_mapping())
        or values.get("target_binding") != target_binding
        or values.get("source_commit") != source_commit
        or values.get("run_digest") != receipt.get("run_digest")
        or not image_id.casefold().startswith(
            f"/subscriptions/{str(values.get('subscription_id', '')).casefold()}/"
        )
        or re.fullmatch(
            rf"/subscriptions/{_UUID}/resourceGroups/[A-Za-z0-9._()-]+/providers/"
            rf"Microsoft\.Compute/images/[A-Za-z0-9._()-]+",
            image_id,
            re.IGNORECASE,
        )
        is None
    ):
        raise ValueError("runner image receipt does not match the Foundation input")
    return {
        **values,
        "runner_source_image_id": image_id,
        "runner_image_toolchain_digest": toolchain_digest,
    }, receipt


def _validate_toolchain(value: dict[str, object]) -> None:
    if set(value) == _LEGACY_TOOLCHAIN_FIELDS:
        value.update(_ORAS_DEFAULTS)
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
    create_addresses: set[str] = set()
    read_addresses: set[str] = set()
    changes = plan.get("resource_changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("runner image plan contains no managed changes")
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("change"), dict):
            raise ValueError("runner image plan contains an invalid resource change")
        address = entry.get("address")
        if not isinstance(address, str):
            raise ValueError("runner image plan contains an invalid resource address")
        if entry.get("type") != _EXPECTED_RESOURCE_TYPES.get(address):
            raise ValueError("runner image plan contains an unexpected resource type")
        actions = entry["change"].get("actions")
        if actions == ["create"]:
            create_addresses.add(address)
        elif actions == ["read"]:
            read_addresses.add(address)
        elif actions != ["no-op"]:
            raise ValueError("runner image plan contains an update, replacement, or deletion")
    if create_addresses != _EXPECTED_CREATE_ADDRESSES or read_addresses != _EXPECTED_READ_ADDRESSES:
        raise ValueError("runner image plan does not match the exact direct-builder graph")
    by_address = {str(entry["address"]): entry for entry in changes}
    _require_after_value(
        by_address, "azapi_resource_action.builder_deallocate", "action", "deallocate"
    )
    _require_after_value(
        by_address, "azapi_resource_action.builder_generalize", "action", "generalize"
    )
    _require_after_value(
        by_address, "azapi_resource_action.verifier_deallocate", "action", "deallocate"
    )
    _require_after_value(by_address, "azurerm_image.runner", "hyper_v_generation", "V2")
    for address in (
        "azurerm_public_ip.firewall",
        "azurerm_public_ip.firewall_management",
    ):
        change = by_address[address]["change"]
        after = change.get("after") if isinstance(change, dict) else None
        ip_tags = after.get("ip_tags") if isinstance(after, dict) else None
        if not isinstance(after, dict) or (ip_tags is not None and ip_tags != []):
            raise ValueError("runner image plan attempts to author policy-managed IP tags")
    deprovision_change = by_address["azapi_resource.builder_deprovision"]["change"]
    deprovision_after = (
        deprovision_change.get("after") if isinstance(deprovision_change, dict) else None
    )
    deprovision_body = (
        deprovision_after.get("body") if isinstance(deprovision_after, dict) else None
    )
    deprovision_properties = (
        deprovision_body.get("properties") if isinstance(deprovision_body, dict) else None
    )
    if (
        not isinstance(deprovision_properties, dict)
        or deprovision_properties.get("treatFailureAsDeploymentFailure") is not True
    ):
        raise ValueError("runner image plan does not fail closed on deprovision error")
    deprovision_source = deprovision_properties.get("source")
    deprovision_script = (
        deprovision_source.get("script") if isinstance(deprovision_source, dict) else None
    )
    if (
        not isinstance(deprovision_script, str)
        or "systemd-run --unit=fdai-deprovision" not in deprovision_script
        or "/var/lib/fdai/image-deprovisioned" not in deprovision_script
        or "systemctl poweroff" not in deprovision_script
        or "systemctl enable" in deprovision_script
        or "/etc/systemd/system/fdai-deprovision.service" in deprovision_script
    ):
        raise ValueError("runner image plan contains an unsafe deprovision lifecycle")
    _require_after_value(by_address, "azurerm_firewall.builder", "sku_tier", "Basic")
    _require_after_value(by_address, "azurerm_firewall.builder", "threat_intel_mode", "Deny")
    _require_after_value(
        by_address, "azurerm_route.builder_default", "next_hop_type", "VirtualAppliance"
    )
    firewall_change = by_address["azurerm_firewall_policy_rule_collection_group.builder"]["change"]
    firewall_after = firewall_change.get("after") if isinstance(firewall_change, dict) else None
    if not isinstance(firewall_after, dict):
        raise ValueError("runner image plan contains an invalid egress allowlist")
    collections = firewall_after.get("application_rule_collection")
    if not isinstance(collections, list) or len(collections) != 1:
        raise ValueError("runner image plan contains an invalid egress allowlist")
    collection = collections[0]
    if collection.get("action") != "Allow" or collection.get("priority") != 100:
        raise ValueError("runner image plan contains an invalid egress allowlist")
    rules = collection.get("rule")
    if not isinstance(rules, list) or len(rules) != 2:
        raise ValueError("runner image plan contains an invalid egress allowlist")
    expected_protocols = {
        (("Https", 443),): 6,
        (("Http", 80),): 2,
    }
    actual_protocols: dict[tuple[tuple[str, int], ...], int] = {}
    for rule in rules:
        protocols = tuple(
            sorted(
                (str(item.get("type")), int(item.get("port"))) for item in rule.get("protocols", [])
            )
        )
        actual_protocols[protocols] = len(rule.get("destination_fqdns", []))
        if rule.get("source_addresses") != [variables["build_subnet_prefix"]]:
            raise ValueError("runner image plan contains an invalid egress allowlist")
    if actual_protocols != expected_protocols:
        raise ValueError("runner image plan contains an invalid egress allowlist")
    if firewall_after.get("network_rule_collection") not in (None, []):
        raise ValueError("runner image plan contains an unexpected network egress rule")
    if firewall_after.get("nat_rule_collection") not in (None, []):
        raise ValueError("runner image plan contains an unexpected NAT rule")
    destinations = {
        value
        for rule in rules or []
        for value in rule.get("destination_fqdns", [])
        if isinstance(value, str)
    }
    if destinations != {
        "*.githubusercontent.com",
        "azure.archive.ubuntu.com",
        "github.com",
        "packages.microsoft.com",
        "releases.hashicorp.com",
        "security.ubuntu.com",
    }:
        raise ValueError("runner image plan contains an invalid egress allowlist")
    for address in ("azurerm_network_interface.builder", "azurerm_network_interface.verifier"):
        after = by_address[address]["change"].get("after")
        configurations = after.get("ip_configuration") if isinstance(after, dict) else None
        if (
            not isinstance(configurations, list)
            or len(configurations) != 1
            or configurations[0].get("public_ip_address_id") is not None
        ):
            raise ValueError("runner image plan contains a public VM interface")
    return len(create_addresses)


def _require_after_value(
    changes: dict[str, dict[str, object]], address: str, key: str, expected: object
) -> None:
    change = changes[address].get("change")
    after = change.get("after") if isinstance(change, dict) else None
    if not isinstance(after, dict) or after.get(key) != expected:
        raise ValueError("runner image plan contains an invalid lifecycle effect")
