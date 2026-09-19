#!/usr/bin/env python3
"""Recover one existing Operator service input from authoritative ARM readback."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

_RESOURCE_ID = re.compile(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/[^/]+/.+", re.I)
_SECRET_ID = re.compile(
    r"https://[a-z0-9-]{3,24}[.]vault[.]azure[.]net/secrets/[A-Za-z0-9-]{1,127}"
    r"(?:/[A-Za-z0-9-]{1,64})?"
)
_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_ENVIRONMENT_NAMES = {
    "FDAI_API_AUDIENCE": "api_audience",
    "FDAI_COMMAND_MI_CLIENT_ID": "command_client_id",
    "FDAI_DATABASE_ROLE": "database_role",
    "FDAI_ENTRA_TENANT_ID": "tenant_id",
    "FDAI_HIL_DECISION_TOPIC": "hil_decisions",
    "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC": "incident_intervention_requests",
    "FDAI_KAFKA_BOOTSTRAP_SERVERS": "kafka_bootstrap_servers",
    "FDAI_MI_CLIENT_ID": "runtime_client_id",
    "FDAI_NOTIFICATION_RECEIPT_TOPIC": "notification_receipts",
    "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS": "cors_allow_origins",
    "FDAI_RBAC_APPROVERS_GROUP_ID": "approvers_group_id",
    "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break_glass_group_id",
    "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributors_group_id",
    "FDAI_RBAC_OWNERS_GROUP_ID": "owners_group_id",
    "FDAI_RBAC_READERS_GROUP_ID": "readers_group_id",
    "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC": "read_investigation_completions",
    "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "read_investigation_requests",
    "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "semantic_physical",
    "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "semantic_projections",
    "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "semantic_requests",
    "KAFKA_TOPIC_EVENTS": "events",
    "POSTGRES_HOST": "database_host",
    "RUNTIME_ENV": "runtime_env",
}


class OperatorTfvarsRecoveryError(ValueError):
    """Raised when live Operator state cannot produce one exact safe input."""


def recover_operator_tfvars(app: dict[str, Any], platform: dict[str, Any]) -> dict[str, Any]:
    """Build current independent-service inputs without reading secret values."""

    properties = _object(app.get("properties"), "Operator properties")
    configuration = _object(properties.get("configuration"), "Operator configuration")
    template = _object(properties.get("template"), "Operator template")
    containers = _objects(template.get("containers"), "Operator containers")
    if len(containers) != 1:
        raise OperatorTfvarsRecoveryError("Operator must have exactly one container")
    container = containers[0]
    if container.get("name") != "operator-service":
        raise OperatorTfvarsRecoveryError("Operator container name is invalid")
    image = _text(container.get("image"), "Operator image")
    if _IMAGE.fullmatch(image) is None:
        raise OperatorTfvarsRecoveryError("Operator image must be pinned by sha256 digest")

    environment = _environment(container.get("env"))
    selected = {
        output: _required_environment(environment, source)
        for source, output in _ENVIRONMENT_NAMES.items()
    }
    if selected["runtime_env"] != "dev":
        raise OperatorTfvarsRecoveryError("Operator recovery is supported only in dev")
    if environment.get("FDAI_EXECUTION_VENUE") != "deployed":
        raise OperatorTfvarsRecoveryError("Operator execution venue is not deployed")

    identities = _identities(app.get("identity"))
    runtime_resource_id = _identity_for_client(
        identities, selected["runtime_client_id"], label="runtime"
    )
    command_resource_id = _identity_for_client(
        identities, selected["command_client_id"], label="command"
    )
    if runtime_resource_id.casefold() == command_resource_id.casefold():
        raise OperatorTfvarsRecoveryError("Operator runtime and command identities must differ")

    secrets = _secrets(configuration.get("secrets"))
    database_secret = _secret_reference(secrets, "database-dsn")
    platform_cost_secret = _secret_id(
        platform.get("cost_pseudonym_key_secret_id"), "Cost pseudonym key"
    )
    current_cost_secret = secrets.get("cost-pseudonym-key")
    if current_cost_secret is not None and current_cost_secret != platform_cost_secret:
        raise OperatorTfvarsRecoveryError(
            "deployed Cost pseudonym key differs from the platform-owned binding"
        )

    resource_group = _text(platform.get("resource_group_name"), "platform resource group")
    if app.get("resourceGroup") != resource_group:
        raise OperatorTfvarsRecoveryError("Operator resource group differs from platform state")
    environment_id = _resource_id(
        platform.get("container_app_environment_id"), "Container Apps environment"
    )
    if str(properties.get("managedEnvironmentId", "")).casefold() != environment_id.casefold():
        raise OperatorTfvarsRecoveryError(
            "Operator Container Apps environment differs from platform state"
        )
    kafka_bootstrap = _text(platform.get("kafka_bootstrap_servers"), "Kafka bootstrap servers")
    if selected["kafka_bootstrap_servers"] != kafka_bootstrap:
        raise OperatorTfvarsRecoveryError("Operator Kafka binding differs from platform state")

    recovered: dict[str, Any] = {
        "name": _text(app.get("name"), "Operator name"),
        "platform": {
            "resource_group_name": resource_group,
            "container_app_environment_id": environment_id,
            "acr_login_server": _text(
                platform.get("acr_login_server"), "container registry login server"
            ),
            "kafka_bootstrap_servers": kafka_bootstrap,
        },
        "identity": {
            "runtime_resource_id": runtime_resource_id,
            "runtime_client_id": selected["runtime_client_id"],
            "command_resource_id": command_resource_id,
            "command_client_id": selected["command_client_id"],
        },
        "event_topics": {
            key: selected[key]
            for key in (
                "events",
                "semantic_requests",
                "semantic_projections",
                "semantic_physical",
                "read_investigation_requests",
                "incident_intervention_requests",
                "read_investigation_completions",
                "hil_decisions",
                "notification_receipts",
            )
        },
        "notification_receipt_secret_id": secrets.get("notification-receipt-secret", ""),
        "cost_pseudonym_key_secret_id": platform_cost_secret,
        "database": {
            "dsn_secret_id": database_secret,
            "host": selected["database_host"],
            "role": selected["database_role"],
        },
        "health": _health(container, configuration),
        "rollback": {
            "strategy": "previous-revision",
            "previous_image": image,
            "max_unavailable_replicas": 0,
        },
        "runtime_env": selected["runtime_env"],
        "auth": {
            "tenant_id": selected["tenant_id"],
            "api_audience": selected["api_audience"],
        },
        "rbac": {
            key: selected[key]
            for key in (
                "readers_group_id",
                "contributors_group_id",
                "approvers_group_id",
                "owners_group_id",
                "break_glass_group_id",
            )
        },
        "cors_allow_origins": selected["cors_allow_origins"],
        "scaling": _scaling(template, container),
        "hil_callback": _hil_callback(environment, secrets),
        "tags": _string_mapping(app.get("tags"), "Operator tags"),
    }
    runtime_caller = environment.get("FDAI_RUNTIME_CALL_CALLER_RESOURCE_ID")
    runtime_target = environment.get("FDAI_RUNTIME_CALL_TARGET_RESOURCE_ID")
    if bool(runtime_caller) != bool(runtime_target):
        raise OperatorTfvarsRecoveryError("Operator runtime-call binding is incomplete")
    if runtime_caller and runtime_target:
        recovered["runtime_call_evidence"] = {
            "caller_resource_id": _resource_id(runtime_caller, "runtime-call caller"),
            "target_resource_id": _resource_id(runtime_target, "runtime-call target"),
        }
    return recovered


def _environment(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _objects(value, "Operator environment"):
        name = _text(item.get("name"), "Operator environment name")
        if name in result:
            raise OperatorTfvarsRecoveryError(f"Operator environment contains duplicate {name}")
        if "secretRef" in item:
            continue
        result[name] = _text(item.get("value"), f"Operator environment {name}")
    return result


def _identities(value: object) -> dict[str, str]:
    identity = _object(value, "Operator identity")
    raw = _object(identity.get("userAssignedIdentities"), "Operator user-assigned identities")
    result: dict[str, str] = {}
    for resource_id, binding in raw.items():
        identifier = _resource_id(resource_id, "Operator identity resource")
        client_id = _text(
            _object(binding, "Operator identity binding").get("clientId"),
            "identity client",
        )
        if client_id.casefold() in result:
            raise OperatorTfvarsRecoveryError("Operator identity client id is duplicated")
        result[client_id.casefold()] = identifier
    return result


def _identity_for_client(identities: dict[str, str], client_id: str, *, label: str) -> str:
    try:
        return identities[client_id.casefold()]
    except KeyError as exc:
        raise OperatorTfvarsRecoveryError(
            f"Operator {label} identity is not attached to the Container App"
        ) from exc


def _secrets(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _objects(value, "Operator secrets"):
        name = _text(item.get("name"), "Operator secret name")
        if name in result:
            raise OperatorTfvarsRecoveryError(f"Operator secrets contain duplicate {name}")
        result[name] = _secret_id(item.get("keyVaultUrl"), f"Operator secret {name}")
    return result


def _secret_reference(secrets: dict[str, str], name: str) -> str:
    try:
        return secrets[name]
    except KeyError as exc:
        raise OperatorTfvarsRecoveryError(f"Operator secret {name} is unavailable") from exc


def _health(container: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
    probes = _objects(container.get("probes"), "Operator probes")
    by_type = {str(probe.get("type", "")).casefold(): probe for probe in probes}
    if set(by_type) != {"liveness", "readiness", "startup"} or len(probes) != 3:
        raise OperatorTfvarsRecoveryError("Operator probe contract is incomplete")
    paths: dict[str, str] = {}
    values: dict[str, int] = {}
    for probe_type, field in (
        ("liveness", "liveness_path"),
        ("readiness", "readiness_path"),
        ("startup", "startup_path"),
    ):
        probe = by_type[probe_type]
        http_get = _object(probe.get("httpGet"), f"Operator {probe_type} probe")
        paths[field] = _text(http_get.get("path"), f"Operator {probe_type} path")
        port = _integer(http_get.get("port"), f"Operator {probe_type} port")
        values.setdefault("port", port)
        if values["port"] != port:
            raise OperatorTfvarsRecoveryError("Operator probes use different ports")
    readiness = by_type["readiness"]
    startup = by_type["startup"]
    ingress = _object(configuration.get("ingress"), "Operator ingress")
    if _integer(ingress.get("targetPort"), "Operator ingress port") != values["port"]:
        raise OperatorTfvarsRecoveryError("Operator ingress and probe ports differ")
    return {
        "port": values["port"],
        **paths,
        "interval_seconds": _integer(readiness.get("periodSeconds"), "probe interval"),
        "timeout_seconds": _integer(readiness.get("timeoutSeconds"), "probe timeout"),
        "failure_count_threshold": _integer(
            readiness.get("failureThreshold"), "probe failure threshold"
        ),
        "startup_failure_count": _integer(
            startup.get("failureThreshold"), "startup failure threshold"
        ),
    }


def _scaling(template: dict[str, Any], container: dict[str, Any]) -> dict[str, Any]:
    scale = _object(template.get("scale"), "Operator scale")
    resources = _object(container.get("resources"), "Operator resources")
    return {
        "min_replicas": _integer(scale.get("minReplicas"), "minimum replicas"),
        "max_replicas": _integer(scale.get("maxReplicas"), "maximum replicas"),
        "cpu": resources.get("cpu"),
        "memory": _text(resources.get("memory"), "Operator memory"),
    }


def _hil_callback(environment: dict[str, str], secrets: dict[str, str]) -> dict[str, Any]:
    enabled = "hil-callback-signing-secret" in secrets
    teams_application_id = environment.get("FDAI_TEAMS_APPLICATION_ID", "")
    slack_team_id = environment.get("FDAI_SLACK_TEAM_ID", "")
    if enabled and not (teams_application_id or slack_team_id):
        raise OperatorTfvarsRecoveryError("enabled HIL callback has no channel binding")
    return {
        "enabled": enabled,
        "signing_secret_id": secrets.get("hil-callback-signing-secret", ""),
        "teams_application_id": teams_application_id,
        "teams_tenant_id": environment.get("FDAI_TEAMS_TENANT_ID", ""),
        "teams_approval_team_id": environment.get("FDAI_TEAMS_APPROVAL_TEAM_ID", ""),
        "teams_approval_channel_id": environment.get("FDAI_TEAMS_APPROVAL_CHANNEL_ID", ""),
        "teams_allowed_service_urls": environment.get("FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON", ""),
        "teams_jwks_url": environment.get("FDAI_TEAMS_JWKS_URL", ""),
        "teams_principal_map_secret_id": secrets.get("hil-teams-principal-map", ""),
        "slack_team_id": slack_team_id,
        "slack_principal_map_secret_id": secrets.get("hil-slack-principal-map", ""),
    }


def _required_environment(environment: dict[str, str], name: str) -> str:
    try:
        return environment[name]
    except KeyError as exc:
        raise OperatorTfvarsRecoveryError(f"Operator environment is missing {name}") from exc


def _objects(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise OperatorTfvarsRecoveryError(f"{label} must be an array of objects")
    return value


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperatorTfvarsRecoveryError(f"{label} must be an object")
    return value


def _string_mapping(value: object, label: str) -> dict[str, str]:
    result = _object(value, label)
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in result.items()):
        raise OperatorTfvarsRecoveryError(f"{label} must contain string values")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OperatorTfvarsRecoveryError(f"{label} must be a non-empty string")
    return value


def _resource_id(value: object, label: str) -> str:
    result = _text(value, label)
    if _RESOURCE_ID.fullmatch(result) is None:
        raise OperatorTfvarsRecoveryError(f"{label} must be an Azure resource id")
    return result


def _secret_id(value: object, label: str) -> str:
    result = _text(value, label)
    if _SECRET_ID.fullmatch(result) is None:
        raise OperatorTfvarsRecoveryError(f"{label} must be an Azure Key Vault secret id")
    return result


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OperatorTfvarsRecoveryError(f"{label} must be a positive integer")
    return value


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _object(value, label)


def _write_private(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--platform", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        recovered = recover_operator_tfvars(
            _read_object(args.app, "Operator ARM readback"),
            _read_object(args.platform, "platform binding"),
        )
        _write_private(args.output, recovered)
    except (OSError, json.JSONDecodeError, OperatorTfvarsRecoveryError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
