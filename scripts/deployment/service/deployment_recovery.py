#!/usr/bin/env python3
"""Verify exact service health and build bounded Container Apps rollback commands."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_ALLOWED_SIDECARS = {
    "document-processing-worker": frozenset({"clamav"}),
}
_PROBE_FIELD_MAP = {
    "failureThreshold": "failure_count_threshold",
    "initialDelaySeconds": "initial_delay",
    "periodSeconds": "interval_seconds",
    "successThreshold": "success_count_threshold",
    "terminationGracePeriodSeconds": "termination_grace_period_seconds",
    "timeoutSeconds": "timeout",
}


class DeploymentRecoveryError(ValueError):
    """Raised when health or rollback evidence does not match the sealed target."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeploymentRecoveryError(f"{path.name} must contain a JSON object")
    return value


def _required(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise DeploymentRecoveryError(f"{label} is missing")
    return value


def _container_contract(container: dict[str, Any], *, label: str) -> dict[str, Any]:
    image = container.get("image")
    if not isinstance(image, str) or _DIGEST_IMAGE.fullmatch(image) is None:
        raise DeploymentRecoveryError(f"{label} image must be pinned by sha256 digest")
    probes = container.get("probes")
    if not isinstance(probes, list) or not all(isinstance(probe, dict) for probe in probes):
        raise DeploymentRecoveryError(f"{label} probes are invalid")
    return {
        "image": image,
        "probes": sorted(copy.deepcopy(probes), key=lambda probe: str(probe.get("type", ""))),
    }


def _canonical_digest(payload: dict[str, Any]) -> str:
    canonical = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def _observed_sidecar_contract(
    container: dict[str, Any],
    *,
    name: str,
    allow_legacy_empty_probes: bool = False,
) -> dict[str, str]:
    contract = _container_contract(container, label=f"sidecar {name}")
    _validate_sidecar_probes(
        contract,
        name=name,
        allow_legacy_empty=allow_legacy_empty_probes,
    )
    configuration = {
        key: value for key, value in container.items() if key not in {"image", "probes"}
    }
    normalized_probes: dict[str, dict[str, Any]] = {}
    for probe in contract["probes"]:
        probe_type = str(probe.get("type", "")).lower()
        socket = probe.get("tcpSocket")
        if probe_type not in {"startup", "liveness", "readiness"} or not isinstance(socket, dict):
            raise DeploymentRecoveryError(f"sidecar {name} probe contract changed")
        unknown_fields = set(probe) - {"type", "tcpSocket", *_PROBE_FIELD_MAP}
        if unknown_fields:
            raise DeploymentRecoveryError(f"sidecar {name} probe contract changed")
        normalized = {"transport": "TCP", "port": socket["port"]}
        for observed_name, planned_name in _PROBE_FIELD_MAP.items():
            if observed_name in probe:
                normalized[planned_name] = probe[observed_name]
        normalized_probes[f"{probe_type}_probe"] = normalized
    return {
        "name": name,
        "image_ref": contract["image"],
        "config_digest": _canonical_digest(configuration),
        "probe_digest": _canonical_digest(normalized_probes),
    }


def _sealed_sidecars(target: dict[str, Any], *, service: str) -> dict[str, dict[str, str]]:
    expected_names = _ALLOWED_SIDECARS.get(service, frozenset())
    raw_sidecars = target.get("sidecar_containers")
    if not isinstance(raw_sidecars, list):
        raise DeploymentRecoveryError("sealed context has no sidecar container contract")
    sidecars: dict[str, dict[str, str]] = {}
    for item in raw_sidecars:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or name in sidecars:
            raise DeploymentRecoveryError("sealed sidecar container contract is invalid")
        values: dict[str, str] = {}
        for key in ("name", "image_ref", "config_digest", "probe_digest"):
            value = item.get(key)
            if not isinstance(value, str):
                raise DeploymentRecoveryError("sealed sidecar container contract is invalid")
            values[key] = value
        if _DIGEST_IMAGE.fullmatch(values["image_ref"]) is None or any(
            re.fullmatch(r"[0-9a-f]{64}", values[key]) is None
            for key in ("config_digest", "probe_digest")
        ):
            raise DeploymentRecoveryError("sealed sidecar container contract is invalid")
        sidecars[name] = values
    if set(sidecars) != expected_names:
        raise DeploymentRecoveryError("sealed context does not contain the exact sidecar set")
    return sidecars


def _observed_sidecars(
    revision: dict[str, Any],
    *,
    service: str,
    allow_legacy_empty_probes: bool = False,
) -> dict[str, dict[str, str]]:
    expected_names = _ALLOWED_SIDECARS.get(service, frozenset())
    if not expected_names:
        return {}
    properties = revision.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    raw_containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(raw_containers, list):
        raise DeploymentRecoveryError("revision must contain containers")
    by_name = {
        container.get("name"): container
        for container in raw_containers
        if isinstance(container, dict) and isinstance(container.get("name"), str)
    }
    if not expected_names <= set(by_name):
        raise DeploymentRecoveryError("revision does not contain the exact sidecar set")
    return {
        name: _observed_sidecar_contract(
            by_name[name],
            name=name,
            allow_legacy_empty_probes=allow_legacy_empty_probes,
        )
        for name in sorted(expected_names)
    }


def _validate_sidecar_probes(
    contract: dict[str, Any],
    *,
    name: str,
    allow_legacy_empty: bool = False,
) -> None:
    probes = contract["probes"]
    if allow_legacy_empty and probes == []:
        return
    by_type = {
        str(probe.get("type", "")).lower(): probe for probe in probes if isinstance(probe, dict)
    }
    if len(probes) != 3 or set(by_type) != {"startup", "liveness", "readiness"}:
        raise DeploymentRecoveryError(f"sidecar {name} must expose exact startup probes")
    ports: set[int] = set()
    for probe in by_type.values():
        socket = probe.get("tcpSocket")
        port = socket.get("port") if isinstance(socket, dict) else None
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 0 < port < 65536
            or "httpGet" in probe
        ):
            raise DeploymentRecoveryError(f"sidecar {name} probes must use one TCP port")
        ports.add(port)
    if len(ports) != 1 or by_type["startup"].get("failureThreshold") != 30:
        raise DeploymentRecoveryError(f"sidecar {name} probe contract changed")


