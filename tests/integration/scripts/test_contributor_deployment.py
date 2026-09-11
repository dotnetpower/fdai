"""Fresh-contributor Azure deployment contract tests."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_AZD_UP = _ROOT / "scripts/deployment/azure/azd-up.sh"
_GENESIS_UP = _ROOT / "scripts/deployment/azure/genesis-up.sh"
_CONTRIBUTOR_TERRAFORM = _ROOT / "scripts/deployment/azure/contributor-terraform.sh"
_REPO_CONFIG = _ROOT / "scripts/deployment/azure/set-gh-actions-config.sh"
_PRIVATE_ONBOARD = _ROOT / "infra/bootstrap/onboard.sh"
_BASH = shutil.which("bash")
assert _BASH is not None


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="ascii")
    path.chmod(0o755)


def _run_private_onboard(
    tmp_path: Path, configured_name: str
) -> tuple[subprocess.CompletedProcess[str], str, Path]:
    workspace = tmp_path / "workspace"
    bootstrap = workspace / "infra/bootstrap"
    verifier = workspace / "scripts/deployment/azure"
    fake_bin = tmp_path / "bin"
    bootstrap.mkdir(parents=True)
    verifier.mkdir(parents=True)
    fake_bin.mkdir()
    onboard = bootstrap / "onboard.sh"
    onboard.write_text(_PRIVATE_ONBOARD.read_text(encoding="utf-8"), encoding="utf-8")
    onboard.chmod(0o755)
    _write_executable(verifier / "verify-azure-context.sh", "#!/usr/bin/env bash\nexit 0\n")
    calls = tmp_path / "state-calls"
    _write_executable(
        bootstrap / "create-state-account.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ $# -eq 0 ]]; then
    name=stgenerated
    printf '%s\n' generated >> "$FAKE_STATE_CALLS"
else
    name="$1"
    printf '%s\n' "$name" >> "$FAKE_STATE_CALLS"
fi
printf 'state_storage_account_name = "%s"\n' "$name"
""",
    )
    _write_executable(
        fake_bin / "terraform",
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
    "output -raw backend_config_hint") printf '%s\n' backend-hint ;;
    "output -raw ops_vnet_id") printf '%s\n' vnet-id ;;
    "output -raw ops_vnet_name") printf '%s\n' vnet-name ;;
    "output -raw ops_resource_group_name") printf '%s\n' rg-ops ;;
    "output -raw deploy_runner_client_id") printf '%s\n' client-id ;;
    "output -raw deploy_runner_principal_id") printf '%s\n' principal-id ;;
