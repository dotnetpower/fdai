"""Protected independent-service deployment contract tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts" / "deployment" / "service"
_CORE_TERRAFORM = (
    _ROOT
    / "infra"
    / "services"
    / "core-control-plane"
    / "modules"
    / "core-control-plane"
    / "main.tf"
).read_text(encoding="utf-8")
_SHARED_CONTAINER_APP_TERRAFORM = (
    _ROOT / "infra" / "services" / "_modules" / "container-app" / "main.tf"
).read_text(encoding="utf-8")
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    return _load("service_contract")


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    return _load("guard_plan")


@pytest.fixture(scope="module")
def bundle() -> ModuleType:
    return _load("plan_bundle")


@pytest.fixture(scope="module")
def tfvars() -> ModuleType:
    return _load("materialize_tfvars")


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    return _load("state_migration")


@pytest.fixture(scope="module")
def peer_state() -> ModuleType:
    return _load("peer_state")


@pytest.fixture(scope="module")
def recovery() -> ModuleType:
    return _load("deployment_recovery")


@pytest.fixture(scope="module")
def live_observation() -> ModuleType:
    return _load("live_observation")


@pytest.fixture(scope="module")
def promotion() -> ModuleType:
    return _load("sidecar_promotion")


def test_service_helpers_do_not_expose_completed_event_bus_migration() -> None:
    retired_tokens = (
        "event_bus_topic_migration",
        "event-bus-topic-migration",
        "migrate_event_bus_topics",
    )
    for name in ("service_contract", "materialize_tfvars", "guard_plan", "plan_bundle"):
        source = (_SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        for token in retired_tokens:
            assert token not in source


def _image(service_image: str) -> str:
    return f"ghcr.io/example/fdai/{service_image}@sha256:{'a' * 64}"


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _resource(*, image: str = "old-image") -> dict[str, object]:
    return {
        "id": (
            "/subscriptions/example-subscription/resourceGroups/example/providers/"
            "Microsoft.App/containerApps/example"
        ),
        "name": "example",
        "resource_group_name": "example",
        "max_inactive_revisions": 0,
        "container_app_environment_id": (
            "/subscriptions/example-subscription/resourceGroups/example/providers/Microsoft.App/"
            "managedEnvironments/example"
        ),
        "identity": [
            {
                "type": "UserAssigned",
                "identity_ids": [
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ],
            }
        ],
        "registry": [
            {
                "server": "example.azurecr.io",
                "identity": (
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ),
            }
        ],
        "secret": [
            {
                "name": "database-dsn",
                "identity": (
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ),
                "key_vault_secret_id": (
                    "/subscriptions/example/resourceGroups/example/providers/"
                    "Microsoft.KeyVault/vaults/example/secrets/database"
                ),
            }
        ],
        "template": [
            {
                "container": [
                    {
                        "name": "operator-service",
                        "image": image,
                        "command": ["fdai-operator-service"],
                        "args": [],
                        "env": [
                            {"name": "FDAI_DATABASE_URL", "secret_name": "database-dsn"},
                            {"name": "POSTGRES_HOST", "value": "db.example.com"},
                            {"name": "FDAI_DATABASE_ROLE", "value": "fdai_operator"},
                            {"name": "FDAI_EXECUTION_VENUE", "value": "deployed"},
                            {"name": "RUNTIME_ENV", "value": "dev"},
                            {"name": "FDAI_MI_CLIENT_ID", "value": "runtime"},
                            {"name": "FDAI_COMMAND_MI_CLIENT_ID", "value": "command"},
                            {"name": "FDAI_KAFKA_BOOTSTRAP_SERVERS", "value": "example"},
                            {"name": "KAFKA_TOPIC_EVENTS", "value": "events"},
                            {
                                "name": "FDAI_SEMANTIC_TURN_REQUEST_TOPIC",
                                "value": "operator.semantic-turn.requests",
                            },
                            {
                                "name": "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC",
                                "value": "core.semantic-turn.projections",
                            },
                            {
                                "name": "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC",
                                "value": "fdai.pantheon.objects",
                            },
                            {
                                "name": "FDAI_READ_INVESTIGATION_REQUEST_TOPIC",
                                "value": "operator.read-investigation.requests",
                            },
                            {
                                "name": "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC",
                                "value": "core.read-investigation.completions",
                            },
                            {
                                "name": "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID",
                                "value": "operator-read-investigation-completion-v1",
                            },
                            {
                                "name": "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC",
                                "value": "operator.incident-intervention.requests",
                            },
                            {
                                "name": "FDAI_HIL_DECISION_TOPIC",
                                "value": "operator.hil-decisions",
                            },
                            {"name": "FDAI_ENTRA_TENANT_ID", "value": "tenant"},
                            {"name": "FDAI_API_AUDIENCE", "value": "audience"},
                            {"name": "FDAI_RBAC_READERS_GROUP_ID", "value": "reader"},
                            {
                                "name": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
                                "value": "contributor",
                            },
                            {"name": "FDAI_RBAC_APPROVERS_GROUP_ID", "value": "approver"},
                            {"name": "FDAI_RBAC_OWNERS_GROUP_ID", "value": "owner"},
                            {
                                "name": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
                                "value": "break-glass",
                            },
                            {
                                "name": "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS",
                                "value": "https://example.com",
                            },
                            {"name": "FDAI_OPERATOR_SERVICE_PORT", "value": "8000"},
                        ],
                    }
                ]
            }
        ],
        "tags": {"fdai:component": "operator-service"},
    }


def _plan(address: str, actions: list[str], *, image: str = "image") -> dict[str, object]:
    before = _resource()
    after = copy.deepcopy(before)
    after["template"][0]["container"][0]["image"] = image  # type: ignore[index]
    return {
        "resource_changes": [
            {
                "address": address,
                "change": {
                    "actions": actions,
                    "before": before,
                    "after": after,
                },
            }
        ]
    }


def _remove_environment_binding(plan: dict[str, object], name: str) -> None:
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    for side in ("before", "after"):
        environment = change[side]["template"][0]["container"][0]["env"]
        environment[:] = [item for item in environment if item["name"] != name]


def _document_ingestion_plan(guard: ModuleType) -> dict[str, object]:
    address = "module.document_ingestion_api.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    contract = guard.resolve_service("document-ingestion-api", "dev")
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    for side in ("before", "after"):
        resource = change[side]
        container = resource["template"][0]["container"][0]
        container["name"] = "document-ingestion-api"
        container["command"] = ["fdai-document-ingestion-api"]
        container["env"] = [
            {"name": name, "value": f"value-{index}"}
            for index, name in enumerate(contract.required_environment)
        ]
        resource["tags"]["fdai:component"] = "document-ingestion-api"
    return plan


def _sharepoint_connector_environment() -> list[dict[str, str]]:
    return [
        {"name": "FDAI_SHAREPOINT_CONNECTOR_ENABLED", "value": "1"},
        {"name": "FDAI_SHAREPOINT_CONNECTOR_ID", "value": "sharepoint-primary"},
        {
            "name": "FDAI_SHAREPOINT_TARGET_TENANT_ID",
            "value": "00000000-0000-0000-0000-000000000000",
        },
        {
            "name": "FDAI_SHAREPOINT_CLIENT_ID",
            "value": "00000000-0000-0000-0000-000000000000",
        },
        {"name": "FDAI_SHAREPOINT_SITE_ID", "value": "site"},
        {"name": "FDAI_SHAREPOINT_DRIVE_ID", "value": "drive"},
        {"name": "FDAI_SHAREPOINT_COLLECTION_ID", "value": "collection"},
        {"name": "FDAI_SHAREPOINT_ACCESS_DESCRIPTOR_REF", "value": "access:sharepoint"},
        {"name": "FDAI_SHAREPOINT_READER_GROUPS", "value": ""},
        {"name": "FDAI_SHAREPOINT_RETENTION_POLICY_VERSION", "value": "retention-v1"},
        {"name": "FDAI_SHAREPOINT_PURPOSES", "value": "knowledge_base"},
        {
            "name": "FDAI_SHAREPOINT_DOWNLOAD_HOST_SUFFIXES",
            "value": ".sharepoint.com",
        },
    ]


def _channel_edge_enable_plan() -> dict[str, object]:
    address = "module.operator_service.module.channel_edge[0].azurerm_container_app.service"
    resource = _resource(image="image")
    resource["name"] = "example-channel-edge"
    resource["id"] = (
        "/subscriptions/example-subscription/resourceGroups/example/providers/"
        "Microsoft.App/containerApps/example-channel-edge"
    )
    resource["identity"][0]["identity_ids"] = [  # type: ignore[index]
        "/subscriptions/example-subscription/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/channel-edge"
    ]
    edge_identity = resource["identity"][0]["identity_ids"][0]  # type: ignore[index]
    resource["registry"][0]["identity"] = edge_identity  # type: ignore[index]
    resource["secret"] = [  # type: ignore[index]
        {
            "name": "edge-database-dsn",
            "identity": edge_identity,
            "key_vault_secret_id": (
                "/subscriptions/example/resourceGroups/example/providers/"
                "Microsoft.KeyVault/vaults/example/secrets/database"
            ),
        },
        {
            "name": "edge-principal-scopes",
            "identity": edge_identity,
            "key_vault_secret_id": (
                "/subscriptions/example/resourceGroups/example/providers/"
                "Microsoft.KeyVault/vaults/example/secrets/principal-scopes"
            ),
        },
    ]
    resource["template"][0]["container"] = [  # type: ignore[index]
        {
            "name": "operator-channel-edge",
            "image": "image",
            "command": ["fdai-operator-channel-edge"],
            "args": [],
            "env": [
                {"name": "FDAI_DATABASE_URL", "secret_name": "edge-database-dsn"},
                {"name": "FDAI_DATABASE_ROLE", "value": "fdai_operator"},
                {"name": "FDAI_EXECUTION_VENUE", "value": "deployed"},
                {"name": "RUNTIME_ENV", "value": "dev"},
                {"name": "FDAI_CHANNEL_EDGE_MI_CLIENT_ID", "value": "channel-edge"},
                {"name": "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS", "value": "slack"},
                {
                    "name": "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON",
                    "secret_name": "edge-principal-scopes",
                },
                {"name": "FDAI_KAFKA_BOOTSTRAP_SERVERS", "value": "example"},
                {"name": "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", "value": "requests"},
                {"name": "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", "value": "projections"},
                {"name": "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC", "value": "physical"},
                {"name": "FDAI_CHANNEL_EDGE_PORT", "value": "8014"},
                {"name": "FDAI_SLACK_SIGNING_SECRET", "secret_name": "slack-signing-secret"},
                {"name": "FDAI_SLACK_BOT_TOKEN", "secret_name": "slack-bot-token"},
                {"name": "FDAI_SLACK_TEAM_ID", "value": "example-team"},
                {
                    "name": "FDAI_SLACK_PRINCIPAL_MAP_JSON",
                    "secret_name": "slack-principal-map",
                },
            ],
            "startup_probe": [
                {
                    "transport": "HTTP",
                    "port": 8014,
                    "path": "/health/ready",
                    "failure_count_threshold": 30,
                }
            ],
            "liveness_probe": [
                {
                    "transport": "HTTP",
                    "port": 8014,
                    "path": "/health/live",
                    "failure_count_threshold": 3,
                }
            ],
            "readiness_probe": [
                {
                    "transport": "HTTP",
                    "port": 8014,
                    "path": "/health/ready",
                    "failure_count_threshold": 3,
                }
            ],
        }
    ]
    resource["ingress"] = [
        {
            "external_enabled": True,
            "allow_insecure_connections": False,
            "target_port": 8014,
        }
    ]
    resource["tags"] = {"fdai:component": "operator-channel-edge"}
    return {
        "resource_changes": [
            {
                "address": "module.operator_service.terraform_data.channel_edge_contract[0]",
                "change": {"actions": ["create"], "before": None, "after": {}},
            },
            {
                "address": address,
                "change": {"actions": ["create"], "before": None, "after": resource},
            },
        ]
    }


def _channel_edge_update_plan() -> dict[str, object]:
    plan = _channel_edge_enable_plan()
    app_change = plan["resource_changes"][1]["change"]  # type: ignore[index]
    before = copy.deepcopy(app_change["after"])
    before["template"][0]["container"][0]["image"] = "old-image"  # type: ignore[index]
    app_change.update({"actions": ["update"], "before": before})
    plan["resource_changes"] = [plan["resource_changes"][1]]  # type: ignore[index]
    return plan


def _channel_edge_disable_plan() -> dict[str, object]:
    plan = _channel_edge_enable_plan()
    for entry in plan["resource_changes"]:  # type: ignore[union-attr]
        change = entry["change"]
        change.update({"actions": ["delete"], "before": change["after"], "after": None})
    return plan


def _worker_plan() -> dict[str, object]:
    address = "module.document_processing_worker.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    before = plan["resource_changes"][0]["change"]["before"]  # type: ignore[index]
    after = plan["resource_changes"][0]["change"]["after"]  # type: ignore[index]
    for resource in (before, after):
        primary = resource["template"][0]["container"][0]  # type: ignore[index]
        primary["name"] = "document-processing-worker"
        primary["command"] = ["fdai-document-processing-worker"]
        primary["env"] = [
            {"name": name, "value": "example"}
            for name in (
                "FDAI_DATABASE_URL",
                "POSTGRES_HOST",
                "FDAI_DATABASE_ROLE",
                "FDAI_INGESTION_DEPLOYMENT_ROLE",
                "FDAI_EXECUTION_VENUE",
                "RUNTIME_ENV",
                "FDAI_MI_CLIENT_ID",
                "FDAI_KAFKA_BOOTSTRAP_SERVERS",
                "FDAI_DOCUMENT_EVENT_TOPIC",
                "FDAI_PANTHEON_OBJECT_TOPIC",
                "FDAI_EMBEDDING_ENDPOINT",
                "FDAI_EMBEDDING_DEPLOYMENT",
                "FDAI_ADLS_ACCOUNT_NAME",
                "FDAI_ADLS_ACCOUNT_URL",
                "FDAI_ADLS_SOURCE_FILE_SYSTEM",
                "FDAI_ADLS_DERIVED_FILE_SYSTEM",
                "FDAI_INGESTION_WORKER_HEALTH_PORT",
                "FDAI_CLAMAV_HOST",
                "FDAI_CLAMAV_PORT",
            )
        ]
        resource["tags"] = {"fdai:component": "document-processing-worker"}
        resource["template"][0]["container"].append(  # type: ignore[index]
            {
                "name": "clamav",
                "image": "docker.io/clamav/clamav@sha256:" + "b" * 64,
                "cpu": 0.5,
                "memory": "1Gi",
                "startup_probe": [
                    {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 30,
                        "interval_seconds": 5,
                        "timeout": 3,
                    }
                ],
                "liveness_probe": [
                    {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 3,
                        "initial_delay": 1,
                        "interval_seconds": 30,
                        "timeout": 3,
                    }
                ],
                "readiness_probe": [
                    {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 3,
                        "interval_seconds": 10,
                        "success_count_threshold": 3,
                        "timeout": 3,
                    }
                ],
            }
        )
    return plan


def _bundle_coordinates() -> dict[str, str]:
    return {
        "tenant_id": "example-tenant",
        "subscription_id": "example-subscription",
        "backend_resource_group": "example-state-rg",
        "backend_storage_account": "examplestate",
        "backend_container": "tfstate",
        "workflow_run_attempt": "2",
        "controls_commit_sha": "d" * 40,
        "attestation_signer_workflow": "example/fdai/.github/workflows/container-supply-chain.yml",
    }


def _sidecar_promotion_inputs(bundle: ModuleType) -> dict[str, object]:
    plan = _worker_plan()
    before = plan["resource_changes"][0]["change"]["before"]  # type: ignore[index]
    after = plan["resource_changes"][0]["change"]["after"]  # type: ignore[index]
    after["template"][0]["container"][0]["image"] = before["template"][0][  # type: ignore[index]
        "container"
    ][0]["image"]
    old_image = "docker.io/clamav/clamav@sha256:" + "b" * 64
    new_image = "docker.io/clamav/clamav@sha256:" + "c" * 64
    after["template"][0]["container"][1]["image"] = new_image  # type: ignore[index]
    context_digest = "d" * 64
    sidecar_contract = bundle.planned_sidecar_contract(
        before["template"][0]["container"][1],  # type: ignore[index]
        name="clamav",
    )
    plan_context = {
        "service": "document-processing-worker",
        "environment": "dev",
        "commit_sha": "e" * 40,
        "target": {
            "service_resource_id": before["id"],  # type: ignore[index]
            "service_name": before["name"],  # type: ignore[index]
            "sidecar_containers": [sidecar_contract],
        },
    }
    approval = {
        "schema_version": "fdai.sidecar-promotion-approval.v1",
        "status": "approved",
        "service": "document-processing-worker",
        "sidecar": "clamav",
        "old_image_ref": old_image,
        "new_image_ref": new_image,
        "plan_context_digest": context_digest,
        "approval_id": "approval-example",
        "requested_by": "requester@example.com",
        "approved_by": ["approver@example.com"],
    }
    attestation = {
        "schema_version": "fdai.sidecar-attestation-proof.v1",
        "verified": True,
        "subject_digest": "sha256:" + "c" * 64,
        "source_revision": "e" * 40,
        "signer_workflow": "example/clamav/.github/workflows/container-supply-chain.yml",
        "predicate_type": "https://slsa.dev/provenance/v1",
    }
    scan = {
        "schema_version": "fdai.sidecar-scan-proof.v1",
        "passed": True,
        "subject_digest": "sha256:" + "c" * 64,
        "scanner": "trivy",
        "severities": ["MEDIUM", "HIGH", "CRITICAL"],
        "report_digest": "f" * 64,
    }
    return {
        "plan": plan,
        "plan_context": plan_context,
        "plan_context_digest": context_digest,
        "approval": approval,
        "attestation": attestation,
        "scan": scan,
        "old_image_ref": old_image,
        "new_image_ref": new_image,
    }


def _write_plan_json(
    path: Path,
    *,
    image: str,
    address: str = "module.operator_service.module.container_app.azurerm_container_app.service",
) -> None:
    path.write_text(json.dumps(_plan(address, ["update"], image=image)) + "\n", encoding="utf-8")


def _state(*addresses: str, resource_id: str | None = None) -> dict[str, object]:
    return {
        "values": {
            "root_module": {
                "resources": [
                    {
                        "address": address,
                        "values": {
                            "id": resource_id
                            or (
                                "/subscriptions/example/resourceGroups/example/providers/"
                                f"Microsoft.App/containerApps/{address}"
                            )
                        },
                    }
                    for address in addresses
                ],
                "child_modules": [],
            }
        }
    }


def _write_fake_terraform(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import shutil
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            state_dir = Path(os.environ["FAKE_STATE_DIR"])
            log_path = state_dir / "calls.log"
            with log_path.open("a", encoding="utf-8") as log:
                log.write(" ".join(args) + "\\n")
            root = None
            if args and args[0].startswith("-chdir="):
                root = Path(args.pop(0).split("=", 1)[1]).name

            if args[:2] == ["state", "pull"]:
                sys.stdout.write((state_dir / f"{root}.json").read_text(encoding="utf-8"))
            elif args and args[0] == "show":
                sys.stdout.write(Path(args[-1]).read_text(encoding="utf-8"))
            elif args[:2] == ["state", "list"]:
                state_path = Path(
                    next(
                        value.split("=", 1)[1]
                        for value in args
                        if value.startswith("-state=")
                    )
                )
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                for resource in payload["values"]["root_module"]["resources"]:
                    print(resource["address"])
            elif args[:2] == ["state", "mv"]:
                source_path = Path(
                    next(
                        value.split("=", 1)[1]
                        for value in args
                        if value.startswith("-state=")
                    )
                )
                destination_path = Path(
                    next(
                        value.split("=", 1)[1]
                        for value in args
                        if value.startswith("-state-out=")
                    )
                )
                source_address, destination_address = args[-2:]
                source = json.loads(source_path.read_text(encoding="utf-8"))
                destination = json.loads(destination_path.read_text(encoding="utf-8"))
                source_resources = source["values"]["root_module"]["resources"]
                moved = next(item for item in source_resources if item["address"] == source_address)
                source_resources.remove(moved)
                moved["address"] = destination_address
                destination["values"]["root_module"]["resources"].append(moved)
                source_path.write_text(json.dumps(source), encoding="utf-8")
                destination_path.write_text(json.dumps(destination), encoding="utf-8")
            elif args[:2] == ["state", "push"]:
                force = "-force" in args
                candidate = Path(args[-1])
                marker = state_dir / "source-push-failed"
                if root == "source" and not force and not marker.exists():
                    marker.write_text("failed\\n", encoding="utf-8")
                    raise SystemExit(9)
                shutil.copyfile(candidate, state_dir / f"{root}.json")
            else:
                raise SystemExit(f"unsupported fake terraform command: {args!r}")
            """
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _health_evidence() -> tuple[dict[str, object], ...]:
    image = _image("fdai-operator-service")
    identity_id = (
        "/subscriptions/example-subscription/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
    )
    resource_id = (
        "/subscriptions/example-subscription/resourceGroups/example/providers/"
        "Microsoft.App/containerApps/example"
    )
    context = {
        "service": "operator-service",
        "subscription_id": "example-subscription",
        "target": {
            "service_resource_id": resource_id.lower(),
            "service_name": "example",
            "resource_group": "example",
            "component_tag": "operator-service",
            "image_ref": image,
            "identity_resource_ids": [identity_id.lower()],
        },
    }
    service_output = {
        "id": resource_id,
        "name": "example",
        "latest_revision_name": "example--new",
    }
    account = {"id": "example-subscription"}
    app = {
        "id": resource_id,
        "name": "example",
        "tags": {"fdai:component": "operator-service"},
        "identity": {"userAssignedIdentities": {identity_id: {}}},
        "properties": {
            "latestRevisionName": "example--new",
            "configuration": {"ingress": {"external": True}},
        },
    }
    revision = {
        "name": "example--new",
        "properties": {
            "provisioningState": "Provisioned",
            "healthState": "Healthy",
            "active": True,
            "template": {"containers": [{"image": image, "probes": []}]},
        },
    }
    return context, service_output, account, app, revision