def _revision_container_contracts(
    revision: dict[str, Any],
    *,
    service: str,
    allow_legacy_empty_sidecar_probes: bool = False,
) -> dict[str, Any]:
    properties = revision.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(containers, list) or not containers:
        raise DeploymentRecoveryError("revision must contain containers")
    expected_sidecars = _ALLOWED_SIDECARS.get(service, frozenset())
    if not expected_sidecars:
        if len(containers) != 1 or not isinstance(containers[0], dict):
            raise DeploymentRecoveryError(
                "revision must contain one primary and the exact allowed sidecar set"
            )
        return {
            "primary": _container_contract(containers[0], label="primary container"),
            "sidecars": {},
        }

    by_name: dict[str, dict[str, Any]] = {}
    for container in containers:
        name = container.get("name") if isinstance(container, dict) else None
        if not isinstance(name, str) or not name or name in by_name:
            raise DeploymentRecoveryError("revision container names are invalid")
        by_name[name] = container
    primary_names = set(by_name) - expected_sidecars
    if len(primary_names) != 1 or set(by_name) != primary_names | expected_sidecars:
        raise DeploymentRecoveryError(
            "revision must contain one primary and the exact allowed sidecar set"
        )
    primary = _container_contract(by_name[primary_names.pop()], label="primary container")
    sidecars: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_sidecars):
        contract = _container_contract(by_name[name], label=f"sidecar {name}")
        _validate_sidecar_probes(
            contract,
            name=name,
            allow_legacy_empty=allow_legacy_empty_sidecar_probes,
        )
        sidecars[name] = contract
    return {"primary": primary, "sidecars": sidecars}


def _target(context: dict[str, Any]) -> dict[str, Any]:
    target = context.get("target")
    if not isinstance(target, dict):
        raise DeploymentRecoveryError("sealed context has no target")
    return target