esac
""",
    )
    tfvars = bootstrap / "bootstrap.tfvars"
    tfvars.write_text(
        f'env = "dev"\nstate_storage_account_name = "{configured_name}"\n',
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_STATE_CALLS": str(calls),
        "AZURE_SUBSCRIPTION_ID": "sub-expected",
        "AZURE_TENANT_ID": "tenant-expected",
    }
    result = subprocess.run(  # noqa: S603 - controlled copied repository script
        [str(onboard)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text(encoding="ascii"), tfvars


def test_public_deployment_is_staged_and_keeps_sensitive_state_private() -> None:
    source = _AZD_UP.read_text(encoding="utf-8")
    main = source.split("for command_name in az azd curl date flock git", maxsplit=1)[1]
    gitignore = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerignore = (_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    genesis_wrapper = _GENESIS_UP.read_text(encoding="utf-8")

    assert "secrets/" in gitignore
    assert "secrets/" in dockerignore
    assert genesis_wrapper.index("umask 077") < genesis_wrapper.index(
        'exec "$ROOT/.venv/bin/python"'
    )
    assert "exec uv run --frozen --project" in genesis_wrapper
    assert 'resource_provider_registrations = "none"' in (_ROOT / "infra/versions.tf").read_text(
        encoding="utf-8"
    )
    assert 'backend": {' in source and '"local": {' in source
    assert 'install -d -m 0700 "$WORK_DIR"' in source
    assert "os.open(destination, flags, 0o600)" in source
    assert 'git -C "$REPO_ROOT" archive "$SOURCE_COMMIT"' in source
    assert "services/assets/resolved-models.json" in source
    assert '--image "fdai-core-control-plane:$tag"' in source
    assert 'CORE_IMAGE="$login_server/fdai-core-control-plane@$digest"' in source
    assert 'private_key="$REPO_ROOT/secrets/license-signing-key.pem"' in source
    assert "--all-capabilities" in source
    assert "--valid-days 30" in source
    assert 'secret_name="fdai-license-$LICENSE_TOKEN_REVISION"' in source
    assert '--name "$secret_name"' in source
    assert "--name fdai-capability-license" not in source
    assert '--file "$LICENSE_TOKEN_FILE"' in source
    assert "az keyvault secret set" in source
    assert 'payload["license"]' in source
    license_function = source.split("prepare_capability_license() {", maxsplit=1)[1].split(
        "\n}\n\nopen_migration_firewall", maxsplit=1
    )[0]
    assert "--value" not in license_function
    assert "FDAI_LICENSE_TOKEN" not in license_function
    assert "observation-only Trial mode" in license_function
    assert 'terraform -chdir="$PLATFORM_ROOT" state list >/dev/null' in source
    assert "for _ in $(seq 1 6); do" in source
    assert "export TF_VAR_enable_legacy_oob_job=false" in source
    assert 'export TF_VAR_operational_history_lifecycle_cron_expression=""' in source
    assert "verify_bootstrap_image" not in source
    assert "FDAI_AZD_BOOTSTRAP_CORE_IMAGE" not in source
    assert "FDAI_MATERIALIZE_AUTHORITATIVE_CATALOGS=1" in source
    assert 'terraform -chdir="$CORE_ROOT" plan' in source
    assert 'terraform -chdir="$CORE_ROOT" apply' in source
    deploy_core = source.split("deploy_core() {", maxsplit=1)[1].split(
        "\n}\n\nwait_for_core", maxsplit=1
    )[0]
    assert deploy_core.index('rm -f -- "$tfvars_tmp"') < deploy_core.index(
        'python3 - "$platform_input" "$tfvars_tmp"'
    )
    assert 'open(sys.argv[2], "x"' in deploy_core
    assert deploy_core.index('open(sys.argv[2], "x"') < deploy_core.index(
        'mv -f -- "$tfvars_tmp" "$CORE_TFVARS"'
    )
    assert 'run_job "$canary_job" "canary" 180' in source
    assert 'run_job "$inventory_job" "inventory" 1800' in source
    assert "azd up" not in main
    assert 'source "$HERE/contributor-target.sh"' in source
    assert 'source "$HERE/contributor-terraform.sh"' in source
    assert 'prepare_contributor_terraform "$REPO_ROOT" "$WORK_DIR"' in source
    assert 'PLATFORM_STATE="$REPO_ROOT/.azure/$AZD_ENVIRONMENT/infra/terraform.tfstate"' in source
    assert 'ensure_contributor_azd_login "$TARGET_HAS_TERMINAL" "$EXPECTED_TENANT"' in source
    assert source.count('TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE"') == 4
    assert '"$HERE/resource_provider_reconcile.py"' in source
    assert "--profile application" in source
    assert "FDAI_RESOURCE_PROVIDER_TIMEOUT_SECONDS must be from 30 through 1800" in source
    assert "az provider register" not in source
    assert 'verify_private_state_file "$PLATFORM_STATE" "platform apply"' in source
    assert 'verify_private_state_file "$CORE_STATE" "Core apply"' in source
    assert "stat -c '%a:%u'" in source

    assert main.index("ensure_resource_providers") < main.index("resolve_models")
    assert main.index("resolve_models") < main.index("platform_preview")
    assert main.index("platform_apply") < main.index("build_core_image")
    assert main.index("build_core_image") < main.index("prepare_capability_license")
    assert main.index("prepare_capability_license") < main.index("bootstrap_database")
    assert main.index("bootstrap_database") < main.index("deploy_core")
    assert main.index("deploy_core") < main.index("set_scheduled_jobs true")
    assert main.index("set_scheduled_jobs true") < main.rindex("platform_apply")
    assert main.rindex("platform_apply") < main.index("wait_for_core")

    orchestrator = (_ROOT / "scripts/deployment/azure/genesis_orchestrator.py").read_text(
        encoding="utf-8"
    )
    assert '"FDAI_AZD_CONFIRM": "0"' in orchestrator
    assert '"FDAI_AZD_CONFIRM": "1"' not in orchestrator
    assert "public_exact_plan_approval_required" in orchestrator


def test_public_deployment_pins_azd_to_the_committed_provider_lock() -> None:
    helper = _CONTRIBUTOR_TERRAFORM.read_text(encoding="utf-8")
    parameter_template = _ROOT / "infra/main.tfvars.json"
    gitignore = (_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert parameter_template.read_text(encoding="utf-8") == "{}\n"
    assert "!infra/main.tfvars.json" in gitignore
    assert "-lockfile=readonly" in helper
    assert "providers mirror" in helper
    assert 'stream.write("provider_installation {\\n  direct {}\\n}\\n")' in helper
    assert 'export TF_CLI_CONFIG_FILE="$bootstrap_config"' in helper
    assert 'exclude = ["registry.terraform.io/*/*"]' in helper
    assert "-backend=false -input=false -upgrade" in helper
    assert helper.count("-upgrade -lockfile=readonly") == 2
    assert 'platform_lock="$platform_root/.terraform.lock.hcl"' in helper
    assert 'core_lock="$core_root/.terraform.lock.hcl"' in helper
    assert 'platform_mirror="$mirror_root/platform"' in helper
    assert 'core_mirror="$mirror_root/core"' in helper
    assert 'export PLATFORM_TF_CLI_CONFIG_FILE="$platform_config"' in helper
    assert 'export CORE_TF_CLI_CONFIG_FILE="$core_config"' in helper
    assert 'export TF_CLI_CONFIG_FILE="$PLATFORM_TF_CLI_CONFIG_FILE"' in helper
    assert 'sha256sum "$platform_lock"' in helper
    assert 'sha256sum "$core_lock"' in helper


def test_contributor_provider_mirror_is_restart_safe(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    infra = repository / "infra"
    infra.mkdir(parents=True)
    (infra / ".terraform.lock.hcl").write_text("locked\n", encoding="ascii")
    core = infra / "services/core-control-plane"
    core.mkdir(parents=True)
    (core / ".terraform.lock.hcl").write_text("core-locked\n", encoding="ascii")
    work_dir = tmp_path / "work"
    work_dir.mkdir(mode=0o700)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "terraform-calls"
    _write_executable(
        fake_bin / "terraform",
        """#!/usr/bin/env bash