def _worker_health_evidence() -> tuple[dict[str, object], ...]:
    evidence = [copy.deepcopy(item) for item in _health_evidence()]
    context = evidence[0]
    app = evidence[3]
    revision = evidence[4]
    context["service"] = "document-processing-worker"
    context["target"]["component_tag"] = "document-processing-worker"  # type: ignore[index]
    context["target"]["image_ref"] = _image("fdai-document-processing-worker")  # type: ignore[index]
    context["target"]["sidecar_containers"] = [  # type: ignore[index]
        {
            "name": "clamav",
            "image_ref": "docker.io/clamav/clamav@sha256:" + "b" * 64,
            "config_digest": _canonical_digest(
                {"name": "clamav", "resources": {"cpu": 0.5, "memory": "1Gi"}}
            ),
            "probe_digest": _canonical_digest(
                {
                    "startup_probe": {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 30,
                        "interval_seconds": 5,
                        "timeout": 3,
                    },
                    "liveness_probe": {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 3,
                        "initial_delay": 1,
                        "interval_seconds": 30,
                        "timeout": 3,
                    },
                    "readiness_probe": {
                        "transport": "TCP",
                        "port": 3310,
                        "failure_count_threshold": 3,
                        "interval_seconds": 10,
                        "success_count_threshold": 3,
                        "timeout": 3,
                    },
                }
            ),
        }
    ]
    app["tags"] = {"fdai:component": "document-processing-worker"}
    revision["properties"]["template"]["containers"] = [  # type: ignore[index]
        {
            "name": "document-processing-worker",
            "image": _image("fdai-document-processing-worker"),
            "probes": [
                {"type": "Liveness", "httpGet": {"path": "/live", "port": 8000}},
                {"type": "Readiness", "httpGet": {"path": "/ready", "port": 8000}},
            ],
        },
        {
            "name": "clamav",
            "image": "docker.io/clamav/clamav@sha256:" + "b" * 64,
            "resources": {"cpu": 0.5, "memory": "1Gi"},
            "probes": [
                {
                    "type": "Startup",
                    "tcpSocket": {"port": 3310},
                    "failureThreshold": 30,
                    "periodSeconds": 5,
                    "timeoutSeconds": 3,
                },
                {
                    "type": "Liveness",
                    "tcpSocket": {"port": 3310},
                    "failureThreshold": 3,
                    "initialDelaySeconds": 1,
                    "periodSeconds": 30,
                    "timeoutSeconds": 3,
                },
                {
                    "type": "Readiness",
                    "tcpSocket": {"port": 3310},
                    "failureThreshold": 3,
                    "periodSeconds": 10,
                    "successThreshold": 3,
                    "timeoutSeconds": 3,
                },
            ],
        },
    ]
    return tuple(evidence)


