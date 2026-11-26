"""Read-only Azure observations for the pre-runner bootstrap boundary."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai_deployment_cli.bootstrap_plan import (
    FOUNDATION_PROVIDER_NAMESPACES,
    BootstrapObservation,
    BootstrapReconcileResult,
    Classification,
    build_intent,
    timestamp,
    validate_inputs,
)
from fdai_deployment_cli.contracts import ProvisionProfile
from fdai_deployment_cli.target import compute_target_binding

_NOT_FOUND_CODES = frozenset({"ResourceGroupNotFound", "ResourceNotFound"})


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Bounded result from one fixed Azure CLI read."""

    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...]], CommandResult]


def reconcile_bootstrap(
    profile: ProvisionProfile,
    *,
    source_commit: str,
    ops_resource_group: str,
    app_resource_group: str,
    state_storage_account: str,
    ttl_seconds: int = 3600,
    now: datetime | None = None,
    run: CommandRunner | None = None,
) -> BootstrapReconcileResult:
    """Read and seal the bounded state needed before a foundation approval."""

    validate_inputs(
        source_commit=source_commit,
        ops_resource_group=ops_resource_group,
        app_resource_group=app_resource_group,
        state_storage_account=state_storage_account,
        ttl_seconds=ttl_seconds,
    )
    command_runner = run or run_azure_cli
    subscription_id, target_binding = _active_target(command_runner)
    if target_binding != profile.target_binding:
        raise ValueError("active Azure target does not match the provision profile")

    observations = [
        *(
            _observe_provider(command_runner, namespace, subscription_id)
            for namespace in FOUNDATION_PROVIDER_NAMESPACES
        ),
        _observe_resource_group(
            command_runner,
            "ops-resource-group",
            ops_resource_group,
            profile.region,
            subscription_id,
        ),
        _observe_resource_group(
            command_runner,
            "application-resource-group",
            app_resource_group,
            profile.region,
            subscription_id,
        ),
        _observe_storage(
            command_runner,
            state_storage_account,
            ops_resource_group,
            profile.region,
            subscription_id,
        ),
    ]
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return BootstrapReconcileResult(
        intent=build_intent(
            profile=profile,
            source_commit=source_commit,
            ops_resource_group=ops_resource_group,
            app_resource_group=app_resource_group,
            state_storage_account=state_storage_account,
        ),
        observations=tuple(observations),
        created_at=timestamp(moment),
        expires_at=timestamp(moment + timedelta(seconds=ttl_seconds)),
    )


def run_azure_cli(arguments: tuple[str, ...]) -> CommandResult:
    """Execute one fixed Azure CLI read without exposing provider error text."""

    executable = shutil.which("az")
    if executable is None:
        raise OSError("Azure CLI is unavailable")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stdout="", stderr="")
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:65_536],
        stderr=completed.stderr[:65_536],
    )