def _health_state_is_accepted(app: dict[str, Any], revision_properties: dict[str, Any]) -> bool:
    """Accept absent health only for a running no-ingress revision with a replica."""
    properties = app.get("properties")
    configuration = properties.get("configuration") if isinstance(properties, dict) else None
    if not isinstance(configuration, dict):
        raise DeploymentRecoveryError("Container App configuration is missing")
    ingress = configuration.get("ingress")
    if ingress is not None and not isinstance(ingress, dict):
        raise DeploymentRecoveryError("Container App ingress configuration is invalid")
    health_state = revision_properties.get("healthState")
    if health_state == "Healthy":
        return True
    replicas = revision_properties.get("replicas")
    return (
        ingress is None
        and health_state is None
        and revision_properties.get("runningState") == "Running"
        and isinstance(replicas, int)
        and not isinstance(replicas, bool)
        and replicas >= 1
    )


def _key_vault_secrets(app: dict[str, Any]) -> list[dict[str, str]]:
    properties = app.get("properties")
    configuration = properties.get("configuration") if isinstance(properties, dict) else None
    raw_secrets = configuration.get("secrets", []) if isinstance(configuration, dict) else []
    if not isinstance(raw_secrets, list):
        raise DeploymentRecoveryError("Container App secret configuration is invalid")
    secrets: list[dict[str, str]] = []
    for raw in raw_secrets:
        if not isinstance(raw, dict):
            raise DeploymentRecoveryError("Container App secret configuration is invalid")
        name = raw.get("name")
        key_vault_url = raw.get("keyVaultUrl")
        identity = raw.get("identity")
        if not all(isinstance(value, str) and value for value in (name, key_vault_url, identity)):
            raise DeploymentRecoveryError(
                "rollback requires every Container App secret to use a Key Vault reference"
            )
        secrets.append(
            {
                "name": cast(str, name),
                "key_vault_url": cast(str, key_vault_url),
                "identity": cast(str, identity),
            }
        )
    return sorted(secrets, key=lambda item: item["name"])


