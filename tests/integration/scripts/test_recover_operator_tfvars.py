from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/deployment/service/recover_operator_tfvars.py"
)
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_RESOURCE_GROUP = "rg-example"
_ENVIRONMENT_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}/providers/"
    "Microsoft.App/managedEnvironments/cae-example"
)
_RUNTIME_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/id-runtime"
)
_COMMAND_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/id-command"
)
_COST_SECRET = "https://kv-example.vault.azure.net/secrets/fdai-cost-pseudonym-key"


@pytest.fixture
def recovery() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recover_operator_tfvars", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recovers_current_operator_contract_and_platform_cost_key(recovery: ModuleType) -> None:
    result = recovery.recover_operator_tfvars(_app(), _platform())

    assert result["name"] == "ca-example-operator-api"
    assert result["identity"] == {
        "runtime_resource_id": _RUNTIME_ID,
        "runtime_client_id": "runtime-client",
        "command_resource_id": _COMMAND_ID,
        "command_client_id": "command-client",
    }
    assert result["cost_pseudonym_key_secret_id"] == _COST_SECRET
    assert result["database"]["dsn_secret_id"].endswith("/fdai-operator-dsn")
    assert result["health"] == {
        "port": 8000,
        "liveness_path": "/healthz",
        "readiness_path": "/healthz",
        "startup_path": "/healthz",
        "interval_seconds": 30,
        "timeout_seconds": 3,
        "failure_count_threshold": 3,
        "startup_failure_count": 30,
    }
    assert result["rollback"]["previous_image"].endswith("@sha256:" + "a" * 64)
    assert result["runtime_call_evidence"]["caller_resource_id"].endswith(
        "/containerApps/ca-example-operator-api"
    )
    assert result["hil_callback"]["enabled"] is False
    assert "channel_edge" not in result


def test_rejects_platform_cost_key_drift(recovery: ModuleType) -> None:
    app = _app()
    app["properties"]["configuration"]["secrets"].append(
        {
            "name": "cost-pseudonym-key",
            "keyVaultUrl": "https://kv-example.vault.azure.net/secrets/another-key",
        }
    )

    with pytest.raises(
        recovery.OperatorTfvarsRecoveryError,
        match="differs from the platform-owned binding",
    ):
        recovery.recover_operator_tfvars(app, _platform())


def test_rejects_missing_distinct_command_identity(recovery: ModuleType) -> None:
    app = _app()
    app["identity"]["userAssignedIdentities"].pop(_COMMAND_ID)

    with pytest.raises(
        recovery.OperatorTfvarsRecoveryError,
        match="command identity is not attached",
    ):
        recovery.recover_operator_tfvars(app, _platform())


def _platform() -> dict[str, str]:
    return {
        "resource_group_name": _RESOURCE_GROUP,
        "container_app_environment_id": _ENVIRONMENT_ID,
        "acr_login_server": "example.azurecr.io",
        "kafka_bootstrap_servers": "example.servicebus.windows.net:9093",
        "cost_pseudonym_key_secret_id": _COST_SECRET,
    }


def _app() -> dict[str, object]:
    caller = (
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}/providers/"
        "Microsoft.App/containerApps/ca-example-operator-api"
    )
    target = (
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}/providers/"
        "Microsoft.App/containerApps/ca-example-core"
    )
    values = {
        "FDAI_API_AUDIENCE": "api://example",
        "FDAI_COMMAND_MI_CLIENT_ID": "command-client",
        "FDAI_DATABASE_ROLE": "fdai_operator",
        "FDAI_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000002",
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_HIL_DECISION_TOPIC": "fdai.hil.decisions",
        "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC": "operator.incident-intervention.requests",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
        "FDAI_MI_CLIENT_ID": "runtime-client",
        "FDAI_NOTIFICATION_RECEIPT_TOPIC": "fdai.notifications.delivery-receipts",
        "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS": "https://console.example.com",
        "FDAI_RBAC_APPROVERS_GROUP_ID": "approvers",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributors",
        "FDAI_RBAC_OWNERS_GROUP_ID": "owners",
        "FDAI_RBAC_READERS_GROUP_ID": "readers",
        "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC": "core.read-investigation.completions",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
        "FDAI_RUNTIME_CALL_CALLER_RESOURCE_ID": caller,
        "FDAI_RUNTIME_CALL_TARGET_RESOURCE_ID": target,
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
        "KAFKA_TOPIC_EVENTS": "fdai.change.events",
        "POSTGRES_HOST": "postgres.example.com",
        "RUNTIME_ENV": "dev",
    }
    probes = [
        {
            "type": probe_type,
            "httpGet": {"path": "/healthz", "port": 8000},
            "periodSeconds": 30,
            "timeoutSeconds": 3,
            "failureThreshold": 30 if probe_type == "Startup" else 3,
        }
        for probe_type in ("Liveness", "Readiness", "Startup")
    ]
    return {
        "name": "ca-example-operator-api",
        "resourceGroup": _RESOURCE_GROUP,
        "tags": {"fdai:component": "operator-service", "fdai:env": "dev"},
        "identity": {
            "userAssignedIdentities": {
                _RUNTIME_ID: {"clientId": "runtime-client"},
                _COMMAND_ID: {"clientId": "command-client"},
            }
        },
        "properties": {
            "managedEnvironmentId": _ENVIRONMENT_ID,
            "configuration": {
                "ingress": {"targetPort": 8000},
                "secrets": [
                    {
                        "name": "database-dsn",
                        "keyVaultUrl": (
                            "https://kv-example.vault.azure.net/secrets/fdai-operator-dsn"
                        ),
                    }
                ],
            },
            "template": {
                "containers": [
                    {
                        "name": "operator-service",
                        "image": "ghcr.io/example/operator@sha256:" + "a" * 64,
                        "env": [{"name": key, "value": value} for key, value in values.items()],
                        "probes": probes,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ],
                "scale": {"minReplicas": 1, "maxReplicas": 2},
            },
        },
    }