def test_matrix_resolves_exact_five_services_and_state_keys(contract: ModuleType) -> None:
    matrix = contract.load_matrix()
    assert set(matrix["services"]) == {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    assert {service["migration_dsn_secret_name"] for service in matrix["services"].values()} == {
        "fdai-state-store-dsn"
    }
    for service, metadata in matrix["services"].items():
        assert "POSTGRES_HOST" in metadata["required_environment"]
        resolved = contract.resolve_service(service, "staging")
        assert resolved.backend_key == f"services/{service}/staging.tfstate"
        assert resolved.terraform_root == f"infra/services/{service}"


def test_core_contract_requires_complete_bootstrap_environment(contract: ModuleType) -> None:
    resolved = contract.resolve_service("core-control-plane", "dev")
    assert {
        "AZURE_TENANT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_REGION",
        "POSTGRES_HOST",
        "POSTGRES_DATABASE",
        "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS",
        "FDAI_CANARY_TOPIC",
        "FDAI_HIL_DECISION_TOPIC",
        "FDAI_INVENTORY_RAW_TOPIC",
        "FDAI_STAGE_TOPIC",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC",
        "FDAI_STARTUP_KAFKA_PROBE_TOPIC",
        "FDAI_STARTUP_KAFKA_SETTLE_SECONDS",
        "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS",
        "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS",
        "FDAI_START_CONSUMER",
    } <= set(resolved.required_environment)
    assert '{ name = "FDAI_START_CONSUMER", value = "1" }' in _CORE_TERRAFORM
    assert "value = tostring(var.startup_readiness.kafka_settle_seconds)" in _CORE_TERRAFORM
    core_variables = (
        _ROOT / "infra" / "services" / "core-control-plane" / "variables.tf"
    ).read_text(encoding="utf-8")
    core_root = (_ROOT / "infra" / "services" / "core-control-plane" / "main.tf").read_text(
        encoding="utf-8"
    )
    assert any(line.split() == ["llm", "=", "var.llm"] for line in core_root.splitlines())
    assert "phase_timeout_seconds = 75" in core_variables
    assert (
        "phase_timeout_seconds > var.startup_readiness.probe_timeout_seconds * 2" in core_variables
    )


def test_all_service_roots_require_non_empty_database_host(contract: ModuleType) -> None:
    for service in contract.load_matrix()["services"]:
        variables = (_ROOT / "infra" / "services" / service / "variables.tf").read_text(
            encoding="utf-8"
        )
        assert "host = optional(string" not in variables
        assert "host          = optional(string" not in variables
        assert 'condition     = trimspace(var.database.host) != ""' in variables
        assert (
            'error_message = "database.host must contain the non-secret PostgreSQL endpoint '
            'identity."' in variables
        )


def test_unknown_service_and_environment_fail_closed(contract: ModuleType) -> None:
    with pytest.raises(contract.ServiceContractError, match="five independent"):
        contract.resolve_service("platform", "dev")
    with pytest.raises(contract.ServiceContractError, match="environment"):
        contract.resolve_service("core-control-plane", "preview")


def test_image_reference_is_service_specific_and_digest_pinned(contract: ModuleType) -> None:
    resolved = contract.resolve_service("operator-service", "dev")
    image = _image("fdai-operator-service")
    digest = contract.validate_image_reference(resolved, "example/fdai", image)
    assert digest == f"sha256:{'a' * 64}"
    with pytest.raises(contract.ServiceContractError, match="selected service"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            _image("fdai-core-control-plane"),
        )
    with pytest.raises(contract.ServiceContractError, match="sha256"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            image.rsplit("@", 1)[0] + "@latest",
        )


def test_plan_guard_allows_only_selected_service_image_update_or_noop(
    guard: ModuleType,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    for action in ("update", "no-op"):
        guard.validate_plan(
            _plan(address, [action]),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )

    with pytest.raises(guard.PlanGuardError, match="creation has no automatic recovery"):
        guard.validate_plan(
            _plan(address, ["create"]),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_exact_operator_channel_edge_enable(guard: ModuleType) -> None:
    guard.validate_plan(
        _channel_edge_enable_plan(),
        service="operator-service",
        environment="dev",
        image_ref="image",
        operator_channel_edge_transition="enable",
    )


def test_plan_guard_allows_operator_channel_edge_image_update(guard: ModuleType) -> None:
    guard.validate_plan(
        _channel_edge_update_plan(),
        service="operator-service",
        environment="dev",
        image_ref="image",
    )


def test_plan_guard_allows_exact_operator_channel_edge_disable(guard: ModuleType) -> None:
    guard.validate_plan(
        _channel_edge_disable_plan(),
        service="operator-service",
        environment="dev",
        image_ref="image",
        operator_channel_edge_transition="disable",
    )


def test_plan_guard_rejects_implicit_or_partial_operator_channel_edge_enable(
    guard: ModuleType,
) -> None:
    with pytest.raises(guard.PlanGuardError, match="explicit none"):
        guard.validate_plan(
            _channel_edge_enable_plan(),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )

    partial = _channel_edge_enable_plan()
    partial["resource_changes"] = partial["resource_changes"][1:]  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="enable plan is incomplete"):
        guard.validate_plan(
            partial,
            service="operator-service",
            environment="dev",
            image_ref="image",
            operator_channel_edge_transition="enable",
        )


def test_plan_guard_rejects_authority_bearing_operator_channel_edge(guard: ModuleType) -> None:
    plan = _channel_edge_enable_plan()
    environment = plan["resource_changes"][1]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    environment.append({"name": "FDAI_COMMAND_MI_CLIENT_ID", "value": "command"})

    with pytest.raises(guard.PlanGuardError, match="grants execution authority"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            operator_channel_edge_transition="enable",
        )


def test_plan_guard_rejects_operator_channel_edge_transition_for_other_service(
    guard: ModuleType,
) -> None:
    with pytest.raises(guard.PlanGuardError, match="only for operator-service"):
        guard.validate_plan(
            _channel_edge_enable_plan(),
            service="core-control-plane",
            environment="dev",
            image_ref="image",
            operator_channel_edge_transition="enable",
        )


def test_plan_guard_allows_worker_primary_image_update_with_exact_clamav_sidecar(
    guard: ModuleType,
) -> None:
    guard.validate_plan(
        _worker_plan(),
        service="document-processing-worker",
        environment="dev",
        image_ref="image",
    )


def test_plan_guard_rejects_unknown_worker_sidecar(guard: ModuleType) -> None:
    plan = _worker_plan()
    for side in ("before", "after"):
        containers = plan["resource_changes"][0]["change"][side]["template"][0][  # type: ignore[index]
            "container"
        ]
        containers.append(  # type: ignore[union-attr]
            {
                "name": "unknown",
                "image": "docker.io/example/unknown@sha256:" + "c" * 64,
            }
        )
    with pytest.raises(guard.PlanGuardError, match="exact allowed sidecar set"):
        guard.validate_plan(
            plan,
            service="document-processing-worker",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_mutable_worker_sidecar(guard: ModuleType) -> None:
    plan = _worker_plan()
    for side in ("before", "after"):
        sidecar = plan["resource_changes"][0]["change"][side]["template"][0][  # type: ignore[index]
            "container"
        ][1]
        sidecar["image"] = "docker.io/clamav/clamav:latest"
    with pytest.raises(guard.PlanGuardError, match="sidecar clamav image is not immutable"):
        guard.validate_plan(
            plan,
            service="document-processing-worker",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_changed_worker_sidecar(guard: ModuleType) -> None:
    plan = _worker_plan()
    sidecar = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][1]
    sidecar["image"] = "docker.io/clamav/clamav@sha256:" + "c" * 64
    with pytest.raises(guard.PlanGuardError, match="sidecar contract drift"):
        guard.validate_plan(
            plan,
            service="document-processing-worker",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"], ["create", "delete"]])
def test_plan_guard_rejects_delete_and_replacement(guard: ModuleType, actions: list[str]) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="delete or replacement"):
        guard.validate_plan(
            _plan(address, actions),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_platform_and_other_service_actions(guard: ModuleType) -> None:
    for address in (
        "azurerm_resource_group.platform",
        "module.core_control_plane.module.container_app.azurerm_container_app.service",
    ):
        with pytest.raises(guard.PlanGuardError, match="cross-service or platform"):
            guard.validate_plan(
                _plan(address, ["update"]),
                service="operator-service",
                environment="dev",
                image_ref="image",
            )


def test_plan_guard_rejects_image_substitution(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="attested image"):
        guard.validate_plan(
            _plan(address, ["update"], image="mutable:latest"),
            service="operator-service",
            environment="dev",
            image_ref="ghcr.io/example/fdai/fdai-operator-service@sha256:" + "a" * 64,
        )


def test_plan_guard_rejects_untrusted_runtime_on_update(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    container["command"] = ["python"]
    container["env"] = [{"name": "RUNTIME_ENV", "value": "dev"}]
    with pytest.raises(guard.PlanGuardError, match="service entrypoint.*missing required"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("name", "peer-service", "target resource identity"),
        ("resource_group_name", "peer-platform", "target resource identity"),
        (
            "container_app_environment_id",
            "/subscriptions/example/resourceGroups/example/providers/Microsoft.App/"
            "managedEnvironments/peer",
            "platform or peer resource identity",
        ),
    ],
)
def test_plan_guard_rejects_target_or_platform_identity_drift(
    guard: ModuleType,
    field: str,
    replacement: str,
    message: str,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_changes"][0]["change"]["after"][field] = replacement  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match=message):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_names_changed_environment_without_exposing_values(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    next(item for item in after_environment if item["name"] == "POSTGRES_HOST")["value"] = (
        "changed.example.com"
    )

    with pytest.raises(guard.PlanGuardError, match="env:POSTGRES_HOST") as error:
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )
    assert "changed.example.com" not in str(error.value)


def test_plan_guard_rejects_identity_expansion(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    identity_ids = plan["resource_changes"][0]["change"]["after"]["identity"][0][  # type: ignore[index]
        "identity_ids"
    ]
    identity_ids.append(
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/executor"
    )
    with pytest.raises(guard.PlanGuardError, match="identity expansion"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize(
    ("runtime_field", "message"),
    [("command", "command"), ("args", "command"), ("env", "environment")],
)
def test_plan_guard_rejects_command_and_environment_drift(
    guard: ModuleType,
    runtime_field: str,
    message: str,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    container[runtime_field] = ["unexpected"]
    with pytest.raises(guard.PlanGuardError, match=message):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_ignores_primary_environment_block_order(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.reverse()

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )


def test_plan_guard_allows_exact_database_host_binding(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    _remove_environment_binding(plan, "POSTGRES_HOST")
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.append({"name": "POSTGRES_HOST", "value": "db.example.com"})

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
        database_host_binding=True,
    )

    with pytest.raises(guard.PlanGuardError, match="command or environment drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_only_explicit_sharepoint_connector_transition(
    guard: ModuleType,
) -> None:
    plan = _document_ingestion_plan(guard)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.extend(_sharepoint_connector_environment())

    guard.validate_plan(
        plan,
        service="document-ingestion-api",
        environment="dev",
        image_ref="image",
        sharepoint_connector_transition="enable",
    )

    with pytest.raises(guard.PlanGuardError, match="command or environment drift"):
        guard.validate_plan(
            plan,
            service="document-ingestion-api",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_unrelated_sharepoint_transition_drift(guard: ModuleType) -> None:
    plan = _document_ingestion_plan(guard)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.extend(_sharepoint_connector_environment())
    after_environment[0]["value"] = "changed"

    with pytest.raises(guard.PlanGuardError, match="unrelated environment drift"):
        guard.validate_plan(
            plan,
            service="document-ingestion-api",
            environment="dev",
            image_ref="image",
            sharepoint_connector_transition="enable",
        )


def test_plan_guard_allows_exact_sharepoint_connector_disable(guard: ModuleType) -> None:
    plan = _document_ingestion_plan(guard)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    change["before"]["template"][0]["container"][0]["env"].extend(  # type: ignore[index]
        _sharepoint_connector_environment()
    )

    guard.validate_plan(
        plan,
        service="document-ingestion-api",
        environment="dev",
        image_ref="image",
        sharepoint_connector_transition="disable",
    )


def test_plan_guard_rejects_broad_sharepoint_download_suffix(guard: ModuleType) -> None:
    plan = _document_ingestion_plan(guard)
    environment = _sharepoint_connector_environment()
    next(item for item in environment if item["name"] == "FDAI_SHAREPOINT_DOWNLOAD_HOST_SUFFIXES")[
        "value"
    ] = ".com"
    plan["resource_changes"][0]["change"]["after"]["template"][0]["container"][0][  # type: ignore[index]
        "env"
    ].extend(environment)

    with pytest.raises(guard.PlanGuardError, match="bindings are invalid"):
        guard.validate_plan(
            plan,
            service="document-ingestion-api",
            environment="dev",
            image_ref="image",
            sharepoint_connector_transition="enable",
        )


def test_plan_guard_allows_exact_core_notification_receipt_topic_addition(
    guard: ModuleType,
) -> None:
    service = "core-control-plane"
    plan = _core_model_binding_plan(guard, "a" * 64)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    after_environment = change["after"]["template"][0]["container"][0]["env"]
    change["before"]["template"][0]["container"][0]["env"] = copy.deepcopy(after_environment)
    after_environment.append(
        {
            "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
            "value": "fdai.notifications.delivery-receipts",
        }
    )
    after_environment.reverse()

    guard.validate_plan(
        plan,
        service=service,
        environment="dev",
        image_ref="image",
    )

    after_environment[-1]["value"] = "unreviewed.topic"
    with pytest.raises(guard.PlanGuardError, match="command or environment drift"):
        guard.validate_plan(
            plan,
            service=service,
            environment="dev",
            image_ref="image",
        )


def _core_model_binding_plan(guard: ModuleType, digest: str) -> dict[str, object]:
    service = "core-control-plane"
    address = "module.core_control_plane.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    contract = guard.resolve_service(service, "dev")
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    for side in ("before", "after"):
        resource = change[side]
        resource["tags"] = {"fdai:component": service}
        container = resource["template"][0]["container"][0]
        container["command"] = [contract.entrypoint]
        container["env"] = [
            {"name": name, "value": "value"} for name in contract.required_environment
        ]
    for name in (
        "LLM_MODE",
        "LLM_RESOLVED_MODELS_PATH",
        "LLM_RESOLVED_MODELS_SHA256",
    ):
        _remove_environment_binding(plan, name)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    model_values = {
        "FDAI_LLM_ENDPOINT": "https://oai-fdai.openai.azure.com",
        "FDAI_WEB_SEARCH_ALLOWED_DOMAINS": "",
        "FDAI_WEB_SEARCH_ENABLED": "false",
        "FDAI_WEB_SEARCH_MAX_RESULTS": "8",
        "FDAI_WEB_SEARCH_TIMEOUT_SECONDS": "45",
    }
    for side in ("before", "after"):
        environment = change[side]["template"][0]["container"][0]["env"]
        for name, value in model_values.items():
            next(item for item in environment if item["name"] == name)["value"] = value
    after_environment.extend(
        (
            {
                "name": "FDAI_MODEL_ENDPOINTS_JSON",
                "value": '{"azure-openai:oai-fdai":"https://oai-fdai.openai.azure.com"}',
            },
            {"name": "LLM_MODE", "value": "azure"},
            {"name": "LLM_RESOLVED_MODELS_PATH", "value": "/app/resolved-models.json"},
            {"name": "LLM_RESOLVED_MODELS_SHA256", "value": digest},
        )
    )
    return plan


def test_plan_guard_allows_exact_core_model_binding_transition(guard: ModuleType) -> None:
    service = "core-control-plane"
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)

    guard.validate_plan(
        plan,
        service=service,
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )

    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.append({"name": "UNREVIEWED", "value": "changed"})
    with pytest.raises(guard.PlanGuardError, match="unapproved environment"):
        guard.validate_plan(
            plan,
            service=service,
            environment="dev",
            image_ref="image",
            model_binding_transition=True,
            resolved_models_digest=digest,
        )


def test_plan_guard_composes_model_and_notification_topic_transitions(
    guard: ModuleType,
) -> None:
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before_environment = change["before"]["template"][0]["container"][0]["env"]
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    for name in ("LLM_MODE", "LLM_RESOLVED_MODELS_PATH", "LLM_RESOLVED_MODELS_SHA256"):
        before_environment.append(
            copy.deepcopy(next(item for item in after_environment if item["name"] == name))
        )
    after_environment.append(
        {
            "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
            "value": "fdai.notifications.delivery-receipts",
        }
    )

    guard.validate_plan(
        plan,
        service="core-control-plane",
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )


def test_plan_guard_composes_model_and_notification_topic_correction(
    guard: ModuleType,
) -> None:
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before_environment = change["before"]["template"][0]["container"][0]["env"]
    after_environment = change["after"]["template"][0]["container"][0]["env"]
    before_environment.append(
        {
            "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
            "value": "fdai.notifications.legacy-receipts",
        }
    )
    after_environment.append(
        {
            "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
            "value": "fdai.notifications.delivery-receipts",
        }
    )

    guard.validate_plan(
        plan,
        service="core-control-plane",
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )


def test_plan_guard_model_binding_validates_canonical_topic_independently(
    guard: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.append(
        {
            "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
            "value": "fdai.notifications.delivery-receipts",
        }
    )
    monkeypatch.setattr(
        guard,
        "_only_notification_receipt_topic_transition",
        lambda *_args, **_kwargs: False,
    )

    guard.validate_plan(
        plan,
        service="core-control-plane",
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )


def test_plan_guard_allows_exact_hydrated_rca_reader_identity(guard: ModuleType) -> None:
    service = "core-control-plane"
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    identity_ids = change["after"]["identity"][0]["identity_ids"]
    identity_ids.append(
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-dev-rca-reader"
    )
    environment = change["after"]["template"][0]["container"][0]["env"]
    environment.append(
        {
            "name": "FDAI_RCA_AZURE_READER_CLIENT_ID",
            "value": "00000000-0000-0000-0000-000000000001",
        }
    )

    guard.validate_plan(
        plan,
        service=service,
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )


def test_plan_guard_composes_model_notification_and_rca_reader_transitions(
    guard: ModuleType,
) -> None:
    service = "core-control-plane"
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    change["after"]["identity"][0]["identity_ids"].append(
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-dev-rca-reader"
    )
    change["after"]["template"][0]["container"][0]["env"].extend(
        (
            {
                "name": "FDAI_NOTIFICATION_RECEIPT_TOPIC",
                "value": "fdai.notifications.delivery-receipts",
            },
            {
                "name": "FDAI_RCA_AZURE_READER_CLIENT_ID",
                "value": "00000000-0000-0000-0000-000000000001",
            },
        )
    )

    guard.validate_plan(
        plan,
        service=service,
        environment="dev",
        image_ref="image",
        model_binding_transition=True,
        resolved_models_digest=digest,
    )


def test_plan_guard_rejects_model_binding_digest_mismatch(guard: ModuleType) -> None:
    service = "core-control-plane"
    plan = _core_model_binding_plan(guard, "b" * 64)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    assert any(item["name"] == "LLM_RESOLVED_MODELS_SHA256" for item in after_environment)

    with pytest.raises(guard.PlanGuardError, match="invalid environment"):
        guard.validate_plan(
            plan,
            service=service,
            environment="dev",
            image_ref="image",
            model_binding_transition=True,
            resolved_models_digest="a" * 64,
        )


def test_plan_guard_allows_operator_runtime_bindings_with_database_host(
    guard: ModuleType,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    expected = {
        "FDAI_HIL_DECISION_TOPIC": "fdai.hil.decisions",
        "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC": ("operator.incident-intervention.requests"),
        "FDAI_NOTIFICATION_RECEIPT_TOPIC": "fdai.notifications.delivery-receipts",
        "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID": (
            "operator-read-investigation-completion-v1"
        ),
        "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC": ("core.read-investigation.completions"),
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests"),
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
    }
    for name in ("POSTGRES_HOST", *expected):
        _remove_environment_binding(plan, name)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.append({"name": "POSTGRES_HOST", "value": "db.example.com"})
    after_environment.extend({"name": name, "value": value} for name, value in expected.items())

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
        database_host_binding=True,
    )

    next(item for item in after_environment if item["name"] == "FDAI_SEMANTIC_TURN_REQUEST_TOPIC")[
        "value"
    ] = "unreviewed.topic"
    with pytest.raises(guard.PlanGuardError, match="unapproved environment"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            database_host_binding=True,
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FDAI_LLM_ENDPOINT", "http://models.example.com"),
        ("FDAI_LLM_ENDPOINT", "https://user@models.example.com"),
        ("FDAI_MODEL_ENDPOINTS_JSON", "not-json"),
        (
            "FDAI_MODEL_ENDPOINTS_JSON",
            '{"azure-foundry:wrong":"https://aif-fdai.services.ai.azure.com"}',
        ),
        ("FDAI_WEB_SEARCH_ALLOWED_DOMAINS", "learn.example.com/path"),
        ("FDAI_WEB_SEARCH_ENABLED", "enabled"),
        ("FDAI_WEB_SEARCH_MAX_RESULTS", "21"),
        ("FDAI_WEB_SEARCH_TIMEOUT_SECONDS", "91"),
    ],
)
def test_plan_guard_rejects_invalid_model_environment(
    guard: ModuleType,
    name: str,
    value: str,
) -> None:
    digest = "a" * 64
    plan = _core_model_binding_plan(guard, digest)
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    next(item for item in after_environment if item["name"] == name)["value"] = value

    with pytest.raises(guard.PlanGuardError, match="invalid environment"):
        guard.validate_plan(
            plan,
            service="core-control-plane",
            environment="dev",
            image_ref="image",
            model_binding_transition=True,
            resolved_models_digest=digest,
        )


@pytest.mark.parametrize(
    "host_binding",
    [
        {"name": "POSTGRES_HOST", "value": ""},
        {"name": "POSTGRES_HOST", "value": "   "},
        {"name": "POSTGRES_HOST", "secret_name": "database-host"},
    ],
)
def test_plan_guard_rejects_invalid_database_host_binding(
    guard: ModuleType,
    host_binding: dict[str, str],
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    _remove_environment_binding(plan, "POSTGRES_HOST")
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.append(host_binding)

    with pytest.raises(guard.PlanGuardError, match="database host binding is invalid"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            database_host_binding=True,
        )


def test_plan_guard_rejects_unrelated_database_host_environment_drift(
    guard: ModuleType,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    _remove_environment_binding(plan, "POSTGRES_HOST")
    after_environment = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]["env"]
    after_environment.extend(
        (
            {"name": "POSTGRES_HOST", "value": "db.example.com"},
            {"name": "UNREVIEWED", "value": "changed"},
        )
    )

    with pytest.raises(guard.PlanGuardError, match="unapproved environment"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            database_host_binding=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workload_profile_name", "Dedicated-D4"),
        ("revision_mode", "Multiple"),
        ("max_inactive_revisions", 50),
        ("ingress", [{"external_enabled": True}]),
        ("secret", [{"name": "replacement", "value": "not-a-secret"}]),
        ("registry", [{"server": "peer.example.com", "identity": "system"}]),
        ("tags", {"fdai:component": "operator-service", "mutable": "changed"}),
    ],
)
def test_plan_guard_rejects_fields_rollback_cannot_prove(
    guard: ModuleType,
    field: str,
    value: object,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_changes"][0]["change"]["after"][field] = value  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="rollback cannot prove"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_only_minimum_rollback_revision_retention(
    guard: ModuleType,
) -> None:
    plan = _plan(
        "module.operator_service.module.container_app.azurerm_container_app.service",
        ["update"],
    )
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    change["after"]["max_inactive_revisions"] = 1

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )

    for unsupported in (0, 2, 50):
        changed = copy.deepcopy(plan)
        changed_change = changed["resource_changes"][0]["change"]  # type: ignore[index]
        changed_change["before"]["max_inactive_revisions"] = 1
        changed_change["after"]["max_inactive_revisions"] = unsupported
        with pytest.raises(guard.PlanGuardError, match="rollback revision retention drift"):
            guard.validate_plan(
                changed,
                service="operator-service",
                environment="dev",
                image_ref="image",
            )


def test_plan_guard_rejects_authority_cutover_change(guard: ModuleType) -> None:
    address = "module.isolated_executor.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    before_container = plan["resource_changes"][0]["change"]["before"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    after_container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    before_container["env"].append(  # type: ignore[union-attr]
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "0"}
    )
    after_container["env"].append(  # type: ignore[union-attr]
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "1"}
    )
    with pytest.raises(guard.PlanGuardError, match="authority cutover"):
        guard.validate_plan(
            plan,
            service="isolated-executor",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_bounded_initial_runtime_cutover(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    before_container = before["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/operator@sha256:" + "b" * 64
    before_container["command"] = ["legacy-operator"]
    before_container["env"].append({"name": "LEGACY_OPTIONAL", "value": "enabled"})
    after["template"][0]["revision_suffix"] = "p20260817033542"
    before["tags"] = {}
    after["tags"] = {
        "fdai:component": "operator-service",
        "fdai:rollback-strategy": "previous-revision",
    }

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )
    with pytest.raises(guard.PlanGuardError, match="command or environment drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_initial_cutover_rejects_invalid_revision_suffix(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    before_container = before["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/operator@sha256:" + "b" * 64
    before_container["command"] = ["legacy-operator"]
    before["tags"] = {}
    after["tags"] = {
        "fdai:component": "operator-service",
        "fdai:rollback-strategy": "previous-revision",
    }
    after["template"][0]["revision_suffix"] = "INVALID_SUFFIX"

    with pytest.raises(guard.PlanGuardError, match="revision suffix is invalid"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_initial_cutover_rejects_changes_outside_runtime_rollback_boundary(
    guard: ModuleType,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    before_container = before["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/operator@sha256:" + "b" * 64
    before_container["command"] = ["legacy-operator"]
    before["tags"] = {}
    after["tags"] = {
        "fdai:component": "operator-service",
        "fdai:rollback-strategy": "previous-revision",
    }
    after["revision_mode"] = "Multiple"
    with pytest.raises(guard.PlanGuardError, match="outside its rollback boundary"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_initial_cutover_rejects_executor_authority_change(guard: ModuleType) -> None:
    address = "module.isolated_executor.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    before_container = before["template"][0]["container"][0]
    after_container = after["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/executor@sha256:" + "b" * 64
    before_container["command"] = ["legacy-executor"]
    before_container["env"].append(
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "0"}
    )
    after_container["env"].append(
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "1"}
    )
    before["tags"] = {}
    after["tags"] = {
        "fdai:component": "isolated-executor",
        "fdai:rollback-strategy": "previous-revision",
    }
    with pytest.raises(guard.PlanGuardError, match="authority cutover"):
        guard.validate_plan(
            plan,
            service="isolated-executor",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_initial_cutover_allows_only_resource_reference_removal(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    before_container = before["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/operator@sha256:" + "b" * 64
    before_container["command"] = ["legacy-operator"]
    before_container["env"].append(
        {
            "name": "LEGACY_RESOURCE",
            "value": "/subscriptions/example/resourceGroups/example/providers/example/legacy",
        }
    )
    before["tags"] = {}
    after["tags"] = {
        "fdai:component": "operator-service",
        "fdai:rollback-strategy": "previous-revision",
    }
    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )
    after["peer_id"] = "/subscriptions/example/resourceGroups/example/providers/example/new-peer"
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource identity"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_initial_cutover_allows_aligned_executor_authority_tag(guard: ModuleType) -> None:
    address = "module.isolated_executor.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    after = change["after"]
    contract = guard.resolve_service("isolated-executor", "dev")
    after_container = after["template"][0]["container"][0]
    after_container["command"] = [contract.entrypoint]
    after_container["env"] = [
        {
            "name": name,
            "value": "1" if name == "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER" else "value",
        }
        for name in contract.required_environment
    ]
    after["tags"] = {
        "fdai:component": "isolated-executor",
        "fdai:rollback-strategy": "previous-revision",
        "fdai:authority-cutover": "true",
    }
    before_container = before["template"][0]["container"][0]
    before_container.clear()
    before_container.update(copy.deepcopy(after_container))
    before_container["image"] = "registry.example.com/executor@sha256:" + "b" * 64
    before_container["command"] = ["legacy-executor"]
    before["tags"] = {}
    guard.validate_plan(
        plan,
        service="isolated-executor",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )


def test_initial_cutover_allows_exact_clamav_tag_normalization_drift(
    guard: ModuleType,
) -> None:
    plan = _worker_plan()
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    planned_sidecar = change["after"]["template"][0]["container"][1]
    drift_before = copy.deepcopy(change["before"])
    drift_after = copy.deepcopy(drift_before)
    drift_before["template"][0]["container"][1]["image"] = "clamav/clamav:stable"
    drift_after["template"][0]["container"][1]["image"] = planned_sidecar["image"]
    drift_after["template"][0]["revision_suffix"] = "normalized"
    drift_after["latest_revision_name"] = "worker--normalized"
    plan["resource_drift"] = [
        {
            "address": (
                "module.document_processing_worker.module.container_app."
                "azurerm_container_app.service"
            ),
            "change": {
                "actions": ["update"],
                "before": drift_before,
                "after": drift_after,
            },
        }
    ]
    before = change["before"]
    before["template"][0]["container"][0]["image"] = (
        "registry.example.com/worker@sha256:" + "d" * 64
    )
    before["template"][0]["container"][0]["command"] = ["legacy-worker"]
    before_sidecar = before["template"][0]["container"][1]
    before_sidecar.pop("startup_probe")
    before_sidecar.pop("liveness_probe")
    before_sidecar.pop("readiness_probe")
    before["tags"] = {}
    change["after"]["tags"] = {
        "fdai:component": "document-processing-worker",
        "fdai:rollback-strategy": "previous-revision",
    }
    guard.validate_plan(
        plan,
        service="document-processing-worker",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )
    plan["resource_drift"][0]["change"]["after"]["identity"] = []  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="document-processing-worker",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_initial_worker_cutover_allows_revision_name_only_drift(guard: ModuleType) -> None:
    plan = _worker_plan()
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = copy.deepcopy(change["before"])
    after = copy.deepcopy(before)
    after["latest_revision_name"] = "worker--normalized"
    plan["resource_drift"] = [
        {
            "address": (
                "module.document_processing_worker.module.container_app."
                "azurerm_container_app.service"
            ),
            "change": {"actions": ["update"], "before": before, "after": after},
        }
    ]
    change["before"]["template"][0]["container"][0]["image"] = (
        "registry.example.com/worker@sha256:" + "d" * 64
    )
    change["before"]["template"][0]["container"][0]["command"] = ["legacy-worker"]
    before_sidecar = change["before"]["template"][0]["container"][1]
    before_sidecar.pop("startup_probe")
    before_sidecar.pop("liveness_probe")
    before_sidecar.pop("readiness_probe")
    change["before"]["tags"] = {}
    change["after"]["tags"] = {
        "fdai:component": "document-processing-worker",
        "fdai:rollback-strategy": "previous-revision",
    }
    guard.validate_plan(
        plan,
        service="document-processing-worker",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )


def test_plan_guard_reports_drift_paths_without_values(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_drift"] = [
        {
            "address": address,
            "change": {
                "actions": ["update"],
                "before": {"identity": {"client_id": "secret-old"}},
                "after": {"identity": {"client_id": "secret-new"}},
            },
        }
    ]
    with pytest.raises(guard.PlanGuardError) as error:
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )
    message = str(error.value)
    assert "$.identity.client_id" in message
    assert "secret-old" not in message
    assert "secret-new" not in message


def test_plan_guard_allows_only_empty_key_vault_secret_value_normalization(
    guard: ModuleType,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    planned_before = plan["resource_changes"][0]["change"]["before"]  # type: ignore[index]
    drift_before = copy.deepcopy(planned_before)
    drift_after = copy.deepcopy(planned_before)
    drift_before["secret"][0]["value"] = ""  # type: ignore[index]
    plan["resource_drift"] = [
        {
            "address": address,
            "change": {"actions": ["update"], "before": drift_before, "after": drift_after},
        }
    ]

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )

    drift_before["secret"][0]["value"] = "not-empty"  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )
    drift_before["secret"][0]["value"] = ""  # type: ignore[index]
    drift_after["secret"][0]["identity"] = "changed"  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_only_recovery_revision_metadata_drift(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    before = copy.deepcopy(plan["resource_changes"][0]["change"]["before"])  # type: ignore[index]
    after = copy.deepcopy(before)
    before["latest_revision_name"] = "service--rollback"
    after["latest_revision_name"] = "service--planned"
    before["latest_revision_fqdn"] = "rollback.example.com"
    after["latest_revision_fqdn"] = "planned.example.com"
    before["template"][0]["revision_suffix"] = "rollback"  # type: ignore[index]
    after["template"][0]["revision_suffix"] = "planned"  # type: ignore[index]
    plan["resource_drift"] = [
        {"address": address, "change": {"actions": ["update"], "before": before, "after": after}}
    ]

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )

    after["template"][0]["container"][0]["command"] = ["changed"]  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_recovery_image_aligned_to_attested_plan(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"], image="image")
    planned_before = plan["resource_changes"][0]["change"]["before"]  # type: ignore[index]
    planned_before["template"][0]["container"][0]["image"] = "image"  # type: ignore[index]
    before = copy.deepcopy(planned_before)
    after = copy.deepcopy(planned_before)
    before["latest_revision_name"] = "service--terraform-stale"
    after["latest_revision_name"] = "service--recovered"
    before["latest_revision_fqdn"] = "stale.example.com"
    after["latest_revision_fqdn"] = "recovered.example.com"
    before["template"][0]["revision_suffix"] = "terraform-stale"  # type: ignore[index]
    after["template"][0]["revision_suffix"] = "recovered"  # type: ignore[index]
    before["template"][0]["container"][0]["image"] = "old-image"  # type: ignore[index]
    plan["resource_drift"] = [
        {"address": address, "change": {"actions": ["update"], "before": before, "after": after}}
    ]

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )

    after["template"][0]["container"][0]["image"] = "other-image"  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_allows_fresh_bounded_revision_suffix(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    after = plan["resource_changes"][0]["change"]["after"]  # type: ignore[index]
    after["template"][0]["revision_suffix"] = "p20260810041030"  # type: ignore[index]

    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
    )

    after["template"][0]["revision_suffix"] = "INVALID_SUFFIX"  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="revision suffix is invalid"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_shared_container_app_seals_fresh_plan_time_revision() -> None:
    assert (
        'revision_suffix = "p${formatdate("YYYYMMDDhhmmss", plantimestamp())}"'
        in _SHARED_CONTAINER_APP_TERRAFORM
    )


def test_initial_cutover_allows_drift_aligned_with_planned_before(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    change = plan["resource_changes"][0]["change"]  # type: ignore[index]
    before = change["before"]
    before_container = before["template"][0]["container"][0]
    before_container["image"] = "registry.example.com/operator@sha256:" + "b" * 64
    before_container["command"] = ["legacy-operator"]
    before["tags"] = {}
    change["after"]["tags"] = {  # type: ignore[index]
        "fdai:component": "operator-service",
        "fdai:rollback-strategy": "previous-revision",
    }
    plan["resource_drift"] = [
        {
            "address": address,
            "change": {
                "actions": ["update"],
                "before": copy.deepcopy(change["after"]),
                "after": copy.deepcopy(before),
            },
        }
    ]
    guard.validate_plan(
        plan,
        service="operator-service",
        environment="dev",
        image_ref="image",
        initial_cutover=True,
    )
    plan["resource_drift"][0]["change"]["after"]["name"] = "peer"  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
            initial_cutover=True,
        )


def test_plan_guard_rejects_refreshed_platform_or_peer_drift(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_drift"] = [
        {
            "address": "module.platform.azurerm_container_app_environment.shared",
            "change": {"actions": ["update"]},
        }
    ]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_tfvars_selects_one_service_and_reserves_image(tfvars: ModuleType, tmp_path: Path) -> None:
    payload = {"environments": {"dev": {"operator-service": {"name": "example"}}}}
    selected = tfvars.select_tfvars(payload, service="operator-service", environment="dev")
    output = tmp_path / "service.tfvars.json"
    tfvars.write_tfvars(output, selected)
    assert json.loads(output.read_text(encoding="utf-8")) == {"name": "example"}
    assert output.stat().st_mode & 0o777 == 0o600
    payload["environments"]["dev"]["operator-service"]["image"] = "mutable"
    with pytest.raises(tfvars.TfvarsError, match="must not set image"):
        tfvars.select_tfvars(payload, service="operator-service", environment="dev")


def test_tfvars_derives_disabled_operator_channel_edge_without_mutating_source(
    tfvars: ModuleType,
) -> None:
    payload = {
        "environments": {
            "dev": {
                "operator-service": {
                    "name": "example",
                    "channel_edge": {
                        "enabled": True,
                        "principal_scopes_secret_id": "secret-reference",
                    },
                }
            }
        }
    }

    selected = tfvars.select_tfvars(
        payload,
        service="operator-service",
        environment="dev",
        operator_channel_edge_enabled=False,
    )

    assert selected["channel_edge"]["enabled"] is False
    assert selected["channel_edge"]["principal_scopes_secret_id"] == "secret-reference"
    assert payload["environments"]["dev"]["operator-service"]["channel_edge"]["enabled"] is True


def test_state_migration_resolves_exact_source_and_destination(
    migration: ModuleType,
) -> None:
    source_key, destination_key, source, destination = migration.migration_coordinates(
        "operator-service", "staging"
    )
    assert source_key == "fdai-staging.tfstate"
    assert destination_key == "services/operator-service/staging.tfstate"
    assert source == "module.operator_api[0].azurerm_container_app.operator_api"
    assert destination == (
        "module.operator_service.module.container_app.azurerm_container_app.service"
    )


def _peer_raw_state(
    *, serial: int = 1, sensitive_value: str = "not-for-receipt"
) -> dict[str, object]:
    return {
        "version": 4,
        "terraform_version": "1.9.0",
        "serial": serial,
        "lineage": "example-lineage",
        "outputs": {"sensitive": {"value": sensitive_value, "sensitive": True, "type": "string"}},
        "resources": [
            {
                "mode": "managed",
                "type": "azurerm_container_app",
                "name": "service",
                "instances": [{"attributes": {"id": "/synthetic/service"}}],
            }
        ],
    }


def _capture_peer_manifest(
    peer_state: ModuleType,
    tmp_path: Path,
    *,
    phase: str,
    changed_service: str | None = None,
) -> dict[str, object]:
    state_dir = tmp_path / phase
    state_dir.mkdir()
    for coordinate in peer_state.peer_coordinates("operator-service", "dev"):
        serial = 2 if coordinate.service == changed_service else 1
        (state_dir / f"{coordinate.service}.json").write_text(
            json.dumps(_peer_raw_state(serial=serial)), encoding="utf-8"
        )
    return peer_state.capture_manifest(
        selected_service="operator-service",
        environment="dev",
        phase=phase,
        state_dir=state_dir,
    )


def _capture_peer_manifest_from_states(
    peer_state: ModuleType,
    tmp_path: Path,
    *,
    phase: str,
    states: dict[str, dict[str, object]],
) -> dict[str, object]:
    state_dir = tmp_path / phase
    state_dir.mkdir()
    for coordinate in peer_state.peer_coordinates("operator-service", "dev"):
        (state_dir / f"{coordinate.service}.json").write_text(
            json.dumps(states[coordinate.service]), encoding="utf-8"
        )
    return peer_state.capture_manifest(
        selected_service="operator-service",
        environment="dev",
        phase=phase,
        state_dir=state_dir,
    )


def test_peer_state_capture_is_closed_and_redacts_raw_state(
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    coordinates = peer_state.peer_coordinates("operator-service", "dev")
    assert len(coordinates) == 4
    assert {coordinate.service for coordinate in coordinates} == {
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }

    manifest = _capture_peer_manifest(peer_state, tmp_path, phase="before")

    assert manifest["peer_count"] == 4
    encoded = json.dumps(manifest)
    assert "not-for-receipt" not in encoded
    assert "example-lineage" not in encoded
    assert all(peer["managed_resource_count"] == 1 for peer in manifest["peers"])


def test_peer_state_receipt_ignores_nonsemantic_state_serialization_changes(
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    services = {
        coordinate.service for coordinate in peer_state.peer_coordinates("operator-service", "dev")
    }
    before_states = {service: _peer_raw_state() for service in services}
    after_states = copy.deepcopy(before_states)
    core = after_states["core-control-plane"]
    core["outputs"] = {
        "other": {"value": "ignored", "sensitive": False, "type": "string"},
        **core["outputs"],
    }
    core["terraform_version"] = "1.15.6"
    before = _capture_peer_manifest_from_states(
        peer_state, tmp_path, phase="before", states=before_states
    )
    after = _capture_peer_manifest_from_states(
        peer_state, tmp_path, phase="after", states=after_states
    )

    receipt = peer_state.verify_peer_isolation(
        before=before,
        after=after,
        mode="plan",
        selected_service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="a" * 40,
        image_ref=_image("fdai-operator-service"),
        workflow_run_id="10",
        workflow_run_attempt="1",
        plan_run_id="10",
        plan_run_attempt="1",
        plan_digest="b" * 64,
        context_digest="c" * 64,
    )

    assert receipt["status"] == "verified"


def test_peer_state_receipt_rejects_managed_resource_identity_drift(
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    services = {
        coordinate.service for coordinate in peer_state.peer_coordinates("operator-service", "dev")
    }
    before_states = {service: _peer_raw_state() for service in services}
    after_states = copy.deepcopy(before_states)
    instance = after_states["core-control-plane"]["resources"][0]["instances"][0]
    instance["attributes"]["id"] = "/synthetic/replaced-service"
    before = _capture_peer_manifest_from_states(
        peer_state, tmp_path, phase="before", states=before_states
    )
    after = _capture_peer_manifest_from_states(
        peer_state, tmp_path, phase="after", states=after_states
    )

    with pytest.raises(
        peer_state.PeerStateError,
        match=r"core-control-plane \(managed_resource_identity_sha256=",
    ):
        peer_state.verify_peer_isolation(
            before=before,
            after=after,
            mode="plan",
            selected_service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="a" * 40,
            image_ref=_image("fdai-operator-service"),
            workflow_run_id="10",
            workflow_run_attempt="1",
            plan_run_id="10",
            plan_run_attempt="1",
            plan_digest="b" * 64,
            context_digest="c" * 64,
        )


def test_peer_state_receipt_binds_exact_plan_and_unchanged_peers(
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    before = _capture_peer_manifest(peer_state, tmp_path, phase="before")
    after = _capture_peer_manifest(peer_state, tmp_path, phase="after")

    receipt = peer_state.verify_peer_isolation(
        before=before,
        after=after,
        mode="plan",
        selected_service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="a" * 40,
        image_ref=_image("fdai-operator-service"),
        workflow_run_id="10",
        workflow_run_attempt="1",
        plan_run_id="10",
        plan_run_attempt="1",
        plan_digest="b" * 64,
        context_digest="c" * 64,
    )

    assert receipt["status"] == "verified"
    assert receipt["peer_count"] == 4
    assert receipt["plan_digest"] == "b" * 64


def test_live_observations_require_verified_apply_and_distinct_kind_evidence(
    live_observation: ModuleType,
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    before = _capture_peer_manifest(peer_state, tmp_path, phase="before")
    after = _capture_peer_manifest(peer_state, tmp_path, phase="after")
    image_ref = _image("fdai-operator-service")
    receipt = peer_state.verify_peer_isolation(
        before=before,
        after=after,
        mode="apply",
        selected_service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="a" * 40,
        image_ref=image_ref,
        workflow_run_id="11",
        workflow_run_attempt="1",
        plan_run_id="10",
        plan_run_attempt="1",
        plan_digest="b" * 64,
        context_digest="c" * 64,
    )

    result = live_observation.build_observations(
        receipt,
        service_id="operator-service",
        commit_sha="a" * 40,
        image_ref=image_ref,
        workflow_run_id="11",
        workflow_run_attempt="1",
        plan_digest="b" * 64,
        context_digest="c" * 64,
    )

    observations = result["observations"]
    assert set(observations) == {
        "health",
        "identity",
        "image",
        "offset",
        "schema",
        "source",
        "topology",
    }
    assert all(value["observed"] is True for value in observations.values())
    assert len({value["verification"] for value in observations.values()}) == 7
    assert observations["offset"]["peer_serials"] == {
        "core-control-plane": 1,
        "document-ingestion-api": 1,
        "document-processing-worker": 1,
        "isolated-executor": 1,
    }

    receipt["mode"] = "plan"
    with pytest.raises(live_observation.LiveObservationError, match="verified apply"):
        live_observation.build_observations(
            receipt,
            service_id="operator-service",
            commit_sha="a" * 40,
            image_ref=image_ref,
            workflow_run_id="11",
            workflow_run_attempt="1",
            plan_digest="b" * 64,
            context_digest="c" * 64,
        )


def test_peer_state_receipt_rejects_any_peer_drift(
    peer_state: ModuleType,
    tmp_path: Path,
) -> None:
    before = _capture_peer_manifest(peer_state, tmp_path, phase="before")
    after = _capture_peer_manifest(
        peer_state,
        tmp_path,
        phase="after",
        changed_service="isolated-executor",
    )

    with pytest.raises(
        peer_state.PeerStateError,
        match=r"isolated-executor \(serial=1->2\)",
    ):
        peer_state.verify_peer_isolation(
            before=before,
            after=after,
            mode="apply",
            selected_service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="a" * 40,
            image_ref=_image("fdai-operator-service"),
            workflow_run_id="11",
            workflow_run_attempt="1",
            plan_run_id="10",
            plan_run_attempt="1",
            plan_digest="b" * 64,
            context_digest="c" * 64,
        )


def test_state_cutover_requires_source_zero_and_destination_exactly_once(
    migration: ModuleType,
) -> None:
    source = "legacy.service"
    destination = "independent.service"
    migration.verify_state_pair(
        _state(source),
        _state(),
        source_address=source,
        destination_address=destination,
        phase="pre",
    )
    migration.verify_state_pair(
        _state(),
        _state(destination),
        source_address=source,
        destination_address=destination,
        phase="post",
    )
    with pytest.raises(migration.StateMigrationError, match="source=1 and destination=0"):
        migration.verify_state_pair(
            _state(),
            _state(destination),
            source_address=source,
            destination_address=destination,
            phase="pre",
        )
    with pytest.raises(migration.StateMigrationError, match="source=0 and destination=1"):
        migration.verify_state_pair(
            _state(source),
            _state(destination),
            source_address=source,
            destination_address=destination,
            phase="post",
        )
    with pytest.raises(migration.StateMigrationError, match="destination=1"):
        migration.verify_state_pair(
            _state(),
            _state(destination, destination),
            source_address=source,
            destination_address=destination,
            phase="post",
        )


def test_state_cutover_rejects_alias_with_duplicate_physical_resource(
    migration: ModuleType,
) -> None:
    resource_id = (
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.App/containerApps/operator-service"
    )
    with pytest.raises(migration.StateMigrationError, match="duplicate physical resource"):
        migration.verify_state_pair(
            _state("legacy.alias", resource_id=resource_id),
            _state("independent.service", resource_id=resource_id),
            source_address="legacy.service",
            destination_address="independent.service",
            phase="post",
        )


def test_state_cutover_accepts_raw_v4_state_without_provider_schemas(
    migration: ModuleType,
) -> None:
    source = "module.compute.azurerm_container_app.core"
    destination = "module.core_control_plane.module.container_app.azurerm_container_app.service"
    resource_id = (
        "/subscriptions/example/resourceGroups/example/providers/Microsoft.App/containerApps/core"
    )
    source_state = {
        "version": 4,
        "resources": [
            {
                "module": "module.compute",
                "mode": "managed",
                "type": "azurerm_container_app",
                "name": "core",
                "instances": [{"attributes": {"id": resource_id}}],
            }
        ],
    }
    migration.verify_state_pair(
        source_state,
        {"version": 4, "resources": []},
        source_address=source,
        destination_address=destination,
        phase="pre",
    )


def test_state_migration_restores_both_backends_when_source_push_fails(
    migration: ModuleType,
    tmp_path: Path,
) -> None:
    source_address = "module.operator_api[0].azurerm_container_app.operator_api"
    destination_address = (
        "module.operator_service.module.container_app.azurerm_container_app.service"
    )
    resource_id = (
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.App/containerApps/operator-service"
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "source.json").write_text(
        json.dumps(_state(source_address, resource_id=resource_id)), encoding="utf-8"
    )
    (state_dir / "destination.json").write_text(json.dumps(_state()), encoding="utf-8")
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_terraform(fake_bin / "terraform")
    env = os.environ.copy()
    env["FAKE_STATE_DIR"] = str(state_dir)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    bash = shutil.which("bash")
    assert bash is not None

    result = subprocess.run(  # noqa: S603 - fixed script and synthetic arguments
        [
            bash,
            str(_SCRIPTS / "migrate_state.sh"),
            "operator-service",
            "dev",
            str(source_root),
            str(destination_root),
            str(tmp_path / "backups"),
            "--execute",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "state backups restored and single physical ownership verified" in result.stderr
    restored_source = json.loads((state_dir / "source.json").read_text(encoding="utf-8"))
    restored_destination = json.loads((state_dir / "destination.json").read_text(encoding="utf-8"))
    migration.verify_state_pair(
        restored_source,
        restored_destination,
        source_address=source_address,
        destination_address=destination_address,
        phase="pre",
    )
    calls = (state_dir / "calls.log").read_text(encoding="utf-8")
    assert f"-chdir={destination_root} state push -force" in calls
    assert f"-chdir={source_root} state push -force" in calls


def test_cutover_fence_rejects_legacy_runtime_recreation(migration: ModuleType) -> None:
    source = "module.operator_api[0].azurerm_container_app.operator_api"
    migration.guard_legacy_plan(
        {"resource_changes": [{"address": source, "change": {"actions": ["no-op"]}}]}
    )
    for actions in (["create"], ["update"], ["delete", "create"]):
        with pytest.raises(migration.StateMigrationError, match="legacy deploy cannot recreate"):
            migration.guard_legacy_plan(
                {"resource_changes": [{"address": source, "change": {"actions": actions}}]}
            )


def test_health_verification_binds_exact_resource_revision_component_and_image(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _health_evidence()
    recovery.validate_health(
        context=context,
        service_output=service_output,
        account=account,
        app=app,
        revision=revision,
        previous_revision="example--old",
    )


def test_health_verification_uses_azure_latest_revision_not_stale_terraform_output(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _health_evidence()
    service_output["latest_revision_name"] = "example--stale"
    recovery.validate_health(
        context=context,
        service_output=service_output,
        account=account,
        app=app,
        revision=revision,
        previous_revision="example--old",
    )


def test_no_ingress_health_accepts_absent_azure_health_state(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _health_evidence()
    app["properties"]["configuration"]["ingress"] = None  # type: ignore[index]
    revision["properties"]["healthState"] = None  # type: ignore[index]
    revision["properties"]["runningState"] = "Running"  # type: ignore[index]
    revision["properties"]["replicas"] = 1  # type: ignore[index]

    recovery.validate_health(
        context=context,
        service_output=service_output,
        account=account,
        app=app,
        revision=revision,
        previous_revision="example--old",
    )

    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": ""},
    )
    app["properties"]["latestRevisionName"] = "example--recovery"  # type: ignore[index]
    revision["name"] = "example--recovery"
    recovery.validate_rollback(
        snapshot=snapshot,
        account=account,
        app=app,
        revision=revision,
    )


def test_ingress_health_rejects_absent_azure_health_state(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _health_evidence()
    revision["properties"]["healthState"] = None  # type: ignore[index]

    with pytest.raises(recovery.DeploymentRecoveryError, match="healthy and active"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


def test_no_ingress_health_rejects_nonrunning_revision(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _health_evidence()
    app["properties"]["configuration"]["ingress"] = None  # type: ignore[index]
    revision["properties"]["healthState"] = None  # type: ignore[index]
    revision["properties"]["runningState"] = "Activating"  # type: ignore[index]
    revision["properties"]["replicas"] = 1  # type: ignore[index]

    with pytest.raises(recovery.DeploymentRecoveryError, match="healthy and active"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


def test_recovery_snapshots_only_restorable_key_vault_references(
    recovery: ModuleType,
) -> None:
    context, _, account, app, revision = _health_evidence()
    app["properties"]["configuration"] = {  # type: ignore[index]
        "secrets": [
            {
                "name": "database-dsn",
                "keyVaultUrl": "https://example.vault.azure.net/secrets/database",
                "identity": "/subscriptions/example/identities/runtime",
            }
        ]
    }
    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": ""},
    )
    assert snapshot["previous_secrets"] == [
        {
            "name": "database-dsn",
            "key_vault_url": "https://example.vault.azure.net/secrets/database",
            "identity": "/subscriptions/example/identities/runtime",
        }
    ]
    opaque = copy.deepcopy(app)
    opaque["properties"]["configuration"]["secrets"] = [{"name": "opaque"}]  # type: ignore[index]
    with pytest.raises(recovery.DeploymentRecoveryError, match="Key Vault reference"):
        recovery.capture_snapshot(
            context=context,
            account=account,
            app=opaque,
            revision=revision,
            rollback_contract={"authority_fallback": ""},
        )


@pytest.mark.parametrize(
    ("revision_updates", "app_updates"),
    [
        ({"healthState": "Unhealthy", "runningState": "ActivationFailed"}, {}),
        ({"active": False}, {}),
        ({"provisioningState": "Failed"}, {}),
        ({"healthState": None, "runningState": "Running", "replicas": 1}, {}),
    ],
)
def test_recovery_rejects_unhealthy_or_inactive_rollback_baseline(
    recovery: ModuleType,
    revision_updates: dict[str, object],
    app_updates: dict[str, object],
) -> None:
    context, _, account, app, revision = _health_evidence()
    revision["properties"].update(revision_updates)  # type: ignore[union-attr]
    app["properties"].update(app_updates)  # type: ignore[union-attr]

    with pytest.raises(recovery.DeploymentRecoveryError, match="healthy and active"):
        recovery.capture_snapshot(
            context=context,
            account=account,
            app=app,
            revision=revision,
            rollback_contract={"authority_fallback": ""},
        )


def test_worker_recovery_snapshots_and_verifies_primary_and_clamav_contracts(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _worker_health_evidence()
    recovery.validate_health(
        context=context,
        service_output=service_output,
        account=account,
        app=app,
        revision=revision,
        previous_revision="example--old",
    )
    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": ""},
    )
    assert snapshot["previous_containers"]["primary"] == {
        "image": _image("fdai-document-processing-worker"),
        "probes": revision["properties"]["template"]["containers"][0]["probes"],  # type: ignore[index]
    }
    assert snapshot["previous_containers"]["sidecars"]["clamav"] == {
        "image": "docker.io/clamav/clamav@sha256:" + "b" * 64,
        "probes": sorted(
            revision["properties"]["template"]["containers"][1]["probes"],  # type: ignore[index]
            key=lambda probe: probe["type"],
        ),
    }
    assert (
        snapshot["previous_sidecar_contracts"]["clamav"]
        == context["target"]["sidecar_containers"][0]
    )

    app["properties"]["latestRevisionName"] = "example--recovery"  # type: ignore[index]
    revision["name"] = "example--recovery"
    recovery.validate_rollback(
        snapshot=snapshot,
        account=account,
        app=app,
        revision=revision,
    )


def test_apply_runs_service_migrations_from_masked_key_vault_dsn() -> None:
    workflow = (_ROOT / ".github/workflows/service-deploy.yml").read_text(encoding="utf-8")

    setup_uv = "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990"
    assert "- name: Install pinned uv for service migrations" in workflow
    assert setup_uv in workflow
    assert 'version: "0.11.32"' in workflow
    assert "enable-cache: false" in workflow
    assert workflow.index(setup_uv) < workflow.index(
        "- name: Apply service-owned database migrations"
    )
    assert "- name: Apply service-owned database migrations" in workflow
    assert 'echo "::add-mask::$migration_dsn"' in workflow
    assert 'migration_command="$TRUSTED_CONTROLS/service-migrations/bin/$SERVICE"' in workflow
    assert workflow.count("migration_deadline=$((SECONDS + 1200))") == 1
    assert 'timeout --kill-after=30s "${remaining}s" "$@"' in workflow
    assert 'export FDAI_DATABASE_URL="$migration_dsn"' in workflow
    assert "run_migration env FDAI_DATABASE_URL=" not in workflow
    assert "service migration exceeded its 20-minute stage deadline" in workflow
    assert 'cd "$TRUSTED_CONTROLS"' in workflow
    assert "alembic upgrade head" in workflow
    assert workflow.index("alembic upgrade head") < workflow.index('"$migration_command" bootstrap')
    assert '"$migration_command" bootstrap' in workflow
    assert '"$migration_command" prepare-adoption' not in workflow
    assert '"$migration_command" stamp-baseline' not in workflow
    assert "database-dsn must be an Azure Key Vault HTTPS secret reference" in workflow
    assert "migration_dsn_secret_name" in workflow


def test_rollback_removes_secrets_absent_from_the_exact_snapshot() -> None:
    workflow = (_ROOT / ".github/workflows/service-deploy.yml").read_text(encoding="utf-8")

    assert "app-before-secret-restore.json" in workflow
    assert "mapfile -t extra_secret_names" in workflow
    assert "az containerapp secret remove" in workflow
    assert '--secret-names "${extra_secret_names[@]}"' in workflow


def test_initial_worker_cutover_snapshots_exact_empty_legacy_sidecar_probes(
    recovery: ModuleType,
) -> None:
    context, _, account, app, revision = _worker_health_evidence()
    context["deployment_mode"] = "initial-cutover"
    revision["properties"]["template"]["containers"][1]["probes"] = []  # type: ignore[index]

    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": ""},
    )

    assert snapshot["legacy_sidecar_probe_rollback"] is True
    assert snapshot["previous_containers"]["sidecars"]["clamav"]["probes"] == []
    app["properties"]["latestRevisionName"] = "example--recovery"  # type: ignore[index]
    revision["name"] = "example--recovery"
    recovery.validate_rollback(
        snapshot=snapshot,
        account=account,
        app=app,
        revision=revision,
    )

    strict_context = copy.deepcopy(context)
    strict_context["deployment_mode"] = "normal"
    with pytest.raises(recovery.DeploymentRecoveryError, match="exact startup probes"):
        recovery.capture_snapshot(
            context=strict_context,
            account=account,
            app=app,
            revision=revision,
            rollback_contract={"authority_fallback": ""},
        )


def test_worker_health_rejects_unknown_sidecar(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _worker_health_evidence()
    revision["properties"]["template"]["containers"].append(  # type: ignore[index]
        {
            "name": "unknown",
            "image": "docker.io/example/unknown@sha256:" + "c" * 64,
            "probes": [],
        }
    )
    with pytest.raises(recovery.DeploymentRecoveryError, match="exact allowed sidecar set"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


def test_worker_health_rejects_mutable_sidecar(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _worker_health_evidence()
    revision["properties"]["template"]["containers"][1]["image"] = (  # type: ignore[index]
        "docker.io/clamav/clamav:latest"
    )
    with pytest.raises(recovery.DeploymentRecoveryError, match="sidecar clamav image"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("cpu", 1.0, "config digest"),
        (
            "probes",
            [
                {
                    "type": "Startup",
                    "tcpSocket": {"port": 3310},
                    "failureThreshold": 30,
                },
                {"type": "Liveness", "tcpSocket": {"port": 3310}},
                {"type": "Readiness", "tcpSocket": {"port": 3311}},
            ],
            "probe",
        ),
    ],
)
def test_worker_health_rejects_sidecar_drift_from_sealed_plan_context(
    recovery: ModuleType,
    field: str,
    value: object,
    message: str,
) -> None:
    context, service_output, account, app, revision = _worker_health_evidence()
    sidecar = revision["properties"]["template"]["containers"][1]  # type: ignore[index]
    if field == "cpu":
        sidecar["resources"][field] = value
    else:
        sidecar[field] = value

    with pytest.raises(recovery.DeploymentRecoveryError, match=message):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


def test_worker_health_rejects_unsupported_live_sidecar_configuration(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _worker_health_evidence()
    revision["properties"]["template"]["containers"][1]["env"] = [  # type: ignore[index]
        {"name": "UNSEALED", "value": "1"}
    ]

    with pytest.raises(recovery.DeploymentRecoveryError, match="unsupported runtime"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


@pytest.mark.parametrize("mutation", ["image", "probe"])
def test_worker_rollback_rejects_changed_sidecar_contract(
    recovery: ModuleType,
    mutation: str,
) -> None:
    context, _, account, app, revision = _worker_health_evidence()
    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": ""},
    )
    app["properties"]["latestRevisionName"] = "example--recovery"  # type: ignore[index]
    revision["name"] = "example--recovery"
    sidecar = revision["properties"]["template"]["containers"][1]  # type: ignore[index]
    if mutation == "image":
        sidecar["image"] = "docker.io/clamav/clamav@sha256:" + "c" * 64
    else:
        sidecar["probes"][0]["tcpSocket"]["port"] = 3311
    with pytest.raises(
        recovery.DeploymentRecoveryError,
        match="container contract|sidecar clamav probe contract",
    ):
        recovery.validate_rollback(
            snapshot=snapshot,
            account=account,
            app=app,
            revision=revision,
        )


@pytest.mark.parametrize(
    ("evidence_index", "path", "value", "message"),
    [
        (2, ("id",), "peer-subscription", "subscription"),
        (3, ("id",), "/subscriptions/peer/resourceGroups/peer", "identity"),
        (3, ("name",), "peer", "identity"),
        (3, ("tags", "fdai:component"), "isolated-executor", "component tag"),
        (4, ("properties", "healthState"), "Unhealthy", "healthy and active"),
        (
            4,
            ("properties", "template", "containers", 0, "image"),
            _image("fdai-core-control-plane"),
            "image digest",
        ),
    ],
)
def test_health_verification_rejects_identity_and_health_drift(
    recovery: ModuleType,
    evidence_index: int,
    path: tuple[str | int, ...],
    value: object,
    message: str,
) -> None:
    evidence = [copy.deepcopy(item) for item in _health_evidence()]
    target: object = evidence[evidence_index]
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(recovery.DeploymentRecoveryError, match=message):
        recovery.validate_health(
            context=evidence[0],
            service_output=evidence[1],
            account=evidence[2],
            app=evidence[3],
            revision=evidence[4],
            previous_revision="example--old",
        )


def test_health_verification_rejects_stale_revision(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _health_evidence()
    with pytest.raises(recovery.DeploymentRecoveryError, match="new revision"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--new",
        )


def test_health_verification_rejects_workload_identity_substitution(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _health_evidence()
    app["identity"] = {
        "userAssignedIdentities": {
            "/subscriptions/example-subscription/resourceGroups/example/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/executor": {}
        }
    }

    with pytest.raises(recovery.DeploymentRecoveryError, match="workload identity set"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--old",
        )


def test_executor_rollback_uses_previous_revision_image_without_changing_authority(
    recovery: ModuleType,
) -> None:
    snapshot = {
        "resource_group": "example",
        "service_name": "executor",
        "previous_revision": "executor--previous",
        "previous_image": _image("fdai-isolated-executor"),
        "platform_rollback_required": True,
    }
    command = recovery.rollback_command(snapshot, revision_suffix="rollback-123-1")
    assert command[0:4] == ["az", "containerapp", "revision", "copy"]
    assert command[command.index("--from-revision") + 1] == "executor--previous"
    assert "--image" not in command
    assert "--set-env-vars" not in command


def test_executor_rollback_records_separate_platform_authority_recovery(
    recovery: ModuleType,
) -> None:
    context, _, account, app, revision = _health_evidence()
    snapshot = recovery.capture_snapshot(
        context=context,
        account=account,
        app=app,
        revision=revision,
        rollback_contract={"authority_fallback": "core-in-process"},
    )
    assert snapshot["platform_rollback_required"] is True
    assert "authority_fallback" not in snapshot
    app["properties"]["latestRevisionName"] = "example--recovery"  # type: ignore[index]
    revision["name"] = "example--recovery"
    revision["properties"]["template"]["containers"][0]["env"] = [  # type: ignore[index]
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "0"}
    ]
    recovery.validate_rollback(
        snapshot=snapshot,
        account=account,
        app=app,
        revision=revision,
    )


def test_plan_bundle_round_trip_and_tamper_rejection(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=now,
        **coordinates,
    )
    verified = bundle.verify_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        plan_digest=created["plan_digest"],
        context_digest=created["context_digest"],
        plan_run_id="123",
        now=now + timedelta(minutes=5),
        **coordinates,
    )
    assert verified == created
    sealed_context = json.loads(context.read_text(encoding="utf-8"))
    assert created["deployment_mode"] == "standard"
    assert sealed_context["deployment_mode"] == "standard"
    assert sealed_context["tenant_id"] == "example-tenant"
    assert sealed_context["subscription_id"] == "example-subscription"
    assert sealed_context["backend"] == {
        "resource_group": "example-state-rg",
        "storage_account": "examplestate",
        "container": "tfstate",
        "key": "services/operator-service/dev.tfstate",
    }
    assert sealed_context["target"]["service_resource_id"].endswith(
        "/providers/microsoft.app/containerapps/example"
    )
    assert sealed_context["target"]["service_name"] == "example"
    assert sealed_context["target"]["identity_resource_ids"]
    assert sealed_context["target"]["referenced_resource_ids"]
    assert sealed_context["attestation"] == {
        "signer_workflow": coordinates["attestation_signer_workflow"],
        "source_digest": "b" * 40,
        "subject_digest": f"sha256:{'a' * 64}",
    }
    assert sealed_context["trusted_controls"] == {
        "commit_sha": "d" * 40,
    }
    plan.write_bytes(b"tampered")
    with pytest.raises(bundle.PlanBundleError, match="binary plan digest"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_binds_initial_cutover_mode(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        initial_cutover=True,
        now=now,
        **coordinates,
    )
    assert created["deployment_mode"] == "initial-cutover"
    assert json.loads(context.read_text(encoding="utf-8"))["deployment_mode"] == ("initial-cutover")
    with pytest.raises(bundle.PlanBundleError, match="deployment_mode"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_binds_model_binding_mode(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
    image = _image("fdai-core-control-plane")
    address = "module.core_control_plane.module.container_app.azurerm_container_app.service"
    payload = _plan(address, ["update"], image=image)
    payload["resource_changes"][0]["change"]["after"]["tags"][  # type: ignore[index]
        "fdai:component"
    ] = "core-control-plane"
    plan_json.write_text(json.dumps(payload), encoding="utf-8")
    coordinates = _bundle_coordinates()
    digest = "a" * 64
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="core-control-plane",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        resolved_models_digest=digest,
        model_binding_transition=True,
        now=now,
        **coordinates,
    )
    assert created["deployment_mode"] == "model-binding"
    assert json.loads(context.read_text(encoding="utf-8"))["materials"] == {
        "resolved_models": {"canonical_json_sha256": digest}
    }
    with pytest.raises(bundle.PlanBundleError, match="deployment_mode"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="core-control-plane",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            resolved_models_digest=digest,
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_binds_database_host_mode(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        database_host_binding=True,
        now=now,
        **coordinates,
    )
    assert created["deployment_mode"] == "database-host-binding"
    assert json.loads(context.read_text(encoding="utf-8"))["deployment_mode"] == (
        "database-host-binding"
    )
    with pytest.raises(bundle.PlanBundleError, match="deployment_mode"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_binds_sharepoint_connector_transition(
    bundle: ModuleType,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
    image = _image("fdai-document-ingestion-api")
    _write_plan_json(
        plan_json,
        image=image,
        address="module.document_ingestion_api.module.container_app.azurerm_container_app.service",
    )
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="document-ingestion-api",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        sharepoint_connector_transition="enable",
        now=now,
        **coordinates,
    )
    assert created["deployment_mode"] == "sharepoint-connector-enable"
    with pytest.raises(bundle.PlanBundleError, match="deployment_mode"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="document-ingestion-api",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_binds_operator_channel_edge_transition(
    bundle: ModuleType,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    payload = json.loads(plan_json.read_text(encoding="utf-8"))
    edge_plan = _channel_edge_enable_plan()
    edge_resource = edge_plan["resource_changes"][1]["change"]["after"]  # type: ignore[index]
    edge_resource["template"][0]["container"][0]["image"] = image  # type: ignore[index]
    payload["resource_changes"].extend(edge_plan["resource_changes"])
    plan_json.write_text(json.dumps(payload), encoding="utf-8")
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        operator_channel_edge_transition="enable",
        now=now,
        **coordinates,
    )
    assert created["deployment_mode"] == "operator-channel-edge-enable"
    assert json.loads(context.read_text(encoding="utf-8"))["deployment_mode"] == (
        "operator-channel-edge-enable"
    )
    sealed_edge = json.loads(context.read_text(encoding="utf-8"))["operator_channel_edge"]
    assert sealed_edge["service_name"] == "example-channel-edge"
    assert sealed_edge["component_tag"] == "operator-channel-edge"
    assert sealed_edge["image_ref"] == image
    assert len(sealed_edge["identity_resource_ids"]) == 1
    with pytest.raises(bundle.PlanBundleError, match="deployment_mode"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            operator_channel_edge_transition="disable",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


def test_plan_bundle_seals_disabled_operator_channel_edge_target(
    bundle: ModuleType,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    image = _image("fdai-operator-service")
    payload = _plan(
        "module.operator_service.module.container_app.azurerm_container_app.service",
        ["no-op"],
        image=image,
    )
    edge_plan = _channel_edge_disable_plan()
    edge_resource = edge_plan["resource_changes"][1]["change"]["before"]  # type: ignore[index]
    edge_resource["template"][0]["container"][0]["image"] = image  # type: ignore[index]
    payload["resource_changes"].extend(edge_plan["resource_changes"])
    plan_json.write_text(json.dumps(payload), encoding="utf-8")

    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        operator_channel_edge_transition="disable",
        now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
        **_bundle_coordinates(),
    )

    sealed_edge = json.loads(context.read_text(encoding="utf-8"))["operator_channel_edge"]
    assert created["deployment_mode"] == "operator-channel-edge-disable"
    assert sealed_edge["state"] == "disabled"
    assert sealed_edge["service_name"] == "example-channel-edge"
    assert sealed_edge["image_ref"] == image


def test_worker_plan_bundle_seals_exact_primary_and_sidecar_contract(
    bundle: ModuleType, tmp_path: Path
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary worker plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-document-processing-worker")
    payload = _worker_plan()
    payload["resource_changes"][0]["change"]["after"]["template"][0]["container"][0][  # type: ignore[index]
        "image"
    ] = image
    plan_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"

    bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="document-processing-worker",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
        **_bundle_coordinates(),
    )

    target = json.loads(context.read_text(encoding="utf-8"))["target"]
    assert target["primary_container"] == {
        "config_digest": target["primary_container"]["config_digest"],
        "image_ref": image,
        "name": "document-processing-worker",
    }
    assert len(target["primary_container"]["config_digest"]) == 64
    assert target["sidecar_containers"] == [
        {
            "config_digest": target["sidecar_containers"][0]["config_digest"],
            "image_ref": "docker.io/clamav/clamav@sha256:" + "b" * 64,
            "name": "clamav",
            "probe_digest": target["sidecar_containers"][0]["probe_digest"],
        }
    ]
    assert len(target["sidecar_containers"][0]["config_digest"]) == 64
    assert len(target["sidecar_containers"][0]["probe_digest"]) == 64


def test_initial_worker_bundle_seals_new_sidecar_probe_contract(
    bundle: ModuleType, tmp_path: Path
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary worker cutover plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-document-processing-worker")
    payload = _worker_plan()
    change = payload["resource_changes"][0]["change"]  # type: ignore[index]
    before_sidecar = change["before"]["template"][0]["container"][1]
    before_sidecar.pop("startup_probe")
    before_sidecar.pop("liveness_probe")
    before_sidecar.pop("readiness_probe")
    change["after"]["template"][0]["container"][0]["image"] = image
    planned_sidecar = change["after"]["template"][0]["container"][1]
    for probe_name, values in {
        "startup_probe": {
            "header": [],
            "host": "",
            "initial_delay": 0,
            "interval_seconds": 5,
            "path": "",
            "termination_grace_period_seconds": 0,
            "timeout": 3,
        },
        "liveness_probe": {
            "failure_count_threshold": 3,
            "header": [],
            "host": "",
            "initial_delay": 1,
            "interval_seconds": 30,
            "path": "",
            "termination_grace_period_seconds": 0,
            "timeout": 3,
        },
        "readiness_probe": {
            "failure_count_threshold": 3,
            "header": [],
            "host": "",
            "initial_delay": 0,
            "interval_seconds": 10,
            "path": "",
            "success_count_threshold": 3,
            "timeout": 3,
        },
    }.items():
        planned_sidecar[probe_name][0].update(values)
    plan_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    context = tmp_path / "context.json"
    bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=tmp_path / "metadata.json",
        service="document-processing-worker",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        initial_cutover=True,
        now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
        **_bundle_coordinates(),
    )
    sidecar = json.loads(context.read_text(encoding="utf-8"))["target"]["sidecar_containers"][0]
    assert sidecar["name"] == "clamav"
    assert sidecar["image_ref"].startswith("docker.io/clamav/clamav@sha256:")
    expected_context = _worker_health_evidence()[0]
    assert (
        sidecar["probe_digest"]
        == expected_context["target"]["sidecar_containers"][0][  # type: ignore[index]
            "probe_digest"
        ]
    )


@pytest.mark.parametrize("mutation", ["unknown", "mutable", "changed"])
def test_worker_plan_bundle_rejects_unsealed_sidecar_contract(
    bundle: ModuleType,
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary worker plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-document-processing-worker")
    payload = _worker_plan()
    after_containers = payload["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ]
    after_containers[0]["image"] = image
    if mutation == "unknown":
        after_containers.append(
            {
                "name": "unknown",
                "image": "docker.io/example/unknown@sha256:" + "c" * 64,
            }
        )
    elif mutation == "mutable":
        after_containers[1]["image"] = "docker.io/clamav/clamav:latest"
    else:
        after_containers[1]["cpu"] = 1.0
    plan_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(bundle.PlanBundleError, match="sidecar|container"):
        bundle.create_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=tmp_path / "context.json",
            metadata_path=tmp_path / "metadata.json",
            service="document-processing-worker",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            workflow_run_id="123",
            now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
            **_bundle_coordinates(),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("future_field", 1, "unsupported fields"), ("header", [{"name": "x"}], "headers")],
)
def test_worker_plan_bundle_rejects_unobservable_probe_fields(
    bundle: ModuleType,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary worker plan")
    payload = _worker_plan()
    image = _image("fdai-document-processing-worker")
    change = payload["resource_changes"][0]["change"]  # type: ignore[index]
    change["after"]["template"][0]["container"][0]["image"] = image
    change["after"]["template"][0]["container"][1]["startup_probe"][0][field] = value
    plan_json = tmp_path / "service-plan.json"
    plan_json.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(bundle.PlanBundleError, match=message):
        bundle.create_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=tmp_path / "context.json",
            metadata_path=tmp_path / "metadata.json",
            service="document-processing-worker",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            workflow_run_id="123",
            now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
            **_bundle_coordinates(),
        )


def test_clamav_promotion_seals_exact_evidence_and_rollback(
    bundle: ModuleType,
    promotion: ModuleType,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)

    promotion_context = promotion.build_promotion_context(**inputs)

    assert promotion_context["status"] == "ready"
    assert promotion_context["old_image_ref"] == inputs["old_image_ref"]
    assert promotion_context["new_image_ref"] == inputs["new_image_ref"]
    assert promotion_context["plan_context_digest"] == inputs["plan_context_digest"]
    assert promotion_context["rollback"] == {
        "image_ref": inputs["old_image_ref"],
        "sidecar_contract": inputs["plan_context"]["target"]["sidecar_containers"][0],  # type: ignore[index]
    }
    assert set(promotion_context["evidence"]) == {
        "approval_digest",
        "attestation_digest",
        "scan_digest",
    }
    promotion.verify_promotion_context(promotion_context, **inputs)


@pytest.mark.parametrize("mutation", ["primary", "config", "extra"])
def test_clamav_promotion_rejects_unknown_plan_changes(
    bundle: ModuleType,
    promotion: ModuleType,
    mutation: str,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)
    plan = inputs["plan"]
    after = plan["resource_changes"][0]["change"]["after"]  # type: ignore[index]
    if mutation == "primary":
        after["template"][0]["container"][0]["image"] = _image(  # type: ignore[index]
            "fdai-document-processing-worker"
        )
    elif mutation == "config":
        after["template"][0]["container"][1]["cpu"] = 1.0  # type: ignore[index]
    else:
        plan["resource_changes"].append(copy.deepcopy(plan["resource_changes"][0]))  # type: ignore[union-attr,index]

    with pytest.raises(promotion.SidecarPromotionError, match="unknown|exactly one"):
        promotion.build_promotion_context(**inputs)


@pytest.mark.parametrize(
    "proof",
    ["approval", "approval_case", "approval_duplicate_case", "attestation", "scan"],
)
def test_clamav_promotion_rejects_unbound_proof(
    bundle: ModuleType,
    promotion: ModuleType,
    proof: str,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)
    if proof == "approval":
        inputs["approval"]["approved_by"] = ["requester@example.com"]  # type: ignore[index]
    elif proof == "approval_case":
        inputs["approval"]["approved_by"] = ["Requester@Example.com"]  # type: ignore[index]
    elif proof == "approval_duplicate_case":
        inputs["approval"]["approved_by"] = [  # type: ignore[index]
            "approver@example.com",
            "Approver@Example.com",
        ]
    elif proof == "attestation":
        inputs["attestation"]["subject_digest"] = "sha256:" + "b" * 64  # type: ignore[index]
    else:
        inputs["scan"]["passed"] = False  # type: ignore[index]

    expected_error = "approval" if proof.startswith("approval") else proof
    with pytest.raises(promotion.SidecarPromotionError, match=expected_error):
        promotion.build_promotion_context(**inputs)


def test_clamav_promotion_rejects_attestation_from_another_source_revision(
    bundle: ModuleType,
    promotion: ModuleType,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)
    inputs["attestation"]["source_revision"] = "f" * 40  # type: ignore[index]

    with pytest.raises(promotion.SidecarPromotionError, match="attestation"):
        promotion.build_promotion_context(**inputs)


def test_default_service_deploy_keeps_clamav_sidecar_immutable(
    bundle: ModuleType,
    guard: ModuleType,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)

    with pytest.raises(guard.PlanGuardError, match="sidecar contract drift"):
        primary_image = inputs["plan"]["resource_changes"][0]["change"]["after"][  # type: ignore[index]
            "template"
        ][0]["container"][0]["image"]
        guard.validate_plan(
            inputs["plan"],
            service="document-processing-worker",
            environment="dev",
            image_ref=primary_image,
        )


def test_clamav_promotion_rollback_requires_exact_old_digest(
    bundle: ModuleType,
    promotion: ModuleType,
) -> None:
    inputs = _sidecar_promotion_inputs(bundle)
    promotion_context = promotion.build_promotion_context(**inputs)
    sidecar_contract = promotion_context["rollback"]["sidecar_contract"]
    snapshot = {
        "service": "document-processing-worker",
        "service_resource_id": promotion_context["target"]["service_resource_id"],
        "service_name": promotion_context["target"]["service_name"],
        "resource_group": "example",
        "previous_revision": "example--old",
        "previous_image": _image("fdai-document-processing-worker"),
        "previous_sidecar_contracts": {"clamav": sidecar_contract},
    }

    command = promotion.promotion_rollback_command(
        promotion_context=promotion_context,
        snapshot=snapshot,
        revision_suffix="rollback-123-1",
    )

    assert command[0:4] == ["az", "containerapp", "revision", "copy"]
    assert command[command.index("--from-revision") + 1] == "example--old"
    changed = copy.deepcopy(snapshot)
    changed["previous_sidecar_contracts"]["clamav"]["image_ref"] = inputs["new_image_ref"]
    with pytest.raises(promotion.SidecarPromotionError, match="exact old ClamAV digest"):
        promotion.promotion_rollback_command(
            promotion_context=promotion_context,
            snapshot=changed,
            revision_suffix="rollback-123-1",
        )


def test_core_plan_bundle_seals_only_canonical_resolved_models_digest(
    bundle: ModuleType, tmp_path: Path
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-core-control-plane")
    _write_plan_json(
        plan_json,
        image=image,
        address="module.core_control_plane.module.container_app.azurerm_container_app.service",
    )
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    digest = "e" * 64
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="core-control-plane",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        resolved_models_digest=digest,
        now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
        **coordinates,
    )
    sealed_context = json.loads(context.read_text(encoding="utf-8"))
    assert sealed_context["materials"] == {"resolved_models": {"canonical_json_sha256": digest}}
    assert "capabilities" not in sealed_context
    with pytest.raises(bundle.PlanBundleError, match="canonical resolved-models"):
        bundle.create_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="core-control-plane",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            workflow_run_id="123",
            now=datetime(2026, 8, 8, 10, 0, tzinfo=UTC),
            **coordinates,
        )
    assert created["resolved_models_digest"] == digest


@pytest.mark.parametrize(
    "coordinate",
    [
        "tenant_id",
        "subscription_id",
        "backend_resource_group",
        "backend_storage_account",
        "backend_container",
        "workflow_run_attempt",
        "controls_commit_sha",
        "attestation_signer_workflow",
    ],
)
def test_plan_bundle_rejects_apply_context_drift(
    bundle: ModuleType,
    tmp_path: Path,
    coordinate: str,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=now,
        **coordinates,
    )
    changed = dict(coordinates)
    changed[coordinate] = "3" if coordinate == "workflow_run_attempt" else "changed"
    with pytest.raises(bundle.PlanBundleError, match="exact apply input"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **changed,
        )


def test_expired_plan_bundle_is_rejected(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="c" * 40,
        image_ref=image,
        workflow_run_id="456",
        now=now,
        **coordinates,
    )
    with pytest.raises(bundle.PlanBundleError, match="expired"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="c" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="456",
            now=now + timedelta(hours=25),
            **coordinates,
        )
