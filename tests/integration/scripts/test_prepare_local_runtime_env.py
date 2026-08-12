"""Local runtime environment preparation regression tests."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from fdai_service_contracts.semantic_turn import (
    SEMANTIC_PHYSICAL_TOPIC,
    SEMANTIC_PROJECTION_TOPIC,
    SEMANTIC_REQUEST_TOPIC,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/azure/prepare-local-runtime-env.sh"
_BASH = shutil.which("bash") or "bash"


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
def test_prepares_deployed_transport_without_copying_stale_transport(
    tmp_path: Path,
    web_search_candidates: list[dict[str, str]],
    expected_web_search_enabled: str,
    local_vision_state: str,
    semantic_outputs_present: bool,
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
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_CLIENT_ID=client\n"
        "LLM_MODE=local-fake\n"
        "LLM_RESOLVED_MODELS_PATH=/stale/resolved-models.json\n"
        "FDAI_METERING_DSN=postgresql://stale\n"
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=stale.example.com:9093\n"
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=stale.requests\n"
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=stale.projections\n"
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=stale.physical\n"
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
        "FDAI_DIRECT_API_FAKE=1\n",
        encoding="utf-8",
    )
    semantic_outputs = (
        'elif [[ "$*" == *"output -json event_bus_semantic_topics"* ]]; then\n'
        f'  printf \'["{SEMANTIC_REQUEST_TOPIC}","{SEMANTIC_PROJECTION_TOPIC}"]\'\n'
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
        '  printf \'["aw.finops.events","aw.change.events","aw.pantheon.objects"]\'\n'
        + semantic_outputs
        + 'elif [[ "$*" == *"output -json event_bus_auxiliary_topics"* ]]; then\n'
        "  printf '[\"aw.pipeline.stages\"]'\n"
        'elif [[ "$*" == *"output -json event_bus_operational_topics"* ]]; then\n'
        '  printf \'["aw.control.canary","aw.control.canary.dlq","aw.inventory.raw"]\'\n'
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
    assert values == [
        "VITE_MSAL_CLIENT_ID=client",
        "AZURE_TENANT_ID=00000000-0000-0000-0000-000000000002",
        "AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001",
        "AZURE_RESOURCE_GROUP=rg-example",
        "AZURE_REGION=example-region",
        "KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=aw.pantheon.objects",
        "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS=example-ops.servicebus.windows.net:9093",
        "KAFKA_TOPIC_EVENTS=aw.change.events",
        "FDAI_STAGE_TOPIC=aw.pipeline.stages",
        "FDAI_PANTHEON_OBJECT_TOPIC=aw.pantheon.objects",
        "FDAI_INVENTORY_RAW_TOPIC=aw.inventory.raw",
        "POSTGRES_HOST=127.0.0.1",
        "POSTGRES_DATABASE=fdai",
        "FDAI_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai",
        "FDAI_STATE_STORE_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        "FDAI_METERING_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        "LLM_MODE=azure",
        f"LLM_RESOLVED_MODELS_PATH={expected_models_path}",
        "FDAI_LLM_ENDPOINT=https://models.example.com",
        f"FDAI_WEB_SEARCH_ENABLED={expected_web_search_enabled}",
        "RUNTIME_ENV=dev",
        "AUTONOMY_MODE_DEFAULT=shadow",
        "FDAI_START_CONSUMER=1",
        "FDAI_START_PANTHEON=1",
        "FDAI_STARTUP_KAFKA_PROBE_TOPIC=aw.change.events.dlq",
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
        "  printf '[\"aw.change.events\"]'\n"
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


def test_omits_inventory_invalidation_topic_until_provisioned(tmp_path: Path) -> None:
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
        "  printf '[\"aw.change.events\"]'\n"
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

    assert "FDAI_INVENTORY_RAW_TOPIC=" not in output.read_text(encoding="utf-8")
    assert "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=" not in output.read_text(encoding="utf-8")
    assert "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=" not in output.read_text(encoding="utf-8")
    assert "FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-developer-b-core" in output.read_text(
        encoding="utf-8"
    )
    assert "invalidation uses TTL refresh" in completed.stderr
    # No operations gateway is provisioned here, so the governed direct-API
    # executor must fall back to the in-memory shadow fake automatically.
    assert "FDAI_DIRECT_API_FAKE=1" in output.read_text(encoding="utf-8")
    assert "FDAI_DEV_OPERATIONS_GATEWAY_URL=" not in output.read_text(encoding="utf-8")
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
        "  printf '[\"aw.change.events\"]'\n"
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
        "  printf '[\"aw.change.events\"]'\n"
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