def validate_health(
    *,
    context: dict[str, Any],
    service_output: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
    previous_revision: str,
) -> None:
    """Require exact Azure identity, component, digest, and a new healthy revision."""
    target = _target(context)
    expected_subscription = _required(context, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("Azure account subscription does not match sealed context")
    expected_id = _required(target, "service_resource_id", label="service resource id")
    expected_name = _required(target, "service_name", label="service name")
    expected_component = _required(target, "component_tag", label="component tag")
    expected_image = _required(target, "image_ref", label="image reference")
    service = _required(context, "service", label="service")
    if str(service_output.get("id", "")).lower() != expected_id.lower():
        raise DeploymentRecoveryError("Terraform service resource id does not match sealed context")
    if service_output.get("name") != expected_name:
        raise DeploymentRecoveryError("Terraform service name does not match sealed context")
    if str(app.get("id", "")).lower() != expected_id.lower() or app.get("name") != expected_name:
        raise DeploymentRecoveryError(
            "observed Container App identity does not match sealed context"
        )
    tags = app.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != expected_component:
        raise DeploymentRecoveryError("observed component tag does not match sealed context")
    app_properties = app.get("properties")
    latest_revision = (
        app_properties.get("latestRevisionName") if isinstance(app_properties, dict) else None
    )
    if not isinstance(latest_revision, str):
        raise DeploymentRecoveryError("latest revision is missing from Azure state")
    if latest_revision == previous_revision:
        raise DeploymentRecoveryError("post-apply health did not observe a new revision")
    if revision.get("name") != latest_revision:
        raise DeploymentRecoveryError("health evidence is not for the new revision")
    properties = revision.get("properties")
    if not isinstance(properties, dict):
        raise DeploymentRecoveryError("revision properties are missing")
    if properties.get("provisioningState") != "Provisioned":
        raise DeploymentRecoveryError("new revision is not Provisioned")
    if not _health_state_is_accepted(app, properties) or properties.get("active") is not True:
        raise DeploymentRecoveryError("new revision is not healthy and active")
    containers = _revision_container_contracts(revision, service=service)
    if containers["primary"]["image"] != expected_image:
        raise DeploymentRecoveryError("new revision image digest does not match sealed context")
    expected_sidecars = _ALLOWED_SIDECARS.get(service, frozenset())
    if expected_sidecars:
        sealed_sidecars = _sealed_sidecars(target, service=service)
        observed_sidecars = _observed_sidecars(revision, service=service)
        for name in sorted(expected_sidecars):
            observed = observed_sidecars[name]
            expected = sealed_sidecars[name]
            for field in ("image_ref", "config_digest", "probe_digest"):
                if observed[field] != expected[field]:
                    raise DeploymentRecoveryError(
                        f"observed sidecar {name} {field.replace('_', ' ')} "
                        "does not match sealed context"
                    )


def capture_snapshot(
    *,
    context: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
    rollback_contract: dict[str, Any],
) -> dict[str, Any]:
    """Capture the exact current revision and image before applying a protected plan."""
    target = _target(context)
    expected_subscription = _required(context, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("Azure account subscription does not match sealed context")
    expected_id = _required(target, "service_resource_id", label="service resource id")
    if str(app.get("id", "")).lower() != expected_id.lower():
        raise DeploymentRecoveryError("rollback snapshot resource id does not match sealed context")
    properties = app.get("properties")
    previous_revision = (
        properties.get("latestRevisionName") if isinstance(properties, dict) else None
    )
    if not isinstance(previous_revision, str) or revision.get("name") != previous_revision:
        raise DeploymentRecoveryError("rollback snapshot revision is not the current revision")
    service = _required(context, "service", label="service")
    allow_legacy_sidecar_probes = context.get("deployment_mode") == "initial-cutover"
    containers = _revision_container_contracts(
        revision,
        service=service,
        allow_legacy_empty_sidecar_probes=allow_legacy_sidecar_probes,
    )
    legacy_sidecar_probe_rollback = any(
        contract["probes"] == [] for contract in containers["sidecars"].values()
    )
    sidecar_contracts = _observed_sidecars(
        revision,
        service=service,
        allow_legacy_empty_probes=allow_legacy_sidecar_probes,
    )
    authority_fallback = rollback_contract.get("authority_fallback", "")
    if authority_fallback not in ("", "core-in-process"):
        raise DeploymentRecoveryError("rollback authority fallback is unsupported")
    return {
        "subscription_id": expected_subscription,
        "service_resource_id": expected_id,
        "service_name": _required(target, "service_name", label="service name"),
        "resource_group": _required(target, "resource_group", label="resource group"),
        "component_tag": _required(target, "component_tag", label="component tag"),
        "service": service,
        "previous_revision": previous_revision,
        "previous_image": containers["primary"]["image"],
        "previous_containers": containers,
        "previous_sidecar_contracts": sidecar_contracts,
        "legacy_sidecar_probe_rollback": legacy_sidecar_probe_rollback,
        "previous_secrets": _key_vault_secrets(app),
        "platform_rollback_required": authority_fallback == "core-in-process",
    }


def rollback_command(snapshot: dict[str, Any], *, revision_suffix: str) -> list[str]:
    """Build a bounded revision-copy rollback using the exact captured revision and image."""
    if not re.fullmatch(r"[a-z0-9-]{1,50}", revision_suffix):
        raise DeploymentRecoveryError("rollback revision suffix is invalid")
    command = [
        "az",
        "containerapp",
        "revision",
        "copy",
        "--resource-group",
        _required(snapshot, "resource_group", label="resource group"),
        "--name",
        _required(snapshot, "service_name", label="service name"),
        "--from-revision",
        _required(snapshot, "previous_revision", label="previous revision"),
        "--revision-suffix",
        revision_suffix,
        "--only-show-errors",
        "--output",
        "json",
    ]
    return command


def validate_rollback(
    *,
    snapshot: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
) -> None:
    """Require a new healthy revision running the exact captured image after rollback."""
    expected_subscription = _required(snapshot, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("rollback subscription does not match snapshot")
    expected_id = _required(snapshot, "service_resource_id", label="service resource id")
    expected_name = _required(snapshot, "service_name", label="service name")
    if str(app.get("id", "")).lower() != expected_id.lower() or app.get("name") != expected_name:
        raise DeploymentRecoveryError("rollback Container App identity does not match snapshot")
    tags = app.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != snapshot.get("component_tag"):
        raise DeploymentRecoveryError("rollback component tag does not match snapshot")
    properties = app.get("properties")
    latest_revision = properties.get("latestRevisionName") if isinstance(properties, dict) else None
    previous_revision = _required(snapshot, "previous_revision", label="previous revision")
    if not isinstance(latest_revision, str) or latest_revision == previous_revision:
        raise DeploymentRecoveryError("rollback did not create a new recovery revision")
    revision_properties = revision.get("properties")
    if revision.get("name") != latest_revision or not isinstance(revision_properties, dict):
        raise DeploymentRecoveryError("rollback evidence is not for the recovery revision")
    if (
        revision_properties.get("provisioningState") != "Provisioned"
        or not _health_state_is_accepted(app, revision_properties)
        or revision_properties.get("active") is not True
    ):
        raise DeploymentRecoveryError("rollback revision is not healthy and active")
    service = _required(snapshot, "service", label="service")
    containers = _revision_container_contracts(
        revision,
        service=service,
        allow_legacy_empty_sidecar_probes=(snapshot.get("legacy_sidecar_probe_rollback") is True),
    )
    previous_containers = snapshot.get("previous_containers")
    if not isinstance(previous_containers, dict) or containers != previous_containers:
        raise DeploymentRecoveryError("rollback container contract does not match snapshot")
    if containers["primary"]["image"] != _required(
        snapshot, "previous_image", label="previous image"
    ):
        raise DeploymentRecoveryError("rollback revision image does not match snapshot")
    previous_sidecar_contracts = snapshot.get("previous_sidecar_contracts")
    if (
        not isinstance(previous_sidecar_contracts, dict)
        or _observed_sidecars(
            revision,
            service=service,
            allow_legacy_empty_probes=(snapshot.get("legacy_sidecar_probe_rollback") is True),
        )
        != previous_sidecar_contracts
    ):
        raise DeploymentRecoveryError("rollback sidecar contract does not match snapshot")
    previous_secrets = snapshot.get("previous_secrets")
    if not isinstance(previous_secrets, list) or _key_vault_secrets(app) != previous_secrets:
        raise DeploymentRecoveryError("rollback Key Vault secret references do not match snapshot")


def main() -> int:
    """Validate health, capture a rollback snapshot, or emit a rollback command."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    capture = commands.add_parser("capture")
    for command in (verify, capture):
        command.add_argument("--context", type=Path, required=True)
        command.add_argument("--account", type=Path, required=True)
        command.add_argument("--app", type=Path, required=True)
        command.add_argument("--revision", type=Path, required=True)
    verify.add_argument("--service-output", type=Path, required=True)
    verify.add_argument("--previous-revision", required=True)
    capture.add_argument("--rollback-contract", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    rollback = commands.add_parser("rollback-command")
    rollback.add_argument("--snapshot", type=Path, required=True)
    rollback.add_argument("--revision-suffix", required=True)
    rollback_verify = commands.add_parser("verify-rollback")
    rollback_verify.add_argument("--snapshot", type=Path, required=True)
    rollback_verify.add_argument("--account", type=Path, required=True)
    rollback_verify.add_argument("--app", type=Path, required=True)
    rollback_verify.add_argument("--revision", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_health(
                context=_object(args.context),
                service_output=_object(args.service_output),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
                previous_revision=args.previous_revision,
            )
        elif args.command == "capture":
            snapshot = capture_snapshot(
                context=_object(args.context),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
                rollback_contract=_object(args.rollback_contract),
            )
            args.output.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        elif args.command == "rollback-command":
            values = rollback_command(_object(args.snapshot), revision_suffix=args.revision_suffix)
            sys.stdout.buffer.write("\0".join(values).encode() + b"\0")
        else:
            validate_rollback(
                snapshot=_object(args.snapshot),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
            )
    except (OSError, json.JSONDecodeError, DeploymentRecoveryError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
