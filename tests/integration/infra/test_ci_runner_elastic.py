"""Contracts for the ephemeral Container Apps Job CI runner."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra" / "ci-runner-aca"
TERRAFORM = (INFRA / "main.tf").read_text(encoding="utf-8")
VARIABLES = (INFRA / "variables.tf").read_text(encoding="utf-8")
ENTRYPOINT = (INFRA / "entrypoint.sh").read_text(encoding="utf-8")
DOCKERFILE = (INFRA / "Dockerfile").read_text(encoding="utf-8")


def _workflow() -> dict[str, dict[str, object]]:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def test_elastic_job_runs_eight_shards_on_main_only_behind_the_source_guard() -> None:
    workflow = _workflow()
    hosted = workflow["jobs"]["python-tests"]
    elastic = workflow["jobs"]["python-tests-elastic"]
    assert elastic["runs-on"] == ["self-hosted", "Linux", "X64", "fdai-ci", "fdai-ci-aca"]
    assert elastic["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert elastic["strategy"]["max-parallel"] == 8
    assert elastic["env"]["FDAI_PYTEST_SHARD_COUNT"] == "8"
    assert elastic["env"]["FDAI_PYTEST_SHARD_INDEX"] == "${{ matrix.shard }}"
    assert elastic["steps"] == hosted["steps"]
    assert "protected-ci-source" in elastic["needs"]
    assert " ".join(elastic["if"].split()) == (
        "needs.changes.outputs.python == 'true' && "
        "vars.FDAI_CI_ELASTIC_RUNNER_ENABLED == 'true' && "
        "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
    )
    assert "python-tests-elastic" in workflow["jobs"]["required"]["needs"]


def test_every_routing_choice_is_exclusive_and_hosted_remains_the_fallback() -> None:
    jobs = _workflow()["jobs"]
    hosted = " ".join(jobs["python-tests"]["if"].split())
    ssd = " ".join(jobs["python-tests-ssd"]["if"].split())
    guard = " ".join(jobs["protected-ci-source"]["if"].split())
    assert "FDAI_CI_ELASTIC_RUNNER_ENABLED != 'true'" in hosted
    assert "FDAI_CI_ELASTIC_RUNNER_ENABLED != 'true'" in ssd
    assert "FDAI_CI_ELASTIC_RUNNER_ENABLED == 'true'" in guard
    assert "FDAI_CI_SSD_RUNNER_ENABLED == 'true'" in guard
    assert "github.event_name == 'pull_request'" in hosted


def test_terraform_scales_on_queued_jobs_with_a_hard_ceiling() -> None:
    assert 'custom_rule_type = "github-runner"' in TERRAFORM
    assert "min_executions              = 0" in TERRAFORM
    assert "max_executions              = var.max_executions" in TERRAFORM
    assert 'targetWorkflowQueueLength = "1"' in TERRAFORM
    assert "replica_retry_limit          = 0" in TERRAFORM
    assert "var.max_executions <= 64" in VARIABLES
    assert "!endswith(var.runner_image" in VARIABLES


def test_terraform_never_holds_the_github_credential_or_deployment_authority() -> None:
    assert 'value = "unset"' in TERRAFORM
    assert "ignore_changes = [secret]" in TERRAFORM
    assert "admin_enabled       = false" in TERRAFORM
    assert 'principal_type       = "ServicePrincipal"' in TERRAFORM
    assert TERRAFORM.count("azurerm_role_assignment") == 2
    assert 'role_definition_name = "AcrPull"' in TERRAFORM
    assert "key_vault" not in TERRAFORM
    assert "azurerm_virtual_network_peering" not in TERRAFORM
    assert not re.search(r"github[_-]?(pat|token)\s*=\s*\"[^\"]+\"", TERRAFORM, re.I)
    assert 'backend "local" {}' in (INFRA / "versions.tf").read_text(encoding="utf-8")


def test_entrypoint_hides_the_credential_from_workflow_code() -> None:
    assert "unset GITHUB_RUNNER_CREDENTIAL" in ENTRYPOINT
    assert "--ephemeral" in ENTRYPOINT
    assert ENTRYPOINT.index("unset GITHUB_RUNNER_CREDENTIAL") < ENTRYPOINT.index("./config.sh")
    assert ENTRYPOINT.index("verify-toolchain.py") < ENTRYPOINT.index("registration-token")
    assert "exec runuser -u runner -- env -i" in ENTRYPOINT
    assert "--token" not in ENTRYPOINT
    assert "set -x" not in ENTRYPOINT
    subprocess.run(  # noqa: S603 - syntax check of tracked scripts
        ["/usr/bin/bash", "-n", str(INFRA / "entrypoint.sh")], check=True
    )


def test_image_is_built_from_the_declared_toolchain_with_a_pinned_runner() -> None:
    assert (
        "COPY toolchain.json verify-toolchain.py provision-toolchain.sh /opt/fdai-ci/" in DOCKERFILE
    )
    assert "/opt/fdai-ci/provision-toolchain.sh" in DOCKERFILE
    assert "sha256sum --check --strict" in DOCKERFILE
    assert re.search(r"RUNNER_SHA256=[a-f0-9]{64}", DOCKERFILE)
    assert "USER " not in DOCKERFILE
    build = (INFRA / "build-image.sh").read_text(encoding="utf-8")
    assert "infra/ci-runner" in build and "az acr build" in build
    subprocess.run(  # noqa: S603 - syntax check of tracked scripts
        ["/usr/bin/bash", "-n", str(INFRA / "build-image.sh")], check=True
    )


def test_credential_script_never_places_the_secret_in_arguments_or_terraform() -> None:
    script = (INFRA / "set-credential.sh").read_text(encoding="utf-8")
    assert "read -rsp" in script
    assert "chmod 0600" in script and "trap 'rm -f" in script
    assert "[[ -t 0 ]]" in script
    assert "--secrets" not in script and "set -x" not in script
    assert "az rest --method patch" in script and '"@${body}"' in script
    subprocess.run(  # noqa: S603 - syntax check of tracked scripts
        ["/usr/bin/bash", "-n", str(INFRA / "set-credential.sh")], check=True
    )
