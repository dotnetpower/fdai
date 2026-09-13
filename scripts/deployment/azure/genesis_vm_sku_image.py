"""Seal a catalog-selected image pair with its fixed Foundation host in a v2 review."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes
from genesis_checks import CheckError
from genesis_runner_image_contract import RunnerImageInputs
from genesis_runner_image_sku_probe import read_vm_skus, read_vm_usage
from genesis_runner_image_skus import (
    EVIDENCE_INVALID,
    require_selection_projection,
    selection_sizes,
)
from genesis_vm_sku_catalog import read_vm_catalog
from genesis_vm_sku_choice import choose_deployment_vms, require_deployment_vms
from genesis_vm_sku_policy import parse_vm_policy
from genesis_vm_sku_preflight import POLICY_NAME, VmReadContext


def select_catalog_image_inputs(
    inputs: RunnerImageInputs,
    *,
    terraform_root: Path,
    destination: Path,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> RunnerImageInputs:
    """Select only in a fresh planning directory; preserve the prepared host and all claims."""
    policy = parse_vm_policy(read_private_bytes(terraform_root / POLICY_NAME, max_bytes=16_384))
    if not inputs.foundation_vm_size:
        raise CheckError(EVIDENCE_INVALID, 3)
    context: VmReadContext = {
        "subscription_id": str(inputs.terraform_values["subscription_id"]),
        "region": inputs.region,
        "azure_cli": azure_cli,
        "capture": capture,
        "cwd": cwd,
        "environment": environment,
    }
    rows = read_vm_catalog(**context)
    usages = read_vm_usage(**context)
    chosen = choose_deployment_vms(
        policy,
        region=inputs.region,
        rows=rows,
        usages=usages,
        foundation_size=inputs.foundation_vm_size,
    )
    selection: dict[str, object] = {
        "schema_version": "fdai.runner-image-sku-selection.v2",
        "build_vm_size": chosen.builder.size,
        "verify_vm_size": chosen.verifier.size,
        "foundation_vm_size": chosen.foundation.size,
        "image_disk_gib": policy.os_disk_gib,
        "policy_digest": policy.digest,
        "sku_evidence_digest": canonical_digest({"rows": rows}),
        "quota_evidence_digest": canonical_digest({"rows": usages}),
        "checked_at": datetime.now(
            timezone.utc  # noqa: UP017 - Python 3.10 entrypoint
        ).isoformat(),
        "capacity_reserved": False,
    }
    values = {
        **inputs.terraform_values,
        "build_vm_size": chosen.builder.size,
        "verify_vm_size": chosen.verifier.size,
    }
    if read_plan_input(destination) != inputs.terraform_values:
        raise CheckError("runner_image_selection_input_changed", 3)
    write_plan_input(destination.parent / "runner-image-sku-evidence.json", {"rows": rows})
    write_plan_input(destination.parent / "runner-image-quota-evidence.json", {"rows": usages})
    destination.unlink()
    write_plan_input(destination, values)
    return replace(inputs, terraform_values=values, sku_selection=selection)


def recheck_catalog_image_inputs(
    projection: bytes,
    *,
    selection: dict[str, object],
    terraform_root: Path,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> None:
    """Recheck the sealed triplet and projection without ever ranking new choices at apply."""
    builder, verifier = selection_sizes(selection)
    require_selection_projection(projection, region=region, selection=selection)
    policy = parse_vm_policy(read_private_bytes(terraform_root / POLICY_NAME, max_bytes=16_384))
    if (
        policy.digest != selection["policy_digest"]
        or selection["image_disk_gib"] != policy.os_disk_gib
    ):
        raise CheckError(EVIDENCE_INVALID, 3)
    host = str(selection["foundation_vm_size"])
    context: VmReadContext = {
        "subscription_id": subscription_id,
        "region": region,
        "azure_cli": azure_cli,
        "capture": capture,
        "cwd": cwd,
        "environment": environment,
    }
    rows = read_vm_skus(tuple(sorted({builder, verifier, host})), **context)
    usages = read_vm_usage(**context)
    require_deployment_vms(
        policy,
        region=region,
        rows=rows,
        usages=usages,
        builder=builder,
        verifier=verifier,
        foundation=host,
    )