def _active_target(run: CommandRunner) -> tuple[str, str]:
    result = run(
        (
            "account",
            "show",
            "--query",
            "{subscription:id,tenant:tenantId}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if result.returncode != 0:
        raise ValueError("azure_target_unavailable")
    payload = _json_object(result.stdout, "Azure target")
    subscription = payload.get("subscription")
    tenant = payload.get("tenant")
    if not isinstance(subscription, str) or not isinstance(tenant, str):
        raise ValueError("azure_target_invalid")
    return subscription, compute_target_binding(tenant_id=tenant, subscription_id=subscription)


def _observe_provider(
    run: CommandRunner,
    namespace: str,
    subscription_id: str,
) -> BootstrapObservation:
    result = run(
        (
            "provider",
            "show",
            "--namespace",
            namespace,
            "--subscription",
            subscription_id,
            "--query",
            "registrationState",
            "--output",
            "tsv",
            "--only-show-errors",
        )
    )
    entry_id = f"provider.{namespace.casefold()}"
    if result.returncode != 0:
        return BootstrapObservation(entry_id, Classification.INDETERMINATE, "provider_read_failed")
    state = result.stdout.strip()
    if state == "Registered":
        return BootstrapObservation(entry_id, Classification.COMPATIBLE, "provider_registered")
    if state in {"NotRegistered", "Unregistered"}:
        return BootstrapObservation(
            entry_id, Classification.MISSING, "provider_registration_required"
        )
    return BootstrapObservation(entry_id, Classification.INDETERMINATE, "provider_state_unresolved")


def _observe_resource_group(
    run: CommandRunner,
    entry_id: str,
    name: str,
    region: str,
    subscription_id: str,
) -> BootstrapObservation:
    result = run(
        (
            "group",
            "show",
            "--name",
            name,
            "--subscription",
            subscription_id,
            "--query",
            "{name:name,location:location}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if result.returncode != 0:
        if _error_code(result.stderr) == "ResourceGroupNotFound":
            return BootstrapObservation(entry_id, Classification.MISSING, "resource_group_missing")
        return BootstrapObservation(
            entry_id, Classification.INDETERMINATE, "resource_group_read_failed"
        )
    payload = _json_object(result.stdout, "resource group")
    if (
        payload.get("name") != name
        or str(payload.get("location", "")).casefold() != region.casefold()
    ):
        return BootstrapObservation(entry_id, Classification.CONFLICT, "resource_group_conflict")
    return BootstrapObservation(entry_id, Classification.COMPATIBLE, "resource_group_compatible")


def _observe_storage(
    run: CommandRunner,
    name: str,
    resource_group: str,
    region: str,
    subscription_id: str,
) -> BootstrapObservation:
    result = run(
        (
            "storage",
            "account",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "{name:name,location:location,kind:kind,sku:sku.name,"
            "minimum_tls_version:minimumTlsVersion,public_network_access:publicNetworkAccess,"
            "shared_key_access:allowSharedKeyAccess,blob_public_access:allowBlobPublicAccess,"
            "cross_tenant_replication:allowCrossTenantReplication}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if result.returncode == 0:
        posture = _classify_existing_storage(result.stdout, name=name, region=region)
        if posture.classification is not Classification.COMPATIBLE:
            return posture
        return _observe_storage_data_protection(
            run,
            name=name,
            resource_group=resource_group,
            subscription_id=subscription_id,
        )
    if _error_code(result.stderr) not in _NOT_FOUND_CODES:
        return BootstrapObservation(
            "state-storage", Classification.INDETERMINATE, "state_storage_read_failed"
        )
    return _observe_storage_name(run, name=name, subscription_id=subscription_id)


def _classify_existing_storage(value: str, *, name: str, region: str) -> BootstrapObservation:
    payload = _json_object(value, "state storage account")
    expected: dict[str, object] = {
        "name": name,
        "location": region.casefold(),
        "kind": "StorageV2",
        "sku": "Standard_LRS",
        "minimum_tls_version": "TLS1_2",
        "public_network_access": "Disabled",
        "shared_key_access": False,
        "blob_public_access": False,
        "cross_tenant_replication": False,
    }
    normalized = dict(payload)
    normalized["location"] = str(normalized.get("location", "")).casefold()
    if normalized != expected:
        return BootstrapObservation(
            "state-storage", Classification.CONFLICT, "state_storage_posture_conflict"
        )
    return BootstrapObservation(
        "state-storage", Classification.COMPATIBLE, "state_storage_compatible"
    )


def _observe_storage_data_protection(
    run: CommandRunner,
    *,
    name: str,
    resource_group: str,
    subscription_id: str,
) -> BootstrapObservation:
    result = run(
        (
            "storage",
            "account",
            "blob-service-properties",
            "show",
            "--account-name",
            name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "{versioning:isVersioningEnabled,blob_delete_retention:deleteRetentionPolicy.enabled,"
            "container_delete_retention:containerDeleteRetentionPolicy.enabled}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if result.returncode != 0:
        return BootstrapObservation(
            "state-storage",
            Classification.INDETERMINATE,
            "state_storage_data_protection_read_failed",
        )
    payload = _json_object(result.stdout, "state storage data protection")
    if payload != {
        "versioning": True,
        "blob_delete_retention": True,
        "container_delete_retention": True,
    }:
        return BootstrapObservation(
            "state-storage",
            Classification.MISSING,
            "state_storage_data_protection_required",
        )
    return BootstrapObservation(
        "state-storage",
        Classification.COMPATIBLE,
        "state_storage_compatible",
    )


def _observe_storage_name(
    run: CommandRunner,
    *,
    name: str,
    subscription_id: str,
) -> BootstrapObservation:
    result = run(
        (
            "storage",
            "account",
            "check-name",
            "--name",
            name,
            "--subscription",
            subscription_id,
            "--query",
            "{available:nameAvailable,reason:reason}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if result.returncode != 0:
        return BootstrapObservation(
            "state-storage", Classification.INDETERMINATE, "state_storage_name_check_failed"
        )
    available = _json_object(result.stdout, "state storage name").get("available")
    if available is True:
        return BootstrapObservation(
            "state-storage", Classification.MISSING, "state_storage_missing"
        )
    if available is False:
        return BootstrapObservation(
            "state-storage", Classification.CONFLICT, "state_storage_name_unavailable"
        )
    return BootstrapObservation(
        "state-storage", Classification.INDETERMINATE, "state_storage_name_unresolved"
    )


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} returned invalid JSON")
    return payload


def _error_code(value: str) -> str | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return str(error["code"])
    match = re.search(r"\b(ResourceGroupNotFound|ResourceNotFound)\b", value)
    return match.group(1) if match else None
