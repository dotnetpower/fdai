"""Local runtime environment preparation regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml
from fdai_service_contracts.semantic_turn import (
    SEMANTIC_PHYSICAL_TOPIC,
    SEMANTIC_PROJECTION_TOPIC,
    SEMANTIC_REQUEST_TOPIC,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/azure/prepare-local-runtime-env.sh"
_FULL_STACK_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-console-full-stack.sh"
_BASH = shutil.which("bash") or "bash"
_OPERATING_MODEL_TOPIC = "fdai.operating-model"


def test_validation_database_uses_an_isolated_local_postgres_cluster() -> None:
    compose = yaml.safe_load(
        (_REPO_ROOT / "infra/local/docker-compose.yml").read_text(encoding="utf-8")
    )
    runtime = compose["services"]["postgres"]
    validation = compose["services"]["postgres-validation"]

    assert runtime["ports"] == ["127.0.0.1:5432:5432"]
    assert validation["ports"] == ["127.0.0.1:5433:5432"]
    assert runtime["volumes"] != validation["volumes"]


def test_semantic_fallback_loads_shared_contract() -> None:
    script = _SCRIPT.read_text(encoding="utf-8")

    assert "fdai_service_contracts/semantic_turn.py" in script
    assert "ast.parse" in script
    assert "SEMANTIC_REQUEST_TOPIC" in script
    assert "SEMANTIC_PROJECTION_TOPIC" in script
    assert "SEMANTIC_PHYSICAL_TOPIC" in script


_EXECUTOR_RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/id-example"
)


@pytest.mark.parametrize(
    ("web_search_candidates", "expected_web_search_enabled", "local_vision_state"),
    [
        ([], "0", "absent"),
        (
            [
                {
                    "endpoint": "https://models.example.com/",
                    "deployment": "web-search",
                }
            ],
            "1",
            "absent",
        ),
        ([], "0", "valid"),
        ([], "0", "invalid"),
        ([], "0", "core-incompatible"),
    ],
)
@pytest.mark.parametrize("semantic_outputs_present", [True, False])
@pytest.mark.parametrize(
    "local_kubernetes_binding_mode",
    ["disabled", "legacy", "fleet", "subscription"],
)
def test_prepares_deployed_transport_without_copying_stale_transport(
    tmp_path: Path,
    web_search_candidates: list[dict[str, str]],
    expected_web_search_enabled: str,
    local_vision_state: str,
    semantic_outputs_present: bool,
    local_kubernetes_binding_mode: str,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "resolved-models.json").write_text(
        json.dumps(
            {
                "narrator": {"endpoint": "https://models.example.com/"},
                "web_search_candidates": web_search_candidates,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if local_vision_state != "absent":
        (repo / ".fdai").mkdir()
    if local_vision_state in {"valid", "core-incompatible"}:
        candidate = {
            "endpoint": "https://models.example.com/",
            "deployment": "narrator-mini",
            "api_version": "2024-08-01-preview",
        }
        capabilities = [
            {
                "name": "t1.embedding",
                "status": "resolved",
            },
            {
                "name": "t2.reasoner.primary",
                "status": "resolved" if local_vision_state == "valid" else "hil-only",
            },
            {
                "name": "t2.reasoner.secondary",
                "status": "hil-only",
            },
        ]
        (repo / ".fdai/resolved-models-vision.json").write_text(
            json.dumps(
                {
                    "mixed_model_mode": (
                        "hil-only" if local_vision_state == "valid" else "azure-foundry"
                    ),
                    "capabilities": capabilities,
                    "narrator": candidate,
                    "narrator_candidates": [candidate],
                    "vision_candidates": [candidate],
                }
            )
            + "\n",
            encoding="utf-8",
        )
    elif local_vision_state == "invalid":
        (repo / ".fdai/resolved-models-vision.json").write_text(
            '{"vision_candidates": [{"deployment": "not-a-narrator"}]}\n',
            encoding="utf-8",
        )
    legacy_kubernetes = (
        (
            "FDAI_KUBERNETES_API_SERVER=https://aks.example.com:443\n"
            "FDAI_KUBERNETES_AUDIENCE=example-audience\n"
            "FDAI_KUBERNETES_AUTH_MODE=workload-identity\n"
            "FDAI_KUBERNETES_CA_PATH=/tmp/example-ca.pem\n"
            "FDAI_KUBERNETES_CLUSTER_REF=/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example/providers/Microsoft.ContainerService/managedClusters/aks-example\n"
        )
        if local_kubernetes_binding_mode in {"disabled", "legacy"}
        else ""
    )
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_CLIENT_ID=client\n"
        "LLM_MODE=local-fake\n"
        "LLM_RESOLVED_MODELS_PATH=/stale/resolved-models.json\n"
        "LLM_RESOLVED_MODELS_SHA256=stale-digest\n"
        "FDAI_METERING_DSN=postgresql://stale\n"
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=stale.example.com:9093\n"
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=stale.requests\n"
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=stale.projections\n"
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=stale.physical\n"
        "FDAI_OPERATING_MODEL_TOPIC=stale.operating-model\n"
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC=stale.read.requests\n"
        "KAFKA_TOPIC_EVENTS=stale.topic\n"
        "FDAI_CANARY_TOPIC=stale.canary\n"
        "FDAI_INVENTORY_RAW_TOPIC=stale.inventory\n"
        "FDAI_HIL_DECISION_TOPIC=stale.hil\n"
        "FDAI_AZURE_READER_SUBSCRIPTION_ID=stale-subscription\n"
        "FDAI_AZURE_READER_RESOURCE_GROUPS=stale-group\n"
        "FDAI_MONITOR_WORKSPACE_ID=stale-workspace\n"
        "FDAI_DEV_OPERATIONS_GATEWAY_URL=https://stale.example.com\n"
        "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=stale-audience\n"
        "FDAI_WEB_SEARCH_ENABLED=1\n"
        "FDAI_DIRECT_API_FAKE=1\n" + legacy_kubernetes + "FDAI_TEAMS_NOTIFICATION_ACTIVATION=0\n"
        "FDAI_TEAMS_OPS_ENDPOINT=https://flow.example.com/trigger/local\n"
        "FDAI_SLACK_OPS_WEBHOOK_URL=https://hooks.slack.example/services/local\n",
        encoding="utf-8",
    )
    if local_kubernetes_binding_mode == "fleet":
        (repo / ".fdai").mkdir(exist_ok=True)
        bindings_path = repo / ".fdai/local-kubernetes-bindings.json"
        bindings_path.write_text(
            json.dumps(
                [
                    {
                        "api_server": "https://aks.example.com:443",
                        "audience": "example-audience",
                        "auth_mode": "workload-identity",
                        "ca_pem": "example-ca",
                        "cluster_ref": (
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-example/providers/"
                            "Microsoft.ContainerService/managedClusters/aks-example"
                        ),
                    }
                ]
            ),
            encoding="utf-8",
        )
        bindings_path.chmod(0o600)
    semantic_outputs = (
        'elif [[ "$*" == *"output -json event_bus_semantic_topics"* ]]; then\n'
        f'  printf \'["{SEMANTIC_REQUEST_TOPIC}",'
        f'"{SEMANTIC_PROJECTION_TOPIC}",'
        '"operator.read-investigation.requests"]\'\n'
        'elif [[ "$*" == *"output -raw event_bus_semantic_physical_topic"* ]]; then\n'
        f"  printf '{SEMANTIC_PHYSICAL_TOPIC}'\n"
        if semantic_outputs_present
        else ""
    )
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -raw event_bus_operational_kafka_bootstrap"* ]]; then\n'
        "  printf 'example-ops.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        '  printf \'["fdai.finops.events","fdai.change.events","fdai.pantheon.objects"]\'\n'
        + semantic_outputs
        + 'elif [[ "$*" == *"output -json event_bus_auxiliary_topics"* ]]; then\n'
        "  printf '[\"fdai.pipeline.stages\"]'\n"
        'elif [[ "$*" == *"output -json event_bus_operational_topics"* ]]; then\n'
        '  printf \'["fdai.control.canary","fdai.control.canary.dlq","fdai.inventory.raw"]\'\n'
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
        'elif [[ "$*" == *"output -raw log_workspace_customer_id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000003'\n"
        'elif [[ "$*" == *"output -raw dev_operations_gateway_url"* ]]; then\n'
        "  printf 'https://gateway.example.com'\n"
        'elif [[ "$*" == *"output -raw dev_operations_gateway_audience"* ]]; then\n'
        "  printf 'api-application-id'\n"
        'elif [[ "$*" == *"output -raw executor_identity_resource_id"* ]]; then\n'
        f"  printf '{_EXECUTOR_RESOURCE_ID}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000001'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show"* ]]; then\n'
        "  printf 'example-region'\n"
        'elif [[ "$*" == *"eventhubs eventhub show"* ]]; then\n'
        f"  printf '{SEMANTIC_PHYSICAL_TOPIC}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - resolved binary with test-controlled arguments
        [_BASH, str(_SCRIPT), str(output)],
        check=True,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": str(terraform),
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-a",
            "FDAI_LOCAL_KUBERNETES_LIFECYCLE": (
                "0" if local_kubernetes_binding_mode == "disabled" else "1"
            ),
            "FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION": "1",
        },
        capture_output=True,
        text=True,
    )

    expected_models_path = repo / (
        ".fdai/resolved-models-vision.json"
        if local_vision_state == "valid"
        else "resolved-models.json"
    )
    values = output.read_text(encoding="utf-8").splitlines()
    core_state_store = next(value for value in values if value.startswith("FDAI_STATE_STORE_DSN="))
    assert core_state_store.endswith("?options=-c%20role%3Dfdai_core")
    values[values.index(core_state_store)] = core_state_store.removesuffix(
        "?options=-c%20role%3Dfdai_core"
    )
    expected_prefix = [
        "VITE_MSAL_CLIENT_ID=client",
        "FDAI_TEAMS_OPS_ENDPOINT=https://flow.example.com/trigger/local",
        "FDAI_SLACK_OPS_WEBHOOK_URL=https://hooks.slack.example/services/local",
    ]
    if local_kubernetes_binding_mode == "legacy":
        expected_prefix.extend(
            [
                "FDAI_KUBERNETES_API_SERVER=https://aks.example.com:443",
                "FDAI_KUBERNETES_AUDIENCE=example-audience",
                "FDAI_KUBERNETES_AUTH_MODE=workload-identity",
                "FDAI_KUBERNETES_CA_PATH=/tmp/example-ca.pem",
                "FDAI_KUBERNETES_CLUSTER_REF=/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example/providers/Microsoft.ContainerService/managedClusters/aks-example",
            ]
        )
    elif local_kubernetes_binding_mode == "fleet":
        expected_prefix.append(
            "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON="
            '[{"api_server":"https://aks.example.com:443",'
            '"audience":"example-audience","auth_mode":"workload-identity",'
            '"ca_pem":"example-ca","cluster_ref":'
            '"/subscriptions/00000000-0000-0000-0000-000000000001/'
            "resourceGroups/rg-example/providers/"
            'Microsoft.ContainerService/managedClusters/aks-example"}]'
        )
    elif local_kubernetes_binding_mode == "subscription":
        expected_prefix.append("FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY=1")
    assert values == [
        *expected_prefix,
        "AZURE_TENANT_ID=00000000-0000-0000-0000-000000000002",
        "AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001",
        "AZURE_RESOURCE_GROUP=rg-example",
        "AZURE_REGION=example-region",
        "FDAI_EXECUTION_VENUE=local",
        "KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092",
        "KAFKA_SECURITY_PROTOCOL=PLAINTEXT",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=fdai.pantheon.objects",
        f"FDAI_OPERATING_MODEL_TOPIC={_OPERATING_MODEL_TOPIC}",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC=operator.read-investigation.requests",
        "KAFKA_TOPIC_EVENTS=fdai.change.events",
        "FDAI_STAGE_TOPIC=fdai.pipeline.stages",
        "FDAI_PANTHEON_OBJECT_TOPIC=fdai.pantheon.objects",
        "FDAI_HIL_DECISION_TOPIC=fdai.hil.decisions",
        "FDAI_INVENTORY_RAW_TOPIC=fdai.inventory.raw",
        "POSTGRES_HOST=127.0.0.1",
        "POSTGRES_DATABASE=fdai",
        "FDAI_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai",
        "FDAI_VALIDATION_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5433/fdai_validation",
        "FDAI_STATE_STORE_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        f"FDAI_CHAT_ASSURANCE_READINESS_RECEIPT={repo}/.fdai/conversation-assurance/runtime-readiness.json",
        "FDAI_METERING_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        "LLM_MODE=azure",
        f"LLM_RESOLVED_MODELS_PATH={expected_models_path}",
        f"LLM_RESOLVED_MODELS_SHA256={hashlib.sha256(expected_models_path.read_bytes()).hexdigest()}",
        "FDAI_LLM_ENDPOINT=https://models.example.com",
        f"FDAI_WEB_SEARCH_ENABLED={expected_web_search_enabled}",
        "RUNTIME_ENV=dev",
        "AUTONOMY_MODE_DEFAULT=shadow",
        "FDAI_START_CONSUMER=1",
        "FDAI_START_PANTHEON=1",
        "FDAI_TEAMS_NOTIFICATION_ACTIVATION=1",
        "FDAI_STARTUP_KAFKA_PROBE_TOPIC=fdai.startup.probes",
        "FDAI_STARTUP_KAFKA_SETTLE_SECONDS=20",
        "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS=90",
        "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS=180",
        "FDAI_RUNTIME_LOCAL_AZURE_CLI=1",
        "FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-developer-a-core",
        "FDAI_PANTHEON_CONSUMER_GROUP_PREFIX=fdai-local-developer-a-pantheon",
        "FDAI_OPERATOR_API_CONSUMER_INSTANCE=fdai-local-developer-a-operator-api",
        "FDAI_AZURE_READER_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001",
        "FDAI_AZURE_READER_RESOURCE_GROUPS=rg-example",
        "FDAI_MONITOR_WORKSPACE_ID=00000000-0000-0000-0000-000000000003",
        "FDAI_DEV_OPERATIONS_GATEWAY_URL=https://gateway.example.com",
        "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=api-application-id",
    ]
    if local_vision_state in {"invalid", "core-incompatible"}:
        assert "ignored invalid local vision model artifact" in completed.stderr
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_full_stack_task_explicitly_activates_saved_teams_notifications() -> None:
    content = "\n".join(
        line
        for line in (_REPO_ROOT / ".vscode/tasks.json").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )
    tasks = json.loads(content)["tasks"]
    prepare = next(task for task in tasks if task.get("label") == "console: prepare full stack")

    assert prepare["options"]["env"]["FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION"] == "1"


def test_full_stack_cache_binds_local_activation_inputs() -> None:
    source = _FULL_STACK_SCRIPT.read_text(encoding="utf-8")
    runtime_stage = source[source.index("run_stage \\\n  runtime-environment") :]
    runtime_stage = runtime_stage[: runtime_stage.index("\n  prepare_runtime_environment \\\n")]

    assert "configuration_digest" in runtime_stage
    assert "FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION" in runtime_stage
    assert "FDAI_LOCAL_KUBERNETES_LIFECYCLE" in runtime_stage
    assert "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH" in source
    assert "kubernetes-bindings-path=" in runtime_stage
    assert "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH|" in _SCRIPT.read_text(encoding="utf-8")
    assert "FDAI_LOCAL_NO_AZURE_DEPLOYMENT" in runtime_stage
    assert "FDAI_LOCAL_RESOURCE_GROUP" in runtime_stage


def test_full_stack_cache_binds_explicit_model_override_path_and_bytes() -> None:
    source = _FULL_STACK_SCRIPT.read_text(encoding="utf-8")

    assert source.count('+=("$resolved_models_override")') == 2
    assert source.count('"resolved-models-override=$resolved_models_override"') == 2


def test_rejects_invalid_local_teams_notification_activation_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("VITE_MSAL_CLIENT_ID=client\n", encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(repo / ".fdai/local-runtime.env")],
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION": "invalid",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION MUST be 0 or 1" in completed.stderr


def test_rejects_partial_local_kubernetes_lifecycle_binding_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text(
        "FDAI_KUBERNETES_API_SERVER=https://aks.example.com:443\n",
        encoding="utf-8",
    )
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-kubernetes",
            "FDAI_LOCAL_KUBERNETES_LIFECYCLE": "1",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "requires one non-empty FDAI_KUBERNETES_AUDIENCE binding" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_rejects_relative_local_kubernetes_binding_path_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("", encoding="utf-8")
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-kubernetes",
            "FDAI_LOCAL_KUBERNETES_LIFECYCLE": "1",
            "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH": "bindings.json",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "MUST be an absolute path" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_rejects_group_readable_local_kubernetes_binding_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("", encoding="utf-8")
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    bindings = repo / "bindings.json"
    bindings.write_text("[]", encoding="utf-8")
    bindings.chmod(0o640)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-kubernetes",
            "FDAI_LOCAL_KUBERNETES_LIFECYCLE": "1",
            "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH": str(bindings),
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "file must be owner-only" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_rejects_mixed_local_kubernetes_bindings_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text(
        "FDAI_KUBERNETES_API_SERVER=https://aks.example.com\n",
        encoding="utf-8",
    )
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    bindings = repo / "bindings.json"
    bindings.write_text("[]", encoding="utf-8")
    bindings.chmod(0o600)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-kubernetes",
            "FDAI_LOCAL_KUBERNETES_LIFECYCLE": "1",
            "FDAI_LOCAL_KUBERNETES_BINDINGS_PATH": str(bindings),
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "MUST NOT be combined with legacy FDAI_KUBERNETES_API_SERVER" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_detects_single_log_workspace_when_terraform_state_omits_customer_id(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        "  printf '[\"fdai.change.events\"]'\n"
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
        'elif [[ "$*" == *"output -raw executor_identity_resource_id"* ]]; then\n'
        f"  printf '{_EXECUTOR_RESOURCE_ID}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000001'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show"* ]]; then\n'
        "  printf 'example-region'\n"
        'elif [[ "$*" == *"monitor log-analytics workspace list"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000003'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled binaries
        [_BASH, str(_SCRIPT), str(output)],
        check=True,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": str(terraform),
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-workspace",
        },
        capture_output=True,
        text=True,
    )

    rendered = output.read_text(encoding="utf-8")
    assert "FDAI_MONITOR_WORKSPACE_ID=00000000-0000-0000-0000-000000000003" in rendered
    assert "workspace detected via Azure CLI" in completed.stderr


def test_rejects_resolved_models_without_core_endpoint_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    (repo / "resolved-models.json").write_text('{"capabilities": []}\n', encoding="utf-8")
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-models",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "requires narrator.endpoint" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_uses_local_semantic_topics_without_inventory_invalidation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text(
        "FDAI_INVENTORY_RAW_TOPIC=stale.inventory\n"
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=stale.requests\n"
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=stale.projections\n",
        encoding="utf-8",
    )
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        "  printf '[\"fdai.change.events\"]'\n"
        'elif [[ "$*" == *"output -json event_bus_auxiliary_topics"* ]]; then\n'
        "  exit 1\n"
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
        'elif [[ "$*" == *"output -raw executor_identity_resource_id"* ]]; then\n'
        f"  printf '{_EXECUTOR_RESOURCE_ID}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000001'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show"* ]]; then\n'
        "  printf 'example-region'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled binaries
        [_BASH, str(_SCRIPT), str(output)],
        check=True,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": str(terraform),
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-b",
        },
        capture_output=True,
        text=True,
    )

    rendered = output.read_text(encoding="utf-8")
    assert "FDAI_INVENTORY_RAW_TOPIC=" not in rendered
    assert f"FDAI_SEMANTIC_TURN_REQUEST_TOPIC={SEMANTIC_REQUEST_TOPIC}" in rendered
    assert f"FDAI_SEMANTIC_TURN_PROJECTION_TOPIC={SEMANTIC_PROJECTION_TOPIC}" in rendered
    assert f"FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC={SEMANTIC_PHYSICAL_TOPIC}" in rendered
    assert f"FDAI_OPERATING_MODEL_TOPIC={_OPERATING_MODEL_TOPIC}" in rendered
    assert "FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-developer-b-core" in rendered
    assert "invalidation uses TTL refresh" in completed.stderr
    # No operations gateway is provisioned here, so the governed direct-API
    # executor must fall back to the in-memory shadow fake automatically.
    assert "FDAI_DIRECT_API_FAKE=1" in rendered
    assert "FDAI_DEV_OPERATIONS_GATEWAY_URL=" not in rendered
    assert "uses the in-memory shadow fake" in completed.stderr


def test_rejects_cli_subscription_that_differs_from_terraform(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        "  printf '[\"fdai.change.events\"]'\n"
        'elif [[ "$*" == *"output -json event_bus_auxiliary_topics"* ]]; then\n'
        "  printf '[]'\n"
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
        'elif [[ "$*" == *"output -raw executor_identity_resource_id"* ]]; then\n'
        f"  printf '{_EXECUTOR_RESOURCE_ID}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000099'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show"* ]]; then\n'
        "  echo 'group lookup MUST NOT run after a subscription mismatch' >&2\n"
        "  exit 3\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled binaries
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": str(terraform),
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-c",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "does not match the applied Terraform deployment" in completed.stderr
    assert "group lookup MUST NOT run" not in completed.stderr
    assert not output.exists()


def test_rejects_invalid_local_consumer_instance_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "INVALID/value",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "FDAI_LOCAL_CONSUMER_INSTANCE MUST match" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_rejects_invalid_resolved_models_override_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(output)],
        check=False,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-models",
            "FDAI_LOCAL_RESOLVED_MODELS_PATH": "relative/resolved-models.json",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "MUST name an existing absolute file" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()


def test_detects_gateway_via_azure_cli_when_terraform_state_omits_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text("VITE_DEV_MODE=0\n", encoding="utf-8")
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        "  printf '[\"fdai.change.events\"]'\n"
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
        'elif [[ "$*" == *"output -raw executor_identity_resource_id"* ]]; then\n'
        f"  printf '{_EXECUTOR_RESOURCE_ID}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    terraform.chmod(0o755)
    gateway_app_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
        "rg-example/providers/Microsoft.Web/sites/func-example-devgw-abc123"
    )
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000001'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show"* ]]; then\n'
        "  printf 'example-region'\n"
        'elif [[ "$*" == *"functionapp list"* ]]; then\n'
        f"  printf '{gateway_app_id}'\n"
        'elif [[ "$*" == *"functionapp show"* ]]; then\n'
        "  printf 'func-example-devgw-abc123.azurewebsites.net'\n"
        'elif [[ "$*" == *"rest --method post"* ]]; then\n'
        "  printf 'api://gateway-app-id'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled binaries
        [_BASH, str(_SCRIPT), str(output)],
        check=True,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": str(terraform),
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "developer-d",
        },
        capture_output=True,
        text=True,
    )

    rendered = output.read_text(encoding="utf-8")
    # Terraform state omits the gateway, so the URL/audience are recovered from
    # the live Azure CLI probe and the shadow fake must NOT be wired.
    assert (
        "FDAI_DEV_OPERATIONS_GATEWAY_URL=https://func-example-devgw-abc123.azurewebsites.net"
        in rendered
    )
    assert "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=api://gateway-app-id" in rendered
    assert "FDAI_DIRECT_API_FAKE=" not in rendered
    assert "detected via Azure CLI" in completed.stderr


def test_no_azure_deployment_mode_skips_terraform_and_verifies_explicit_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_CLIENT_ID=client\nFDAI_DIRECT_API_FAKE=1\n", encoding="utf-8"
    )
    az = tmp_path / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"account show --query id"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000001'\n"
        'elif [[ "$*" == *"account show --query tenantId"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000002'\n"
        'elif [[ "$*" == *"group show --subscription '
        '00000000-0000-0000-0000-000000000001 --name rg-example --query location"* ]]; then\n'
        "  printf 'example-region'\n"
        'elif [[ "$*" == *"monitor log-analytics workspace list"* ]]; then\n'
        "  printf '00000000-0000-0000-0000-000000000003'\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    completed = subprocess.run(  # noqa: S603 - test-controlled binaries
        [_BASH, str(_SCRIPT), str(output)],
        check=True,
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": str(az),
            "FDAI_LOCAL_CONSUMER_INSTANCE": "no-deploy",
            "FDAI_LOCAL_NO_AZURE_DEPLOYMENT": "1",
            "FDAI_LOCAL_RESOURCE_GROUP": "rg-example",
        },
        capture_output=True,
        text=True,
    )

    rendered = output.read_text(encoding="utf-8")
    assert "provider-access-must-not-run" not in completed.stderr
    assert "AZURE_TENANT_ID=00000000-0000-0000-0000-000000000002" in rendered
    assert "AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001" in rendered
    assert "AZURE_RESOURCE_GROUP=rg-example" in rendered
    assert "AZURE_REGION=example-region" in rendered
    assert "KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092" in rendered
    assert "FDAI_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092" in rendered
    assert "FDAI_DIRECT_API_FAKE=" not in rendered
    assert "FDAI_DEV_OPERATIONS_GATEWAY_URL=" not in rendered
    assert "FDAI_MONITOR_WORKSPACE_ID=00000000-0000-0000-0000-000000000003" in rendered
    assert "LLM_RESOLVED_MODELS_PATH=" not in rendered
    # A local Redpanda broker joins in milliseconds; the Event Hubs-tuned slow-join
    # timeouts would otherwise make every readiness probe wait up to 90-180s.
    assert "FDAI_STARTUP_KAFKA_SETTLE_SECONDS=" not in rendered
    assert "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS=" not in rendered
    assert "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS=" not in rendered
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_rejects_invalid_no_azure_deployment_flag_before_provider_access(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("VITE_MSAL_CLIENT_ID=client\n", encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - test-controlled environment
        [_BASH, str(_SCRIPT), str(repo / ".fdai/local-runtime.env")],
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_TERRAFORM_BIN": "/provider-access-must-not-run",
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_NO_AZURE_DEPLOYMENT": "invalid",
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "FDAI_LOCAL_NO_AZURE_DEPLOYMENT MUST be 0 or 1" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr


@pytest.mark.parametrize("scope", ["", "invalid;scope", "../scope"])
def test_no_deployment_requires_explicit_valid_scope_before_provider_access(
    tmp_path: Path,
    scope: str,
) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "console/.env.local").write_text("VITE_MSAL_CLIENT_ID=client\n", encoding="utf-8")
    output = repo / ".fdai/local-runtime.env"
    completed = subprocess.run(  # noqa: S603 - isolated provider-free validation
        [_BASH, str(_SCRIPT), str(output)],
        env={
            **os.environ,
            "FDAI_REPO_ROOT": str(repo),
            "FDAI_AZ_BIN": "/provider-access-must-not-run",
            "FDAI_LOCAL_NO_AZURE_DEPLOYMENT": "1",
            "FDAI_LOCAL_RESOURCE_GROUP": scope,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode != 0
    assert "FDAI_LOCAL_RESOURCE_GROUP MUST" in completed.stderr
    assert "provider-access-must-not-run" not in completed.stderr
    assert not output.exists()