set -euo pipefail
mode=direct
grep -q filesystem_mirror "$TF_CLI_CONFIG_FILE" && mode=mirror
printf '%s|%s\n' "$mode" "$*" >> "$FAKE_TERRAFORM_CALLS"
""",
    )
    command = """
set -euo pipefail
source "$1"
prepare_contributor_terraform "$2" "$3"
prepare_contributor_terraform "$2" "$3"
"""

    result = subprocess.run(  # noqa: S603 - controlled helper and fake executable
        [
            _BASH,
            "-c",
            command,
            "bash",
            str(_CONTRIBUTOR_TERRAFORM),
            str(repository),
            str(work_dir),
        ],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_TERRAFORM_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = calls.read_text(encoding="ascii").splitlines()
    modes = [line.split("|", maxsplit=1)[0] for line in invocations]
    assert modes == [
        "direct",
        "direct",
        "direct",
        "direct",
        "mirror",
        "mirror",
        "direct",
        "direct",
        "direct",
        "direct",
        "mirror",
        "mirror",
    ]
    assert sum("services/core-control-plane" in line for line in invocations) == 6
    platform_configs = list(work_dir.glob("terraformrc-platform-*"))
    core_configs = list(work_dir.glob("terraformrc-core-*"))
    assert len(platform_configs) == len(core_configs) == 1
    platform_config = platform_configs[0].read_text(encoding="utf-8")
    core_config = core_configs[0].read_text(encoding="utf-8")
    assert '/platform"' in platform_config and '/core"' not in platform_config
    assert '/core"' in core_config and '/platform"' not in core_config


def test_post_deploy_jobs_track_only_the_new_execution() -> None:
    source = _AZD_UP.read_text(encoding="utf-8")
    run_job = source.split("run_job() {", maxsplit=1)[1].split(
        "\n}\n\nfor command_name", maxsplit=1
    )[0]

    first_list = run_job.index("az containerapp job execution list")
    start = run_job.index("az containerapp job start")
    second_list = run_job.index("az containerapp job execution list", first_list + 1)
    assert first_list < start < second_list
    assert "prior_executions" in run_job
    assert "(${#discovered[@]} == 1)" in run_job
    assert "Job start produced ambiguous executions" in run_job
    assert "--no-wait" not in run_job


def test_platform_exports_complete_public_core_handoff() -> None:
    outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
    block = outputs.split('output "contributor_core_service_tfvars"', maxsplit=1)[1]
    block = block.split('\noutput "dev_operations_gateway_url"', maxsplit=1)[0]

    for required in (
        "name",
        "image",
        "platform",
        "bootstrap",
        "identity",
        "rca_reader_identity",
        "event_topics",
        "database",
        "rollback",
        "runtime_env",
        "llm",
        "observation_context",
        "decision_evidence_container_url",
        "tags",
    ):
        assert required in block
    assert 'var.env == "dev"' in block
    assert "!var.enable_private_networking" in block
    assert "var.enable_llm" in block
    assert 'output "container_registry_name"' in outputs
    assert 'output "inventory_job_name"' in outputs


def test_global_name_suffix_is_opt_in_and_applied_to_shared_names() -> None:
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    main = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")

    suffix = variables.split('variable "resource_name_suffix"', maxsplit=1)[1].split(
        '\nvariable "enable_llm"', maxsplit=1
    )[0]
    assert 'default     = ""' in suffix
    assert "^[a-z0-9]{6}$" in suffix
    assert re.search(
        r'global_name_suffix\s*=\s*var\.resource_name_suffix == "" \? ""',
        main,
    )
    for prefix in ("cr", "kv-", "evhns-", "psql-", "oai-", "aif-"):
        assert prefix in main
    assert main.count("local.global_name_suffix") >= 12


def test_private_foundation_creates_both_state_containers_through_arm() -> None:
    foundation = (_ROOT / "infra/genesis-foundation/main.tf").read_text(encoding="utf-8")
    helper = (_ROOT / "infra/bootstrap/create-state-account.sh").read_text(encoding="utf-8")

    assert 'for_each = toset(["deployment-plans", "tfstate"])' in foundation
    assert (
        'type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"'
    ) in foundation
    assert "for container in tfstate deployment-plans" in helper
    assert "/blobServices/default/containers/${container}?api-version=2023-05-01" in helper
    assert "az storage container" not in helper
    assert "existing state storage account is not owned by FDAI ops bootstrap" in helper


def test_private_onboarding_reuses_the_configured_state_account(tmp_path: Path) -> None:
    result, calls, tfvars = _run_private_onboard(tmp_path, "stexisting")

    assert result.returncode == 0, result.stderr
    assert calls == "stexisting\n"
    assert 'state_storage_account_name = "stexisting"' in tfvars.read_text(encoding="utf-8")
    assert tfvars.stat().st_mode & 0o777 == 0o600


def test_private_onboarding_replaces_the_example_placeholder(tmp_path: Path) -> None:
    result, calls, tfvars = _run_private_onboard(tmp_path, "st....")

    assert result.returncode == 0, result.stderr
    assert calls == "generated\n"
    content = tfvars.read_text(encoding="utf-8")
    assert 'state_storage_account_name = "stgenerated"' in content
    assert "st...." not in content


def test_repository_configuration_sets_complete_foundation_coordinates(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "gh-calls"
    _write_executable(
        fake_bin / "az",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "account show" ]]; then
  if [[ " $* " == *" --subscription "* ]]; then
    printf '%s\\n%s\\n' sub-expected tenant-expected
  else
    printf '%s\\n' tenant-expected
  fi
elif [[ "$1 $2" == "account set" ]]; then
  exit 0
elif [[ "$1 $2" == "group show" ]]; then
  exit 1
else
  exit 64
fi
""",
    )
    _write_executable(
        fake_bin / "terraform",
        """#!/usr/bin/env bash
set -euo pipefail
key="${!#}"
case "$key" in
  ops_resource_group_name) printf '%s\\n' rg-example-ops ;;
  state_container_name) printf '%s\\n' tfstate ;;
  app_resource_group_name) printf '%s\\n' rg-example-dev ;;
  region) printf '%s\\n' koreacentral ;;
  region_short) printf '%s\\n' krc ;;
    ops_vnet_id)
        value="/subscriptions/example/resourceGroups/rg-example-ops/providers"
        echo "$value/Microsoft.Network/virtualNetworks/vnet-example"
        ;;
  ops_vnet_name) printf '%s\\n' vnet-example ;;
  state_storage_account_name) printf '%s\\n' stexample ;;
  deploy_runner_client_id) printf '%s\\n' 00000000-0000-0000-0000-000000000001 ;;
  deploy_runner_principal_id) printf '%s\\n' 00000000-0000-0000-0000-000000000002 ;;
  *) exit 64 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_executable(
        fake_bin / "gh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_GH_CALLS"
if [[ "$1 $2" == "secret list" ]]; then
  exit 0
fi
if [[ "$1 $2" == "secret set" ]]; then
  cat >/dev/null
fi
""",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_GH_CALLS": str(calls),
        "AZURE_SUBSCRIPTION_ID": "sub-expected",
        "AZURE_TENANT_ID": "tenant-expected",
    }

    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_REPO_CONFIG), "Example/Repo", "sub-expected", "tenant-expected"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = calls.read_text(encoding="ascii")
    assert "set STATE_RESOURCE_GROUP -R Example/Repo -b rg-example-ops" in invocations
    assert "set STATE_CONTAINER -R Example/Repo -b tfstate" in invocations
    assert "set MODEL_RESOLVER_DEPLOYER_OBJECT_ID -R Example/Repo" in invocations
    assert "set DEV_DEPLOY_REQUIRED_APPROVALS -R Example/Repo -b 0" in invocations
    assert "ghcr.io/example/repo/fdai-core-control-plane:sha-" in invocations


def test_database_bootstrap_materializes_catalogs_only_when_requested() -> None:
    source = (_ROOT / "scripts/deployment/azure/bootstrap-service-migrations.sh").read_text(
        encoding="utf-8"
    )

    assert 'materialize_catalogs="${FDAI_MATERIALIZE_AUTHORITATIVE_CATALOGS:-0}"' in source
    assert "FDAI_MATERIALIZE_AUTHORITATIVE_CATALOGS must be 0 or 1" in source
    assert source.index('for service in "${migration_services[@]}"') < source.index(
        "materialize-authoritative-catalogs.py"
    )
