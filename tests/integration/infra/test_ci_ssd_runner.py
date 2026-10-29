"""Contracts for the isolated, opt-in SSD CI host."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra" / "ci-runner"
SPEC = importlib.util.spec_from_file_location("ci_runner_register", INFRA / "register.py")
assert SPEC is not None and SPEC.loader is not None
REGISTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTER)
_ELIGIBLE = (
    "vars.FDAI_CI_ELASTIC_RUNNER_ENABLED != 'true' && "
    "vars.FDAI_CI_SSD_RUNNER_ENABLED == 'true' && "
    "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
)


def test_workflow_routes_all_main_regression_shards_without_moving_prs() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["python-tests"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert " ".join(job["if"].split()) == (
        "needs.changes.outputs.python == 'true' && "
        "((vars.FDAI_CI_ELASTIC_RUNNER_ENABLED != 'true' && "
        "vars.FDAI_CI_SSD_RUNNER_ENABLED != 'true') || "
        "github.ref != 'refs/heads/main' || github.event_name == 'pull_request')"
    )
    ssd = workflow["jobs"]["python-tests-ssd"]
    assert ssd["runs-on"] == ["self-hosted", "Linux", "X64", "fdai-ci", "fdai-ci-ssd"]
    assert ssd["env"]["FDAI_PYTEST_MAX_WORKERS"] == "3"
    assert ssd["env"]["FDAI_PYTEST_SHARD_INDEX"] == "${{ matrix.shard }}"
    assert ssd["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert ssd["strategy"]["max-parallel"] == 4
    assert ssd["steps"] == job["steps"]
    assert " ".join(ssd["if"].split()) == ("needs.changes.outputs.python == 'true' && " + _ELIGIBLE)
    assert "protected-ci-source" in ssd["needs"]
    assert "python-tests-ssd" in workflow["jobs"]["required"]["needs"]
    assert workflow["jobs"]["python-coverage-shards"]["runs-on"] == "ubuntu-24.04"
    assert workflow["jobs"]["db-integration"]["runs-on"] == "ubuntu-24.04"


def test_vm_has_no_deployment_identity_or_network_access() -> None:
    source = (INFRA / "main.tf").read_text()
    assert 'resource "azurerm_resource_group" "ci"' in source
    assert 'resource "azurerm_virtual_network" "ci"' in source
    assert "identity {" not in source
    assert "azurerm_role_assignment" not in source
    assert "azurerm_virtual_network_peering" not in source
    assert "public_ip_address_id" not in source.split('resource "azurerm_network_interface"')[1]
    assert 'name                       = "DenyAllInbound"' in source
    assert 'destination_address_prefix = "VirtualNetwork"' in source
    assert 'storage_account_type = "Premium_LRS"' in source
    assert "disk_size_gb         = 256" in source
    assert "ip_tags             = var.egress_ip_tags" in source
    assert "registrationToken" not in source
    assert 'backend "local" {}' in (INFRA / "versions.tf").read_text()


def test_scanner_exception_keeps_the_subnet_nsg_and_vm_dependency() -> None:
    source = (INFRA / "main.tf").read_text()
    binding = source.split('resource "azurerm_subnet_network_security_group_association" "ci" {')[1]
    binding = binding.split("}", 1)[0]
    assert "subnet_id                 = azurerm_subnet.ci.id" in binding
    assert "network_security_group_id = azurerm_network_security_group.ci.id" in binding
    nic = source.split('resource "azurerm_network_interface" "ci" {')[1].split(
        'resource "azurerm_linux_virtual_machine"', 1
    )[0]
    assert "subnet_id                     = azurerm_subnet.ci.id" in nic
    vm = source.split('resource "azurerm_linux_virtual_machine" "ci" {')[1]
    assert "azurerm_subnet_network_security_group_association.ci," in vm
    assert '#trivy:ignore:AZU-0068\nresource "azurerm_network_interface" "ci"' in source


def test_bootstrap_uses_checked_archive_and_refuses_missing_scratch_mount() -> None:
    document = yaml.safe_load((INFRA / "cloud-init.yaml.tftpl").read_text())
    scripts = {entry["path"]: entry["content"] for entry in document["write_files"]}
    storage = scripts["/usr/local/sbin/fdai-ci-storage"]
    assert "findmnt -rn -o TARGET --target /mnt" in storage
    assert "refusing root-disk fallback" in storage
    bootstrap = scripts["/opt/fdai-ci/bootstrap.sh"]
    assert "sha256sum --check --status" in bootstrap
    assert bootstrap.index("sha256sum") < bootstrap.index("tar -xzf")
    assert "fdai-deploy" not in bootstrap
    assert "az login" not in bootstrap
    for script in scripts.values():
        subprocess.run(["/usr/bin/bash", "-n"], input=script, text=True, check=True)


def test_registration_token_is_only_in_protected_parameters() -> None:
    payload = REGISTER.command_payload(
        "example/repository", "vm-example-ci", "westus3", "test-token"
    )
    assert payload["properties"]["protectedParameters"] == [
        {"name": "ACTIONS_RUNNER_INPUT_TOKEN", "value": "test-token"}
    ]
    assert "test-token" not in json.dumps(payload["properties"]["source"])
    script = payload["properties"]["source"]["script"]
    assert "--token" not in script
    assert "$1" not in script
    assert "ACTIONS_RUNNER_INPUT_TOKEN" in script
    assert "unset ACTIONS_RUNNER_INPUT_TOKEN" in script
    assert "--labels fdai-ci,fdai-ci-ssd" in script
    assert "--replace" not in script
    assert '--work "$work"' in script
    assert 'work="/mnt/fdai-ci/work$suffix"' in script
    assert 'tools="/mnt/fdai-ci/toolcache$suffix"' in script
    assert '"ExecStartPre=+$storage"' in script
    assert "ulimit -c 0" in script
    assert "LimitCORE=0" in script
    assert '"$runner_home/_diag"' in script
    assert "CPUQuota=300% MemoryHigh=10G MemoryMax=12G TasksMax=8192" in script
    assert "./svc.sh stop" not in script
    assert "./config.sh remove" not in script
    subprocess.run(["/usr/bin/bash", "-n"], input=script, text=True, check=True)


@pytest.mark.parametrize("parallelism", [0, -1, 6, 100])
def test_registration_rejects_unbounded_parallelism(parallelism: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        REGISTER.registration_script("example/repository", "vm-example-ci", parallelism)


def test_five_slots_have_separate_distribution_and_disposable_state() -> None:
    script = REGISTER.registration_script("example/repository", "vm-example-ci", 5)
    assert "for slot in $(seq 1 5)" in script
    assert 'runner_home="/opt/actions-runner$suffix"' in script
    assert 'runner_name="vm-example-ci$suffix"' in script
    assert 'cache="/mnt/fdai-ci/cache$suffix"' in script
    assert "cp -a /opt/actions-runner/bin /opt/actions-runner/externals" in script
    assert "/opt/actions-runner/.credentials" not in script
    assert "/opt/actions-runner/.runner" not in script
    assert "Existing runner configuration does not match" in script
    assert 'if ! systemctl is-active --quiet "$service_name"' in script
    assert "FDAI_CI_RUNNER_REGISTERED slots=5" in script
    assert "$(nproc) < 16" in script
    assert "65011712" in script  # 62 GiB reserves 2 GiB beyond five 12-GiB limits.
    subprocess.run(["/usr/bin/bash", "-n"], input=script, text=True, check=True)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("matches", [True, False])
def test_existing_slot_validation_accepts_runner_bom_without_replacing_wrong_target(
    tmp_path: Path,
    encoding: str,
    matches: bool,
) -> None:
    script = REGISTER.registration_script("example/repository", "vm-example-ci", 5)
    validator = script.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    (tmp_path / ".runner").write_text(
        json.dumps(
            {
                "agentName": "vm-example-ci" if matches else "vm-other-ci",
                "gitHubUrl": "https://github.com/example/repository",
            }
        ),
        encoding=encoding,
    )
    result = subprocess.run(  # noqa: S603 - repository-owned validator with synthetic coordinates
        [sys.executable, "-c", validator, "vm-example-ci"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is matches, result.stderr


@pytest.mark.parametrize(
    ("busy", "labels", "message"),
    [
        (True, ["fdai-ci", "fdai-ci-ssd"], "is busy"),
        (False, ["fdai-deploy"], "isolated CI pool"),
        (False, ["fdai-ci", "fdai-ci-ssd", "fdai-deploy-candidate"], "isolated CI pool"),
    ],
)
def test_registration_does_not_change_busy_or_deployment_runners(
    monkeypatch: pytest.MonkeyPatch,
    busy: bool,
    labels: list[str],
    message: str,
) -> None:
    responses = iter(
        [
            {"id": "test-subscription"},
            {"approval_policy": "all_external_contributors"},
            {"identity": None},
            {
                "runners": [
                    {
                        "name": "vm-example-ci",
                        "busy": busy,
                        "labels": [{"name": label} for label in labels],
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(REGISTER, "_json_command", lambda _: next(responses))
    monkeypatch.setattr(
        "sys.argv",
        [
            "register.py",
            "--repository",
            "example/repository",
            "--resource-group",
            "rg-example-ci",
            "--vm-name",
            "vm-example-ci",
            "--subscription",
            "test-subscription",
            "--parallelism",
            "5",
        ],
    )
    with pytest.raises(SystemExit, match=message):
        REGISTER.main()


@pytest.mark.parametrize(
    "url",
    ["http://management.azure.com/test", "https://example.com/test", "file:///etc/passwd"],
)
def test_registration_rejects_non_azure_token_destinations(url: str) -> None:
    with pytest.raises(ValueError, match="Azure management HTTPS endpoint"):
        REGISTER._request(url, "test-bearer")


@pytest.mark.parametrize(
    ("repository", "vm_name"),
    [
        ("bad;command/repository", "vm-example-ci"),
        ("example/repository", "vm-example;command"),
        ("example/repository/extra", "vm-example-ci"),
    ],
)
def test_registration_rejects_shell_metacharacters(repository: str, vm_name: str) -> None:
    with pytest.raises(ValueError):
        REGISTER.registration_script(repository, vm_name)


def test_registration_stops_before_minting_a_token_for_a_vm_with_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    responses = iter(
        [
            {"id": "test-subscription"},
            {"approval_policy": "all_external_contributors"},
            {"identity": {"type": "UserAssigned"}},
        ]
    )

    def command(arguments: list[str]) -> object:
        calls.append(arguments)
        return next(responses)

    monkeypatch.setattr(REGISTER, "_json_command", command)
    monkeypatch.setattr(
        "sys.argv",
        [
            "register.py",
            "--repository",
            "example/repository",
            "--resource-group",
            "rg-example-ci",
            "--vm-name",
            "vm-example-ci",
            "--subscription",
            "test-subscription",
        ],
    )
    with pytest.raises(SystemExit, match="must not have a managed identity"):
        REGISTER.main()
    assert not any("registration-token" in " ".join(call) for call in calls)


@pytest.mark.parametrize(
    "policy", ["first_time_contributors", "first_time_contributors_new_to_github"]
)
def test_registration_requires_approval_for_all_external_contributors(
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    responses = iter([{"id": "test-subscription"}, {"approval_policy": policy}])
    monkeypatch.setattr(REGISTER, "_json_command", lambda _: next(responses))
    monkeypatch.setattr(
        "sys.argv",
        [
            "register.py",
            "--repository",
            "example/repository",
            "--resource-group",
            "rg-example-ci",
            "--vm-name",
            "vm-example-ci",
            "--subscription",
            "test-subscription",
        ],
    )
    with pytest.raises(SystemExit, match="all external contributors"):
        REGISTER.main()
