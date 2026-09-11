#!/usr/bin/env python3
"""Independently observe one direct-built Genesis runner image and its build witnesses."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

CaptureCommand = Callable[..., str]


def verify_runner_image_effect(
    *,
    terraform_output: Mapping[str, object],
    review: Mapping[str, object],
    subscription_id: str,
    capture: CaptureCommand,
    cwd: Path,
    timeout: int,
) -> str:
    """Require exact image provenance, successful extensions, and deallocated build VMs."""

    image_id = _resource_id(terraform_output, "id")
    builder_vm_id = _resource_id(terraform_output, "builder_vm_id")
    verifier_vm_id = _resource_id(terraform_output, "verifier_vm_id")
    builder_extension = _resource_id(terraform_output, "builder_extension")
    verifier_extension = _resource_id(terraform_output, "verifier_extension")
    firewall_public_ip = _resource_id(terraform_output, "firewall_public_ip")
    management_public_ip = _resource_id(terraform_output, "management_public_ip")
    expected_prefix = f"/subscriptions/{subscription_id}/".casefold()
    if any(
        not value.casefold().startswith(expected_prefix)
        for value in (
            image_id,
            builder_vm_id,
            verifier_vm_id,
            builder_extension,
            verifier_extension,
            firewall_public_ip,
            management_public_ip,
        )
    ):
        raise ValueError("runner image observation target does not match the reviewed subscription")
    observed = _json_capture(
        capture,
        [
            "az",
            "resource",
            "show",
            "--ids",
            image_id,
            "--query",
            "{id:id,type:type,location:location,hyperVGeneration:properties.hyperVGeneration,provisioningState:properties.provisioningState,sourceVm:properties.sourceVirtualMachine.id,osState:properties.storageProfile.osDisk.osState,osType:properties.storageProfile.osDisk.osType,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ],
        cwd=cwd,
        timeout=timeout,
        reason="runner image independent Azure readback failed",
    )
    tags = observed.get("tags") if isinstance(observed, dict) else None
    if (
        not isinstance(tags, dict)
        or str(observed.get("id", "")).casefold() != image_id.casefold()
        or str(observed.get("type", "")).casefold() != "microsoft.compute/images"
        or observed.get("location") != terraform_output.get("location")
        or observed.get("provisioningState") != "Succeeded"
        or observed.get("hyperVGeneration") != "V2"
        or observed.get("osState") != "Generalized"
        or observed.get("osType") != "Linux"
        or str(observed.get("sourceVm", "")).casefold() != builder_vm_id.casefold()
        or tags.get("fdai:source-commit") != review["source_commit"]
        or tags.get("fdai:run-digest") != review["run_digest"]
        or tags.get("fdai:toolchain-digest") != review["toolchain_digest"]
    ):
        raise ValueError("runner image independent readback does not match the reviewed plan")
    _verify_extension(builder_extension, capture=capture, cwd=cwd, timeout=timeout)
    _verify_extension(verifier_extension, capture=capture, cwd=cwd, timeout=timeout)
    _verify_verifier_image(
        verifier_vm_id, image_id=image_id, capture=capture, cwd=cwd, timeout=timeout
    )
    _verify_deallocated(builder_vm_id, capture=capture, cwd=cwd, timeout=timeout)
    _verify_deallocated(verifier_vm_id, capture=capture, cwd=cwd, timeout=timeout)
    _verify_public_ip_policy_effects(
        (firewall_public_ip, management_public_ip),
        expected_location=str(terraform_output.get("location", "")),
        capture=capture,
        cwd=cwd,
        timeout=timeout,
    )
    return image_id


def _verify_public_ip_policy_effects(
    resource_ids: tuple[str, str],
    *,
    expected_location: str,
    capture: CaptureCommand,
    cwd: Path,
    timeout: int,
) -> None:
    dispositions: list[dict[str, object]] = []
    for resource_id in resource_ids:
        value = _json_capture(
            capture,
            [
                "az",
                "network",
                "public-ip",
                "show",
                "--ids",
                resource_id,
                "--query",
                "{id:id,location:location,allocationMethod:publicIPAllocationMethod,sku:sku.name,ipTags:ipTags}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            cwd=cwd,
            timeout=timeout,
            reason="runner image public IP policy readback failed",
        )
        ip_tags = _public_ip_tags(value.get("ipTags"))
        if (
            str(value.get("id", "")).casefold() != resource_id.casefold()
            or value.get("location") != expected_location
            or value.get("allocationMethod") != "Static"
            or value.get("sku") != "Standard"
            or ip_tags not in ({}, {"FirstPartyUsage": "/Unprivileged"})
        ):
            raise ValueError("runner image public IP policy effect is invalid")
        dispositions.append(ip_tags)
    if dispositions[0] != dispositions[1]:
        raise ValueError("runner image public IP policy effects are inconsistent")


def _public_ip_tags(value: object) -> dict[str, object]:
    if value in (None, []):
        return {}
    if not isinstance(value, list):
        raise ValueError("runner image public IP policy effect is invalid")
    result: dict[str, object] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {"ipTagType", "tag"}:
            raise ValueError("runner image public IP policy effect is invalid")
        tag_type = item.get("ipTagType")
        tag = item.get("tag")
        if not isinstance(tag_type, str) or tag_type in result or not isinstance(tag, str):
            raise ValueError("runner image public IP policy effect is invalid")
        result[tag_type] = tag
    return result


def _verify_extension(
    resource_id: str, *, capture: CaptureCommand, cwd: Path, timeout: int
) -> None:
    value = _json_capture(
        capture,
        [
            "az",
            "vm",
            "extension",
            "show",
            "--ids",
            resource_id,
            "--expand",
            "instanceView",
            "--query",
            "{id:id,type:type,provisioningState:provisioningState,statuses:instanceView.statuses[].code}",
            "--output",
            "json",
            "--only-show-errors",
        ],
        cwd=cwd,
        timeout=timeout,
        reason="runner image extension readback failed",
    )
    if (
        str(value.get("id", "")).casefold() != resource_id.casefold()
        or str(value.get("type", "")).casefold() != "microsoft.compute/virtualmachines/extensions"
        or value.get("provisioningState") != "Succeeded"
        or "ProvisioningState/succeeded" not in value.get("statuses", [])
    ):
        raise ValueError("runner image extension did not complete successfully")


def _verify_deallocated(
    resource_id: str, *, capture: CaptureCommand, cwd: Path, timeout: int
) -> None:
    state = capture(
        [
            "az",
            "vm",
            "get-instance-view",
            "--ids",
            resource_id,
            "--query",
            "instanceView.statuses[?code=='PowerState/deallocated'] | length(@)",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        cwd=cwd,
        timeout=timeout,
        reason="runner image VM power-state readback failed",
    ).strip()
    if state != "1":
        raise ValueError("runner image build VM is not deallocated")


def _verify_verifier_image(
    resource_id: str,
    *,
    image_id: str,
    capture: CaptureCommand,
    cwd: Path,
    timeout: int,
) -> None:
    value = capture(
        [
            "az",
            "vm",
            "show",
            "--ids",
            resource_id,
            "--query",
            "storageProfile.imageReference.id",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        cwd=cwd,
        timeout=timeout,
        reason="runner image verifier source readback failed",
    ).strip()
    if value.casefold() != image_id.casefold():
        raise ValueError("runner image verifier did not boot the captured image")


def _resource_id(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.startswith("/subscriptions/"):
        raise ValueError("runner image Terraform output identity is invalid")
    return result


def _json_capture(
    capture: CaptureCommand,
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
) -> dict[str, object]:
    value = json.loads(capture(list(command), cwd=cwd, timeout=timeout, reason=reason))
    if not isinstance(value, dict):
        raise ValueError(reason)
    return value
