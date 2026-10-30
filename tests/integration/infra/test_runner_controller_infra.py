"""Offline infrastructure and credential-boundary contracts for the PAT controller."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import urllib.error
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra" / "ci-runner-controller"
APP_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci"
    "/providers/Microsoft.App/containerApps/ca-example-controller"
)


def source(name: str) -> str:
    return (INFRA / name).read_text(encoding="utf-8")


def block(text: str, kind: str, *names: str) -> str:
    opening = kind + "".join(f' "{name}"' for name in names) + " {"
    start = text.index(opening) + len(opening)
    depth = 1
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|#[^\n]*|//[^\n]*|[{}]', text[start:]):
        if token[0] == "{":
            depth += 1
        elif token[0] == "}":
            depth -= 1
            if depth == 0:
                return text[start : start + token.start()]
    raise AssertionError(f"Unclosed block: {opening}")


def assignment(text: str, name: str, value: str) -> None:
    assert re.search(rf"(?m)^\s*{name}\s*=\s*{re.escape(value)}\s*$", text)


def test_controller_and_workers_have_separate_environment_state_and_identity() -> None:
    main = source("main.tf")
    controller = source("controller.tf")
    jobs = source("jobs.tf")
    for side in ("controller", "workers"):
        environment = block(main, "resource", "azurerm_container_app_environment", side)
        assignment(environment, "resource_group_name", f"azurerm_resource_group.{side}.name")
        assignment(
            environment,
            "log_analytics_workspace_id",
            f"azurerm_log_analytics_workspace.{side}.id",
        )
    assignment(
        controller,
        "managedEnvironmentId",
        "azurerm_container_app_environment.controller.id",
    )
    assignment(jobs, "container_app_environment_id", "azurerm_container_app_environment.workers.id")
    assert "azurerm_user_assigned_identity.controller" not in jobs
    assert "azurerm_user_assigned_identity.worker_pull" not in controller
    for text in (main, controller, jobs):
        assert not re.search(r"\b(volume|volume_mounts|storage)\s*\{", text)
    assert 'backend "local" {}' in source("versions.tf")
    assert 'resource_provider_registrations = "none"' in source("versions.tf")


def test_manual_jobs_exclusively_use_broker_and_immutable_image() -> None:
    jobs = source("jobs.tf")
    assignment(jobs, "for_each", "local.jobs")
    assignment(jobs, "image", "var.worker_image")
    assignment(jobs, "replica_retry_limit", "0")
    assert "manual_trigger_config {" in jobs
    assert "event_trigger_config" not in jobs
    assert "schedule_trigger_config" not in jobs
    assert "secret {" not in jobs
    assert "secret_name" not in jobs
    assert not re.search(
        r"\b(PAT|GITHUB_TOKEN|GITHUB_RUNNER_CREDENTIAL)\b", re.sub(r"#.*", "", jobs)
    )
    assignment(jobs, "command", '["/usr/bin/python3", "/opt/fdai-ci/broker-entrypoint.py"]')
    assert 'control = "caj-${var.name}-control"' in source("main.tf")
    assert 'general = "caj-${var.name}-general"' in source("main.tf")
    for name in ("worker_image", "controller_image"):
        image = block(source("variables.tf"), "variable", name)
        assert "@sha256:[0-9a-f]{64}$" in image
        assert "var.registry_server" in image
        assert "default" not in image
    assert 'resource "azurerm_container_registry"' not in "".join(
        path.read_text(encoding="utf-8") for path in INFRA.glob("*.tf")
    )


def test_custom_roles_are_exact_and_cannot_stop_drain_or_assign_authority() -> None:
    identity = source("identity.tf")
    expected = {
        "jobs": {
            "Microsoft.App/jobs/read",
            "Microsoft.App/jobs/start/action",
            "Microsoft.App/jobs/executions/read",
        },
        "vm_workers": {
            "Microsoft.Compute/virtualMachines/read",
            "Microsoft.Compute/virtualMachines/write",
            "Microsoft.Compute/virtualMachines/delete",
            "Microsoft.Compute/virtualMachines/instanceView/read",
            "Microsoft.Compute/disks/read",
            "Microsoft.Compute/disks/write",
            "Microsoft.Compute/disks/delete",
            "Microsoft.Network/networkInterfaces/read",
            "Microsoft.Network/networkInterfaces/write",
            "Microsoft.Network/networkInterfaces/delete",
            "Microsoft.Network/networkInterfaces/join/action",
        },
        "subnet_join": {
            "Microsoft.Network/virtualNetworks/subnets/read",
            "Microsoft.Network/virtualNetworks/subnets/join/action",
        },
        "image_read": {
            "Microsoft.Compute/galleries/images/versions/read",
        },
    }
    for name, actions in expected.items():
        role = block(identity, "resource", "azurerm_role_definition", name)
        match = re.search(r"(?m)^\s*actions\s*=\s*(\[[^]]*])", role)
        assert match is not None
        assert set(json.loads(match[1].replace(",\n    ]", "\n    ]"))) == actions
        assignment(role, "not_actions", "[]")
        assert "data_actions" not in role
        assert "*" not in role
    assert "runCommand/action" not in identity
    assert "roleAssignments/write" not in identity
    assert "userAssignedIdentities/assign/action" not in identity
    assert "Virtual Machine Contributor" not in identity
    for name, scope in (
        ("jobs", "azurerm_container_app_job.worker[each.key].id"),
        ("vm_workers", "azurerm_resource_group.workers.id"),
        ("subnet_join", "var.vm_subnet_id"),
        ("image_read", "var.vm_image_id"),
        ("state", "azurerm_storage_container.state.id"),
    ):
        role_assignment = block(identity, "resource", "azurerm_role_assignment", name)
        assignment(role_assignment, "scope", scope)
        assignment(
            role_assignment,
            "principal_id",
            "azurerm_user_assigned_identity.controller.principal_id",
        )
    worker_assignments = [
        block(identity, "resource", "azurerm_role_assignment", name)
        for name in re.findall(r'resource "azurerm_role_assignment" "([^"]+)"', identity)
        if "worker_pull.principal_id"
        in block(identity, "resource", "azurerm_role_assignment", name)
    ]
    assert len(worker_assignments) == 1
    assignment(worker_assignments[0], "scope", "var.registry_id")
    assignment(worker_assignments[0], "role_definition_name", '"AcrPull"')
    assert "identitySettings" in source("jobs.tf")
    assert "lifecycle None" in source("outputs.tf")


def test_blob_state_is_private_encrypted_and_never_uses_shared_keys() -> None:
    main = source("main.tf")
    state = block(main, "resource", "azurerm_storage_account", "state")
    for name, value in {
        "shared_access_key_enabled": "false",
        "allow_nested_items_to_be_public": "false",
        "cross_tenant_replication_enabled": "false",
        "local_user_enabled": "false",
        "https_traffic_only_enabled": "true",
        "infrastructure_encryption_enabled": "true",
        "account_replication_type": '"ZRS"',
        "default_to_oauth_authentication": "true",
        "min_tls_version": '"TLS1_2"',
    }.items():
        assignment(state, name, value)
    container = block(main, "resource", "azurerm_storage_container", "state")
    assignment(container, "container_access_type", '"private"')
    assert "storage_use_azuread" in source("versions.tf")
    assert "primary_access_key" not in main
    assert "connection_string" not in main
    assert "sas_token" not in main
    diagnostic = block(main, "resource", "azurerm_monitor_diagnostic_setting", "state_blob")
    assignment(
        diagnostic,
        "target_resource_id",
        '"${azurerm_storage_account.state.id}/blobServices/default"',
    )
    for category in ("StorageRead", "StorageWrite", "StorageDelete"):
        assert f'category = "{category}"' in diagnostic


def test_single_controller_owns_only_nonsecret_runtime_config_and_placeholders() -> None:
    controller = source("controller.tf")
    block(controller, "resource", "azapi_resource", "controller")
    assignment(controller, "type", '"Microsoft.App/containerApps@2024-03-01"')
    assignment(controller, "external", "true")
    assignment(controller, "allowInsecure", "false")
    assignment(controller, "targetPort", "8080")
    assignment(controller, "ignore_changes", "[body.properties.configuration.secrets]")
    assignment(controller, "ignore_body_changes", '["properties.configuration.secrets"]')
    assignment(controller, "response_export_values", '["properties.configuration.ingress.fqdn"]')
    assert re.findall(r'name\s*=\s*"([^"]+)",\s*value\s*=\s*"unset"', controller) == [
        "github-pat",
        "webhook-hmac",
    ]
    root = "\n".join(path.read_text() for path in INFRA.glob("*.tf"))
    assert not re.search(r'(?:resource|data)\s+"azurerm_container_app"\s+', root)
    assert not re.search(r'(?i)action\s*=\s*"listsecrets"', root)
    assert "azurerm_container_app.controller" not in source("outputs.tf")
    assert 'version = "= 2.13.0"' in source("versions.tf")
    assert 'required_version = ">= 1.11.0"' in source("versions.tf")
    for name in (
        "GITHUB_RUNNER_CREDENTIAL",
        "GITHUB_WEBHOOK_SECRET",
        "GITHUB_REPOSITORY",
        "CONFIG_JSON",
        "FDAI_RUNNER_CONTROLLER_APPLY",
    ):
        assert f'"{name}"' in controller
    config = block(source("main.tf"), "locals")
    expected = {
        "subscription_id",
        "resource_group",
        "jobs",
        "storage_url",
        "storage_container",
        "storage_blob",
        "controller_url",
        "vm_subnet_id",
        "vm_image_id",
        "vm_size",
        "ssh_public_key",
        "location",
        "worker_image",
        "name_prefix",
        "repository",
        "cpu_budgets",
    }
    config_object = re.search(r"config\s*=\s*\{([^}]+)}", config)
    assert config_object is not None
    assert set(re.findall(r"(?m)^\s*(\w+)\s*=", config_object[1])) == expected
    assert "azurerm_container_app.controller" not in config_object[1]
    assert "secret" not in config_object[1].lower()
    variables = source("variables.tf")
    assignment(block(variables, "variable", "vm_image_id"), "default", '""')
    assignment(block(variables, "variable", "controller_apply"), "default", "false")
    assert "versions/[0-9]+" in block(variables, "variable", "vm_image_id")
    assignment(block(variables, "variable", "vm_size"), "default", '"Standard_D4ds_v4"')
    assert "lower(var.worker_resource_group_name) != lower(var.resource_group_name)" in variables
    assert "azurerm_linux_virtual_machine" not in source("main.tf")
    assert "azurerm_public_ip" not in source("main.tf")


def test_controller_build_has_minimal_context_nonroot_stdlib_and_no_worker_code() -> None:
    dockerfile = source("Dockerfile")
    copies = re.findall(r"(?m)^COPY ([^\n]+)", dockerfile)
    assert copies == [
        "scripts/automation/runner_controller/ scripts/automation/runner_controller/",
        "scripts/automation/runner_pool_policy.py scripts/automation/runner_pool_policy.py",
        "config/ci-runner-pools.json config/ci-runner-pools.json",
    ]
    assert "USER 10001:10001" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert 'CMD ["python", "-m", "scripts.automation.runner_controller.service"]' in dockerfile
    assert not re.search(r"\b(pip|apt-get|docker|curl)\b", dockerfile)
    assert "ARG PYTHON_IMAGE\nFROM ${PYTHON_IMAGE}" in dockerfile
    assert source("Dockerfile.dockerignore").startswith("**\n")
    build = source("build-controller-image.sh")
    assert "@sha256:[0-9a-f]{64}" in build
    assert "python:3\\.13" in build
    assert "docker push" not in build
    assert "--secret" not in build


@pytest.fixture
def credential() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "controller_credential", INFRA / "set-controller-credential.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_credential_patch_targets_controller_only_without_secret_readback(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Mock()
    response.__enter__ = Mock(return_value=SimpleNamespace(status=200))
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    build_opener = Mock(return_value=opener)
    monkeypatch.setattr(credential.urllib.request, "build_opener", build_opener)
    credential.store_credentials(APP_ID, "example-azure-token", "example-pat", "example-hmac")
    request = opener.open.call_args.args[0]
    assert request.method == "PATCH"
    assert request.full_url == f"https://management.azure.com{APP_ID}?api-version=2024-03-01"
    assert request.get_header("Authorization") == "Bearer " + "example-azure-token"
    assert json.loads(request.data) == {
        "properties": {
            "configuration": {
                "secrets": [
                    {"name": "github-pat", "value": "example-pat"},
                    {"name": "webhook-hmac", "value": "example-hmac"},
                ]
            }
        }
    }
    assert opener.open.call_args.kwargs == {"timeout": 30}
    assert opener.open.call_count == 1
    assert build_opener.call_args.args[0].proxies == {}
    assert isinstance(build_opener.call_args.args[1], credential.NoRedirect)


@pytest.mark.parametrize(
    "target",
    [
        APP_ID.replace("/containerApps/", "/jobs/"),
        APP_ID.replace("-controller", "-general"),
        APP_ID + "/listSecrets",
        APP_ID + "?example=1",
        APP_ID.replace("rg-example-ci", "rg-example-ci%2fother"),
    ],
)
def test_credential_refuses_worker_or_ambiguous_target(credential: ModuleType, target: str) -> None:
    with pytest.raises(credential.CredentialError, match="invalid_controller_resource_id"):
        credential.store_credentials(target, "example-token", "example-pat", "example-hmac")


def test_credential_refuses_redirect(credential: ModuleType) -> None:
    with pytest.raises(credential.CredentialError, match="redirect_refused"):
        credential.NoRedirect().redirect_request(None, None, 307, "", {}, "https://example.com")


@pytest.mark.parametrize("status", [201, 202, 204, 500])
def test_credential_patch_does_not_claim_unconfirmed_success(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=SimpleNamespace(status=status))
    opener.open.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(credential.urllib.request, "build_opener", Mock(return_value=opener))
    with pytest.raises(credential.CredentialError, match="credential_update_unconfirmed"):
        credential.store_credentials(APP_ID, "example-token", "example-pat", "example-hmac")


def test_credential_provider_failure_is_sanitized(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = Mock()
    opener.open.side_effect = urllib.error.URLError("example-sensitive-provider-body")
    monkeypatch.setattr(credential.urllib.request, "build_opener", Mock(return_value=opener))
    with pytest.raises(credential.CredentialError, match="^credential_update_failed$") as caught:
        credential.store_credentials(APP_ID, "example-token", "example-pat", "example-hmac")
    assert caught.value.__suppress_context__


def test_azure_cli_receives_no_github_credential(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"example-azure-token\n"))
    monkeypatch.setattr(credential.shutil, "which", lambda executable: "/usr/bin/az")
    monkeypatch.setattr(credential.subprocess, "run", run)
    assert credential.access_token("00000000-0000-0000-0000-000000000000") == "example-azure-token"
    args = run.call_args.args[0]
    assert args[:3] == ["/usr/bin/az", "account", "get-access-token"]
    assert args[args.index("--subscription") + 1] == "00000000-0000-0000-0000-000000000000"
    assert run.call_args.kwargs == {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "check": False,
        "timeout": 30,
    }


@pytest.mark.parametrize(
    "stdout,returncode", [(b"", 0), (b"example\nunsafe", 0), (b"\xff", 0), (b"example", 1)]
)
def test_azure_cli_invalid_token_is_sanitized(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
    returncode: int,
) -> None:
    monkeypatch.setattr(credential.shutil, "which", lambda executable: "/usr/bin/az")
    monkeypatch.setattr(
        credential.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=returncode, stdout=stdout)),
    )
    with pytest.raises(credential.CredentialError, match="^azure_identity_unavailable$"):
        credential.access_token("00000000-0000-0000-0000-000000000000")


@pytest.mark.parametrize("generate", [True, False])
def test_interactive_credentials_stay_in_memory_and_output_is_nonsecret(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    generate: bool,
) -> None:
    monkeypatch.setattr(credential.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(credential.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(credential, "access_token", Mock(return_value="example-azure-token"))
    values = iter(["example-pat", "example-webhook-key-with-at-least-32-characters"])
    hidden = Mock(side_effect=lambda prompt: next(values))
    monkeypatch.setattr(credential.getpass, "getpass", hidden)
    monkeypatch.setattr(
        credential.secrets, "token_urlsafe", Mock(return_value="example-generated-" * 4)
    )
    store = Mock()
    monkeypatch.setattr(credential, "store_credentials", store)
    option = "--generate-webhook-key" if generate else "--prompt-webhook-key"
    assert credential.main(["--controller-resource-id", APP_ID, option]) == 0
    assert store.call_args.args[:3] == (APP_ID, "example-azure-token", "example-pat")
    assert store.call_args.args[3] == (
        "example-generated-" * 4 if generate else "example-webhook-key-with-at-least-32-characters"
    )
    assert hidden.call_count == (1 if generate else 2)
    captured = capsys.readouterr()
    assert captured.out == "controller_credentials_stored\n"
    assert captured.err == ""


def test_noninteractive_terminal_fails_before_identity_or_secret_input(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credential.sys.stdin, "isatty", lambda: False)
    identity = Mock()
    prompt = Mock()
    monkeypatch.setattr(credential, "access_token", identity)
    monkeypatch.setattr(credential.getpass, "getpass", prompt)
    assert credential.main(["--controller-resource-id", APP_ID, "--generate-webhook-key"]) == 1
    identity.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.parametrize(
    "value", ["", "unset", "example\nunsafe", "example unsafe", "\x7f", "x" * 4097]
)
def test_hidden_input_rejects_placeholder_and_control_characters(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setattr(credential.getpass, "getpass", Mock(return_value=value))
    with pytest.raises(credential.CredentialError, match="invalid_credential"):
        credential.hidden_value("Example: ")


def test_polling_only_credential_update_needs_no_webhook_permission(
    credential: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credential.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(credential.sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(credential, "access_token", Mock(return_value="example-token"))
    monkeypatch.setattr(credential.getpass, "getpass", Mock(return_value="example-pat"))
    store = Mock()
    monkeypatch.setattr(credential, "store_credentials", store)
    assert credential.main(["--controller-resource-id", APP_ID, "--disable-webhook"]) == 0
    assert store.call_args.args[3] == "unset"
    assert credential.getpass.getpass.call_count == 1


@pytest.fixture
def image_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("image_builder", INFRA / "build-vm-image.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def image_args(tmp_path: Path) -> SimpleNamespace:
    key = tmp_path / "example.pub"
    key.write_text("ssh-ed25519 ZXhhbXBsZQ== example\n", encoding="utf-8")
    root = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ci"
    return SimpleNamespace(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example-ci",
        location="westus3",
        source_sha="a" * 40,
        builder_name="vm-example-builder",
        nic_name="nic-example-builder",
        disk_name="disk-example-builder",
        gallery_name="gal-example",
        image_definition="img-example",
        image_version="1.0.0",
        subnet_id=root + "/providers/Microsoft.Network/virtualNetworks/vnet-example/subnets/ci",
        base_image_id=root
        + "/providers/Microsoft.Compute/galleries/galbase/images/ubuntu/versions/1.0.0",
        vm_size="Standard_D4ds_v4",
        state_dir=tmp_path / "private-build",
        ssh_public_key_file=key,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha", "main"),
        ("base_image_id", "Canonical:ubuntu-24_04-lts:server:latest"),
        (
            "base_image_id",
            "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.Compute/images/unsupported",
        ),
        ("image_version", "latest"),
        ("image_version", "1.0"),
        ("image_version", "1.0.2147483648"),
        ("gallery_name", "../unapproved"),
        ("builder_name", "../existing"),
        ("subnet_id", "/unselected/subnet"),
        ("subscription_id", "not-a-subscription"),
    ],
)
def test_image_builder_rejects_unpinned_or_unscoped_inputs(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    field: str,
    value: str,
) -> None:
    setattr(image_args, field, value)
    with pytest.raises(image_builder.BuildError):
        image_builder.validate(image_args)


def test_image_payload_uses_exact_git_commit_and_no_credentials(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/" + executable)
    run = Mock(
        side_effect=lambda argv, timeout: (
            "commit" if argv[1] == "cat-file" else "example-source-content"
        )
    )
    monkeypatch.setattr(image_builder, "command", run)
    key = image_builder.validate(image_args)
    payload = image_builder.prepare(image_args, key)
    data = json.loads(payload.read_text().split("\n", 1)[1])
    assert [call.args[0][-1] for call in run.call_args_list if call.args[0][1] == "show"] == [
        image_args.source_sha + ":" + path for path in image_builder.SOURCE_FILES
    ]
    assert len(data["write_files"]) == 5
    assert all(item["owner"] == "root:root" for item in data["write_files"])
    assert data["runcmd"][0][:4] == [
        "timeout",
        "3600",
        "bash",
        "/opt/fdai-ci/image-source/infra/ci-runner-controller/provision-vm-image.sh",
    ]
    assert "ticket" not in payload.read_text()
    assert "PAT" not in payload.read_text()
    assert payload.stat().st_mode & 0o777 == 0o600


def test_image_builder_refuses_any_existing_resource_before_mutation(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    builder.resources = Mock(return_value={builder.ids["vm"].lower(): {}})
    builder.az = Mock()
    with pytest.raises(image_builder.BuildError, match="existing_builder_resource_refused"):
        builder.execute(Path("example-cloud-init.json"), "example-public-key")
    builder.az.assert_not_called()


def gallery_definition(builder: Any) -> dict[str, object]:
    return {
        "id": builder.ids["definition"],
        "architecture": "x64",
        "hyperVGeneration": "V2",
        "osType": "Linux",
        "osState": "Generalized",
        "features": [{"name": "SecurityType", "value": "TrustedLaunch"}],
    }


@pytest.mark.parametrize("violation", ["none", "replication", "source", "latest", "mode"])
def test_image_capture_verifies_source_before_exact_builder_cleanup(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    builder.resources = Mock(side_effect=[{}, {}, {}])
    builder.verify_builder = Mock()
    builder.run_script = Mock()
    image = {
        "id": builder.ids["image"],
        "provisioningState": "Succeeded",
        "storageProfile": {"source": {"virtualMachineId": builder.ids["vm"]}},
        "replicationStatus": {"aggregatedState": "Completed"},
        "publishingProfile": {"replicationMode": "Full", "excludeFromLatest": True},
    }
    if violation == "replication":
        image["replicationStatus"]["aggregatedState"] = "InProgress"
    elif violation == "source":
        image["storageProfile"]["source"]["virtualMachineId"] = "/wrong/source"
    elif violation == "latest":
        image["publishingProfile"]["excludeFromLatest"] = False
    elif violation == "mode":
        image["publishingProfile"]["replicationMode"] = "Shallow"
    responses = {
        "verify_image": image,
        "verify_definition": gallery_definition(builder),
        "verify_gallery": {"id": builder.ids["gallery"], "location": image_args.location},
        "list_definitions": [],
        "list_versions": [],
    }
    builder.az = Mock(side_effect=lambda stage, *args, **kwargs: responses.get(stage, {}))
    if violation != "none":
        with pytest.raises(image_builder.BuildError, match="captured_image_unconfirmed"):
            builder.execute(Path("example-cloud-init.json"), "example-public-key")
        assert not any(call.args[0].startswith("delete") for call in builder.az.call_args_list)
        return
    assert (
        builder.execute(Path("example-cloud-init.json"), "example-public-key")
        == builder.ids["image"]
    )
    calls = builder.az.call_args_list
    stages = [call.args[0] for call in calls]
    assert stages.index("verify_image") < stages.index("delete_builder")
    vm_args = next(call.args for call in calls if call.args[0] == "create_vm")
    assert "--assign-identity" not in vm_args
    assert "--public-ip-address" not in vm_args
    assert vm_args[vm_args.index("--nics") + 1] == builder.ids["nic"]
    assert vm_args[vm_args.index("--security-type") + 1] == "TrustedLaunch"
    assert vm_args[vm_args.index("--enable-secure-boot") + 1] == "true"
    assert vm_args[vm_args.index("--enable-vtpm") + 1] == "true"
    definition = next(call.args for call in calls if call.args[0] == "create_definition")
    assert definition[definition.index("--features") + 1] == "SecurityType=TrustedLaunch"
    assert definition[definition.index("--os-state") + 1] == "Generalized"
    capture = next(call.args for call in calls if call.args[0] == "capture_image")
    assert capture[1:4] == ("sig", "image-version", "create")
    assert capture[capture.index("--virtual-machine") + 1] == builder.ids["vm"]
    assert capture[capture.index("--gallery-image-version") + 1] == "1.0.0"
    assert capture[capture.index("--replication-mode") + 1] == "Full"
    assert builder.run_script.call_count == 2
    assert "cloud-init status --wait" in builder.run_script.call_args_list[0].args[1]
    assert "waagent -deprovision+user" in builder.run_script.call_args_list[1].args[1]


def test_image_capture_failure_never_deletes_ambiguous_builder(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    builder.resources = Mock(return_value={})
    builder.prepare_gallery = Mock()
    builder.verify_builder = Mock()
    builder.run_script = Mock()
    builder.az = Mock(return_value={})
    with pytest.raises(image_builder.BuildError, match="captured_image_unconfirmed"):
        builder.execute(Path("example-cloud-init.json"), "example-public-key")
    assert not any(call.args[0].startswith("delete") for call in builder.az.call_args_list)


def test_image_provisioner_reuses_toolchain_and_never_registers() -> None:
    script = source("provision-vm-image.sh")
    assert "timeout 2400 /opt/fdai-ci/provision-toolchain.sh" in script
    assert "usermod -aG docker runner" in script
    assert "/opt/fdai-ci/broker-entrypoint.py" in script
    assert "/home/runner" in script and "/opt/actions-runner" in script
    assert "systemctl enable --now docker" in script
    assert "sha256sum --check --strict" in script
    assert re.search(r"runner_version=2\.338\.2", script)
    worker = (ROOT / "infra/ci-runner-aca/Dockerfile").read_text()
    assert re.search(r"runner_sha256=([0-9a-f]{64})", script)[1] in worker
    assert not re.search(r"(?m)^[^#\n]*config\.sh", script)
    assert "az login" not in script
    assert "RUNNER_ALLOW_RUNASROOT" not in script
    assert "docker info >/dev/null" in script
    assert "tini unzip tzdata tzdata-legacy" in script


@pytest.mark.parametrize(
    "code",
    [
        "ProvisioningState/succeeded",
        "ComponentStatus/StdOut/succeeded",
    ],
)
def test_image_builder_requires_authoritative_stage_marker(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    builder.az = Mock(
        return_value={"value": [{"code": code, "message": "[stdout]\nexample_done\n"}]}
    )
    builder.run_script("example", "echo example_done", "example_done")
    builder.az.return_value["value"][0]["message"] = "not_example_done"
    with pytest.raises(image_builder.BuildError, match="builder_stage_unconfirmed"):
        builder.run_script("example", "echo example_done", "example_done")


@pytest.mark.parametrize(
    "identity,public_ip",
    [
        ({"type": "SystemAssigned"}, None),
        (None, {"id": "/unapproved/public-ip"}),
    ],
)
def test_image_builder_refuses_identity_or_public_nic(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    identity: object,
    public_ip: object,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    tags = {"fdai:image-builder": "true", "fdai:source-sha": image_args.source_sha}
    vm = {
        "id": builder.ids["vm"],
        "tags": tags,
        "identity": identity,
        "securityProfile": {
            "securityType": "TrustedLaunch",
            "uefiSettings": {
                "secureBootEnabled": True,
                "vTpmEnabled": True,
            },
        },
        "networkProfile": {"networkInterfaces": [{"id": builder.ids["nic"]}]},
        "storageProfile": {"osDisk": {"managedDisk": {"id": builder.ids["disk"]}}},
    }
    nic = {
        "id": builder.ids["nic"],
        "tags": tags,
        "ipConfigurations": [
            {"publicIPAddress": public_ip, "subnet": {"id": image_args.subnet_id}}
        ],
    }
    builder.az = Mock(side_effect=[vm, nic])
    with pytest.raises(image_builder.BuildError, match="builder_(scope|network)_changed"):
        builder.verify_builder()


@pytest.mark.parametrize(
    "field,value",
    [
        ("features", [{"name": "SecurityType", "value": "TrustedLaunchSupported"}]),
        ("osState", "Specialized"),
        ("hyperVGeneration", "V1"),
        ("architecture", "Arm64"),
    ],
)
def test_gallery_definition_requires_generalized_trusted_launch_source(
    image_builder: ModuleType,
    image_args: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(image_builder.shutil, "which", lambda executable: "/usr/bin/az")
    builder = image_builder.Builder(image_args)
    definition = gallery_definition(builder)
    definition[field] = value
    builder.az = Mock(return_value=definition)
    with pytest.raises(image_builder.BuildError, match="trusted_launch_definition_required"):
        builder.verify_definition()
