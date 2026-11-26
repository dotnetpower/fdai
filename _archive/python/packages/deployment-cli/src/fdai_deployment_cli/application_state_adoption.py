"""Stage a verified public-development Terraform state for private-host adoption."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_SUFFIX = re.compile(r"[a-z0-9]{6}")
_MAX_STATE_BYTES = 64 * 1024 * 1024
_MAX_MODEL_BYTES = 8 * 1024 * 1024
_RESOURCE_GROUP_ADDRESS = "module.resource_group.azurerm_resource_group.primary[0]"
_OWNERSHIP_ADDRESS = "module.resource_group.terraform_data.ownership"


@dataclass(frozen=True, slots=True)
class ApplicationStateAdoption:
    """Private staged state and value-free metadata for one verified adoption."""

    state: Path
    resolved_models: Path
    descriptor: Path
    resource_name_suffix: str
    managed_resource_count: int


def stage_application_state_adoption(
    *,
    source_state: Path,
    recovery_receipt: Path,
    resolved_models: Path,
    output_directory: Path,
    subscription_id: str,
    resource_group_name: str,
    environment: str,
    region_short: str,
) -> ApplicationStateAdoption:
    """Validate and split a recovered public state without changing its source bytes."""

    if _GUID.fullmatch(subscription_id) is None:
        raise ValueError("application state adoption subscription id is invalid")
    if environment != "dev" or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None:
        raise ValueError("application state adoption supports one valid public dev target")
    if resource_group_name != f"rg-fdai-dev-{region_short}":
        raise ValueError("application state adoption resource group is invalid")
    state_bytes = read_private_bytes(source_state, max_bytes=_MAX_STATE_BYTES)
    recovery_bytes = read_private_bytes(recovery_receipt, max_bytes=65_536)
    recovery = _object(json.loads(recovery_bytes))
    state_digest = hashlib.sha256(state_bytes).hexdigest()
    _validate_recovery(recovery, state_digest=state_digest)
    state = _object(json.loads(state_bytes))
    staged, suffix, count = _split_state(
        state,
        subscription_id=subscription_id,
        resource_group_name=resource_group_name,
        environment=environment,
        region_short=region_short,
        expected_tracked_count=recovery["tracked_resource_count"],
    )
    model_bytes = read_private_bytes(resolved_models, max_bytes=_MAX_MODEL_BYTES)
    model_digest = hashlib.sha256(model_bytes).hexdigest()
    resolved = _object(json.loads(model_bytes))
    capabilities = _resolved_capabilities(resolved)
    if output_directory.exists():
        return _load_staged_adoption(
            output_directory,
            source_state_sha256=state_digest,
            recovery_receipt_sha256=hashlib.sha256(recovery_bytes).hexdigest(),
            resolved_models_sha256=model_digest,
            expected_suffix=suffix,
            expected_count=count,
        )
    output_directory.mkdir(mode=0o700, parents=True)
    staged_state = output_directory / "application-state.json"
    staged_models = output_directory / "resolved-models.json"
    descriptor_path = output_directory / "adoption.json"
    staged_bytes = (json.dumps(staged, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = {
        "schema_version": "fdai.application-state-adoption.v1",
        "state": "staged",
        "source_state_sha256": state_digest,
        "staged_state_sha256": hashlib.sha256(staged_bytes).hexdigest(),
        "resolved_models_sha256": model_digest,
        "recovery_receipt_sha256": hashlib.sha256(recovery_bytes).hexdigest(),
        "source_commit": recovery["source_commit"],
        "verified_source_commit": recovery["verified_source_commit"],
        "resource_name_suffix": suffix,
        "managed_resource_count": count,
        "removed_addresses": [_OWNERSHIP_ADDRESS, _RESOURCE_GROUP_ADDRESS],
        "resolved_capabilities": capabilities,
        "original_state_retained": True,
        "remote_backend_authority_verified": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    try:
        write_private_bytes(staged_state, staged_bytes)
        write_private_bytes(staged_models, model_bytes)
        write_private_output(
            descriptor_path,
            json.dumps(descriptor, sort_keys=True, separators=(",", ":")) + "\n",
        )
    except BaseException:
        shutil.rmtree(output_directory)
        raise
    return ApplicationStateAdoption(
        state=staged_state,
        resolved_models=staged_models,
        descriptor=descriptor_path,
        resource_name_suffix=suffix,
        managed_resource_count=count,
    )


def _load_staged_adoption(
    output_directory: Path,
    *,
    source_state_sha256: str,
    recovery_receipt_sha256: str,
    resolved_models_sha256: str,
    expected_suffix: str,
    expected_count: int,
) -> ApplicationStateAdoption:
    state = output_directory / "application-state.json"
    models = output_directory / "resolved-models.json"
    descriptor_path = output_directory / "adoption.json"
    descriptor = _object(json.loads(read_private_bytes(descriptor_path, max_bytes=1_048_576)))
    staged_state_digest = hashlib.sha256(
        read_private_bytes(state, max_bytes=_MAX_STATE_BYTES)
    ).hexdigest()
    staged_model_digest = hashlib.sha256(
        read_private_bytes(models, max_bytes=_MAX_MODEL_BYTES)
    ).hexdigest()
    if (
        descriptor.get("schema_version") != "fdai.application-state-adoption.v1"
        or descriptor.get("state") != "staged"
        or descriptor.get("source_state_sha256") != source_state_sha256
        or descriptor.get("recovery_receipt_sha256") != recovery_receipt_sha256
        or descriptor.get("resolved_models_sha256") != resolved_models_sha256
        or descriptor.get("staged_state_sha256") != staged_state_digest
        or staged_model_digest != resolved_models_sha256
        or descriptor.get("resource_name_suffix") != expected_suffix
        or descriptor.get("managed_resource_count") != expected_count
        or descriptor.get("original_state_retained") is not True
        or descriptor.get("remote_backend_authority_verified") is not False
    ):
        raise ValueError("retained application state adoption differs")
    return ApplicationStateAdoption(
        state=state,
        resolved_models=models,
        descriptor=descriptor_path,
        resource_name_suffix=expected_suffix,
        managed_resource_count=expected_count,
    )


def _validate_recovery(recovery: dict[str, Any], *, state_digest: str) -> None:
    if (
        recovery.get("schema_version") != "fdai.contributor-recovery.v1"
        or recovery.get("state") != "failed-apply-observed"
        or recovery.get("operational_verification") != "observed"
        or recovery.get("state_sha256") != state_digest
        or _DIGEST.fullmatch(str(recovery.get("plan_sha256", ""))) is None
        or _SOURCE_COMMIT.fullmatch(str(recovery.get("source_commit", ""))) is None
        or _SOURCE_COMMIT.fullmatch(str(recovery.get("verified_source_commit", ""))) is None
        or type(recovery.get("tracked_resource_count")) is not int
        or recovery["tracked_resource_count"] <= 2
    ):
        raise ValueError("application state adoption recovery receipt is invalid")


def _split_state(
    state: dict[str, Any],
    *,
    subscription_id: str,
    resource_group_name: str,
    environment: str,
    region_short: str,
    expected_tracked_count: int,
) -> tuple[dict[str, Any], str, int]:
    if (
        state.get("version") != 4
        or type(state.get("serial")) is not int
        or state["serial"] < 0
        or not isinstance(state.get("lineage"), str)
        or not state["lineage"]
        or not isinstance(state.get("resources"), list)
    ):
        raise ValueError("application state adoption requires valid version-4 state")
    expected_group_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
    kept: list[object] = []
    removed: set[str] = set()
    registry_name = ""
    managed_count = 0
    tracked_count = 0
    for value in state["resources"]:
        resource = _object(value)
        address = _resource_address(resource)
        instances = resource.get("instances")
        if not isinstance(instances, list):
            raise ValueError(  # noqa: TRY004 - normalize untrusted state into a stable CLI error
                "application state adoption resource instances are invalid"
            )
        tracked_count += len(instances)
        if not instances:
            kept.append(value)
            continue
        if address == _RESOURCE_GROUP_ADDRESS:
            attributes = _single_attributes(resource, index=0)
            if str(attributes.get("id", "")).casefold() != expected_group_id.casefold():
                raise ValueError("application state adoption resource group identity differs")
            removed.add(address)
            continue
        if address == _OWNERSHIP_ADDRESS:
            attributes = _single_attributes(resource)
            if attributes.get("input") not in (
                "managed",
                {"value": "managed", "type": "string"},
            ):
                raise ValueError("application state adoption ownership marker is invalid")
            removed.add(address)
            continue
        if resource.get("mode") == "managed":
            managed_count += len(instances)
        if address == "module.container_registry.azurerm_container_registry.primary":
            registry_name = str(_single_attributes(resource).get("name", ""))
        kept.append(value)
    if removed != {_OWNERSHIP_ADDRESS, _RESOURCE_GROUP_ADDRESS}:
        raise ValueError("application state adoption resource-group owners are incomplete")
    if tracked_count != expected_tracked_count:
        raise ValueError("application state adoption tracked resource count differs")
    if managed_count <= 0:
        raise ValueError("application state adoption has no managed application resource")
    prefix = f"crfdai{environment}{region_short}"
    if not registry_name.startswith(prefix):
        raise ValueError("application state adoption registry name does not match the target")
    suffix = registry_name.removeprefix(prefix)
    if _SUFFIX.fullmatch(suffix) is None:
        raise ValueError("application state adoption resource suffix is invalid")
    staged = dict(state)
    staged["resources"] = kept
    staged["serial"] = state["serial"] + 1
    return staged, suffix, managed_count


def _resolved_capabilities(payload: dict[str, Any]) -> list[dict[str, object]]:
    values = payload.get("capabilities")
    if not isinstance(values, list) or not values:
        raise ValueError("application state adoption model capabilities are invalid")
    result: list[dict[str, object]] = []
    for value in values:
        item = _object(value)
        if item.get("status") == "hil-only":
            continue
        if item.get("status") != "resolved" or item.get("publisher") not in {
            "OpenAI",
            "Anthropic",
            "MistralAI",
        }:
            raise ValueError("application state adoption resolved capability is invalid")
        required_strings = ("name", "publisher", "family", "version", "sku")
        if any(
            not isinstance(item.get(key), str) or not item[key].strip() for key in required_strings
        ):
            raise ValueError("application state adoption resolved capability is incomplete")
        capacity_tpm = item.get("capacity_tpm", 0)
        capacity_value = item.get("capacity_value", 0)
        capacity_unit = item.get("capacity_unit", "tpm")
        if (
            isinstance(capacity_tpm, bool)
            or not isinstance(capacity_tpm, (int, float))
            or isinstance(capacity_value, bool)
            or not isinstance(capacity_value, (int, float))
        ):
            raise ValueError(  # noqa: TRY004 - normalize model JSON into a stable CLI error
                "application state adoption resolved capability capacity is invalid"
            )
        if (
            (capacity_unit == "tpm" and not (capacity_tpm >= 1000 and capacity_value == 0))
            or (capacity_unit == "ptu" and not (capacity_tpm == 0 and capacity_value >= 1))
            or capacity_unit not in {"tpm", "ptu"}
        ):
            raise ValueError("application state adoption resolved capability capacity is invalid")
        result.append(
            {
                key: item[key]
                for key in (
                    "name",
                    "publisher",
                    "family",
                    "version",
                    "sku",
                    "capacity_tpm",
                    "capacity_unit",
                    "capacity_value",
                )
                if key in item
            }
        )
    if not result:
        raise ValueError("application state adoption has no resolved model capability")
    return result


def _resource_address(resource: dict[str, Any]) -> str:
    mode = resource.get("mode")
    resource_type = resource.get("type")
    name = resource.get("name")
    if mode not in {"managed", "data"} or not all(
        isinstance(value, str) and value for value in (resource_type, name)
    ):
        raise ValueError("application state adoption resource is invalid")
    module = resource.get("module")
    prefix = f"{module}." if isinstance(module, str) and module else ""
    base = f"{prefix}{resource_type}.{name}"
    if base == "module.resource_group.azurerm_resource_group.primary":
        return base + "[0]"
    return base


def _single_attributes(resource: dict[str, Any], *, index: int | None = None) -> dict[str, Any]:
    instances = resource.get("instances")
    if not isinstance(instances, list) or len(instances) != 1:
        raise ValueError("application state adoption expected one resource instance")
    instance = _object(instances[0])
    if instance.get("index_key") != index:
        raise ValueError("application state adoption resource index is invalid")
    return _object(instance.get("attributes"))


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("application state adoption contains an invalid object")
    return dict(value)
