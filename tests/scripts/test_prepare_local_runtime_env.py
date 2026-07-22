"""Local runtime environment preparation regression tests."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts/deployment/azure/prepare-local-runtime-env.sh"
_BASH = shutil.which("bash") or "bash"
_EXECUTOR_RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/id-example"
)


def test_prepares_deployed_transport_without_copying_stale_transport(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_CLIENT_ID=client\n"
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=stale.example.com:9093\n"
        "KAFKA_TOPIC_EVENTS=stale.topic\n"
        "FDAI_CANARY_TOPIC=stale.canary\n"
        "FDAI_INVENTORY_RAW_TOPIC=stale.inventory\n"
        "FDAI_HIL_DECISION_TOPIC=stale.hil\n"
        "FDAI_AZURE_READER_SUBSCRIPTION_ID=stale-subscription\n"
        "FDAI_AZURE_READER_RESOURCE_GROUPS=stale-group\n"
        "FDAI_DEV_OPERATIONS_GATEWAY_URL=https://stale.example.com\n"
        "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=stale-audience\n",
        encoding="utf-8",
    )
    terraform = tmp_path / "terraform"
    terraform.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"output -raw event_bus_kafka_bootstrap"* ]]; then\n'
        "  printf 'example.servicebus.windows.net:9093'\n"
        'elif [[ "$*" == *"output -json event_bus_topics"* ]]; then\n'
        '  printf \'["aw.finops.events","aw.change.events"]\'\n'
        'elif [[ "$*" == *"output -json event_bus_auxiliary_topics"* ]]; then\n'
        '  printf \'["aw.pipeline.stages","aw.inventory.raw"]\'\n'
        'elif [[ "$*" == *"output -raw resource_group_name"* ]]; then\n'
        "  printf 'rg-example'\n"
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
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = repo / ".fdai/local-runtime.env"

    subprocess.run(  # noqa: S603 - resolved binary with test-controlled arguments
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

    values = output.read_text(encoding="utf-8").splitlines()
    assert values == [
        "VITE_MSAL_CLIENT_ID=client",
        "AZURE_TENANT_ID=00000000-0000-0000-0000-000000000002",
        "AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001",
        "AZURE_RESOURCE_GROUP=rg-example",
        "AZURE_REGION=example-region",
        "KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093",
        "KAFKA_TOPIC_EVENTS=aw.change.events",
        "FDAI_STAGE_TOPIC=aw.pipeline.stages",
        "FDAI_PANTHEON_OBJECT_TOPIC=aw.pantheon.objects",
        "FDAI_INVENTORY_RAW_TOPIC=aw.inventory.raw",
        "POSTGRES_HOST=127.0.0.1",
        "POSTGRES_DATABASE=fdai",
        "FDAI_DATABASE_URL=postgresql+psycopg://fdai:devonly@127.0.0.1:5432/fdai",
        "FDAI_STATE_STORE_DSN=postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        "RUNTIME_ENV=dev",
        "AUTONOMY_MODE_DEFAULT=shadow",
        "FDAI_START_CONSUMER=1",
        "FDAI_START_PANTHEON=1",
        "FDAI_RUNTIME_LOCAL_AZURE_CLI=1",
        "FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-developer-a-core",
        "FDAI_PANTHEON_CONSUMER_GROUP_PREFIX=fdai-local-developer-a-pantheon",
        "FDAI_READ_API_CONSUMER_INSTANCE=fdai-local-developer-a-read-api",
        "FDAI_AZURE_READER_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000001",
        "FDAI_AZURE_READER_RESOURCE_GROUPS=rg-example",
        "FDAI_DEV_OPERATIONS_GATEWAY_URL=https://gateway.example.com",
        "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE=api-application-id",
    ]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_omits_inventory_invalidation_topic_until_provisioned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "console").mkdir(parents=True)
    (repo / "infra").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(Path(os.sys.executable))
    (repo / "console/.env.local").write_text(
        "FDAI_INVENTORY_RAW_TOPIC=stale.inventory\n",
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
    assert "FDAI_CORE_CONSUMER_GROUP_ID=fdai-local-developer-b-core" in output.read_text(
        encoding="utf-8"
    )
    assert "invalidation uses TTL refresh" in completed.stderr


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
