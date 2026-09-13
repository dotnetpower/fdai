"""Seal automatic image-VM choices before plan and recheck that exact pair before apply."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes
from genesis_checks import CheckError
from genesis_runner_image_contract import RunnerImageInputs
from genesis_runner_image_sku_choice import (
    choose_image_vm_pair,
    parse_sku_policy,
    require_selected_pair,
)
from genesis_runner_image_sku_probe import read_vm_skus, read_vm_usage, verify_image_vm_skus
from genesis_runner_image_skus import (
    EVIDENCE_INVALID,
    require_selection_projection,
    selection_sizes,
)
from genesis_vm_sku_image import recheck_catalog_image_inputs, select_catalog_image_inputs
from genesis_vm_sku_preflight import POLICY_NAME

SKU_EVIDENCE_NAME = "runner-image-sku-evidence.json"
QUOTA_EVIDENCE_NAME = "runner-image-quota-evidence.json"


class _ReadContext(TypedDict):
    subscription_id: str
    region: str
    azure_cli: Path
    capture: Callable[..., str]
    cwd: Path
    environment: Mapping[str, str]


def select_image_vm_inputs(
    inputs: RunnerImageInputs,
    *,
    terraform_root: Path,
    destination: Path,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> RunnerImageInputs:
    """Choose once in a new planning directory and bind sizes without changing image identity.

    The caller owns source/target verification and creates the private directory. This function
    never touches an existing plan, apply claim, Foundation selection, or provider resource.
    """

    if (terraform_root / POLICY_NAME).exists() or (terraform_root / POLICY_NAME).is_symlink():
        return select_catalog_image_inputs(
            inputs,
            terraform_root=terraform_root,
            destination=destination,
            azure_cli=azure_cli,
            capture=capture,
            cwd=cwd,
            environment=environment,
        )
    policy = parse_sku_policy(
        read_private_bytes(terraform_root / "sku-policy.json", max_bytes=16_384)
    )
    context: _ReadContext = {
        "subscription_id": str(inputs.terraform_values["subscription_id"]),
        "region": inputs.region,
        "azure_cli": azure_cli,
        "capture": capture,
        "cwd": cwd,
        "environment": environment,
    }
    rows = read_vm_skus(policy.candidates, **context)
    usages = read_vm_usage(**context)
    builder, verifier = choose_image_vm_pair(policy, region=inputs.region, rows=rows, usages=usages)
    selected: dict[str, object] = {
        "schema_version": "fdai.runner-image-sku-selection.v1",
        "build_vm_size": builder,
        "verify_vm_size": verifier,
        "policy_digest": policy.digest,
        "sku_evidence_digest": canonical_digest({"rows": rows}),
        "quota_evidence_digest": canonical_digest({"rows": usages}),
        "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 script
        "capacity_reserved": False,
    }
    values = {**inputs.terraform_values, "build_vm_size": builder, "verify_vm_size": verifier}
    if read_plan_input(destination) != inputs.terraform_values:
        raise CheckError("runner_image_selection_input_changed", 3)
    # Exclusive private outputs preserve replay inputs without making them apply-time authority.
    write_plan_input(destination.parent / SKU_EVIDENCE_NAME, {"rows": rows})
    write_plan_input(destination.parent / QUOTA_EVIDENCE_NAME, {"rows": usages})
    destination.unlink()
    write_plan_input(destination, values)
    return replace(inputs, terraform_values=values, sku_selection=selected)


def recheck_image_vm_inputs(
    projection: bytes,
    *,
    selection: object,
    terraform_root: Path,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> None:
    """Preserve legacy review checks; new reviews recheck their pair without running selection."""

    context: _ReadContext = {
        "subscription_id": subscription_id,
        "region": region,
        "azure_cli": azure_cli,
        "capture": capture,
        "cwd": cwd,
        "environment": environment,
    }
    if selection is None:
        verify_image_vm_skus(projection, **context)
        return
    if (
        isinstance(selection, dict)
        and selection.get("schema_version") == "fdai.runner-image-sku-selection.v2"
    ):
        recheck_catalog_image_inputs(
            projection,
            selection=selection,
            terraform_root=terraform_root,
            **context,
        )
        return
    builder, verifier = selection_sizes(selection)
    require_selection_projection(projection, region=region, selection=selection)
    policy = parse_sku_policy(
        read_private_bytes(terraform_root / "sku-policy.json", max_bytes=16_384)
    )
    if not isinstance(selection, dict) or policy.digest != selection["policy_digest"]:
        raise CheckError(EVIDENCE_INVALID, 3)
    rows = read_vm_skus(tuple(sorted({builder, verifier})), **context)
    usages = read_vm_usage(**context)
    require_selected_pair(
        policy,
        region=region,
        rows=rows,
        usages=usages,
        builder=builder,
        verifier=verifier,
    )
