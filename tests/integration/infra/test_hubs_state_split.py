"""Offline ownership rehearsal, never an Azure deployment or real-state migration."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[3] / "infra"
ROOT = INFRA / "hubs-development"
STATE_ORDER_COMMAND = (
    'jq --slurpfile mapped "$PRIVATE_MOVE_RESOURCES"'
    + (INFRA / "modules/hub-service/README.md")
    .read_text()
    .split('```bash\njq --slurpfile mapped "$PRIVATE_MOVE_RESOURCES"', 1)[1]
    .split("\n```", 1)[0]
)
RESOURCE = re.compile(r'^resource "([^"]+)" "([^"]+)"', re.M)
KINDS = ("release", "target")
DIRECTORY_STATES = ("absent", "partial_registration", "consent_pending", "bound")
LEGACY_FOUNDATION = {
    "azurerm_resource_group.hub",
    "azurerm_virtual_network.hub",
    "azurerm_subnet.apps",
    "azurerm_subnet.database",
    "azurerm_subnet.secrets",
    "azurerm_public_ip.egress",
    "azurerm_nat_gateway.hub",
    "azurerm_nat_gateway_public_ip_association.hub",
    "azurerm_subnet_nat_gateway_association.hub",
    "azurerm_log_analytics_workspace.hub",
    "azurerm_container_app_environment.hub",
    "azurerm_user_assigned_identity.hub",
    "azurerm_key_vault.hub",
    "azurerm_private_dns_zone.vault",
    "azurerm_private_dns_zone.database",
    "azurerm_private_dns_zone_virtual_network_link.vault",
    "azurerm_private_dns_zone_virtual_network_link.database",
    "azurerm_private_endpoint.vault",
    "azurerm_postgresql_flexible_server.hub",
    "azurerm_postgresql_flexible_server_active_directory_administrator.hub",
    "azurerm_postgresql_flexible_server_database.hub",
    "azurerm_postgresql_flexible_server_configuration.log_connections",
    "azurerm_postgresql_flexible_server_configuration.log_checkpoints",
    "azurerm_postgresql_flexible_server_configuration.connection_throttle",
    "azurerm_postgresql_flexible_server_configuration.tls_floor",
}
LEGACY_DIRECTORY = {
    "azuread_application.api",
    "azuread_application.browser",
    "azuread_application_identifier_uri.api",
    "azuread_service_principal.api",
    "azuread_service_principal.browser",
    "azuread_service_principal_delegated_permission_grant.operator",
    "azuread_app_role_assignment.catalog_reader",
}


def _declarations(root: Path) -> set[str]:
    return {
        f"{kind}.{name}"
        for path in root.glob("*.tf")
        for kind, name in RESOURCE.findall(path.read_text(encoding="utf-8"))
    }


def _run(root: Path, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ARM_", "AZURE_", "TF_VAR_", "TF_CLI_ARGS"))
        and key not in {"TF_DATA_DIR", "TF_WORKSPACE", "TF_CLI_CONFIG_FILE"}
    }
    environment.update(TF_IN_AUTOMATION="1", CHECKPOINT_DISABLE="1")
    executable = shutil.which("terraform")
    assert executable is not None, "Terraform is required for the offline state rehearsal."
    result = subprocess.run(  # noqa: S603 - Literal test commands on synthetic temporary states.
        [executable, *args],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def _inventory(directory: str) -> dict[str, str]:
    objects = {f'{resource}["{kind}"]': kind for resource in LEGACY_FOUNDATION for kind in KINDS}
    for kind in KINDS:
        objects[f'azurerm_role_assignment.registry_reader["{kind}"]'] = kind
        for secret in ("development-signing-key", "hub-database-url"):
            objects[f'azurerm_role_assignment.secret_reader["{kind}-{secret}"]'] = kind
    for resource in LEGACY_DIRECTORY:
        if directory == "absent":
            continue
        if directory == "partial_registration" and not resource.startswith("azuread_application."):
            continue
        if directory == "consent_pending" and resource.startswith(
            (
                "azuread_app_role_assignment.",
                "azuread_service_principal_delegated_permission_grant.",
            )
        ):
            continue
        addresses = (
            [resource]
            if resource == "azuread_app_role_assignment.catalog_reader"
            else [f'{resource}["{kind}"]' for kind in KINDS]
        )
        objects.update(dict.fromkeys(addresses, "legacy"))
    if directory == "consent_pending":
        objects["data.azuread_client_config.current[0]"] = "legacy"
    if directory == "bound":
        for resource in ("azurerm_container_app.hub", "azurerm_container_app_job.migrate"):
            objects.update({f'{resource}["{kind}"]': kind for kind in KINDS})
    return objects


@pytest.mark.parametrize("product", ("release-hub", "lifecycle-hub"))
def test_local_backend_uses_explicit_private_state_path(tmp_path: Path, product: str) -> None:
    declaration = re.search(r'backend "local" \{\}', (INFRA / product / "main.tf").read_text())
    assert declaration is not None, "Existing local state must not require Azure backend bootstrap."
    root = tmp_path / product
    root.mkdir()
    (root / "main.tf").write_text(
        f'terraform {{\n  {declaration.group()}\n}}\nresource "terraform_data" "owned" {{}}\n'
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    state = private / f"{product}.tfstate"
    backend = private / f"{product}.backend.hcl"
    backend.write_text(f"path = {json.dumps(str(state))}\n")
    _run(root, "init", f"-backend-config={backend}", "-input=false", "-no-color")
    _run(root, "plan", "-out=candidate.tfplan", "-input=false", "-no-color")
    _run(root, "apply", "-input=false", "-no-color", "candidate.tfplan")
    assert state.is_file()
    assert len(json.loads(state.read_text())["resources"]) == 1
    assert not (root / "terraform.tfstate").exists()


def _write_state(path: Path, addresses: list[str], *, counted_role: bool = False) -> None:
    resources: dict[str, dict] = {}
    for address in addresses:
        base, _, index = address.removeprefix("data.").partition("[")
        kind, name = base.split(".")
        provider = "azuread" if kind.startswith("azuread_") else "azurerm"
        instance = {
            "schema_version": 0,
            "attributes": {"id": f"synthetic://{address}"},
            "sensitive_attributes": [],
            "private": "e30=",
            "dependencies": (
                ["azurerm_resource_group.hub", "azurerm_user_assigned_identity.hub"]
                if kind == "azurerm_role_assignment"
                else ["azurerm_resource_group.hub"]
                if f"{kind}.{name}" in LEGACY_FOUNDATION and kind != "azurerm_resource_group"
                else []
            ),
        }
        if index:
            instance["index_key"] = json.loads(index[:-1])
        elif counted_role and base == "azuread_app_role_assignment.catalog_reader":
            instance["index_key"] = 0
        resource = resources.setdefault(
            base,
            {
                "mode": "data" if address.startswith("data.") else "managed",
                "type": kind,
                "name": name,
                "provider": f'provider["registry.terraform.io/hashicorp/{provider}"]',
                "instances": [],
            },
        )
        resource["instances"].append(instance)
    path.write_text(
        json.dumps(
            {
                "version": 4,
                "terraform_version": "1.9.0",
                "serial": 1,
                "lineage": "00000000-0000-0000-0000-000000000001",
                "outputs": {},
                "resources": list(resources.values()),
            }
        ),
        encoding="utf-8",
    )


def _instances(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    result = {}
    for resource in json.loads(path.read_text(encoding="utf-8"))["resources"]:
        for instance in resource["instances"]:
            address = f"{resource['type']}.{resource['name']}"
            if resource.get("module"):
                address = f"{resource['module']}.{address}"
            if resource["mode"] == "data":
                address = f"data.{address}"
            if "index_key" in instance:
                address += f"[{json.dumps(instance['index_key'])}]"
            result[address] = {
                "provider": resource["provider"],
                **{key: value for key, value in instance.items() if key != "index_key"},
            }
            # Terraform 1.15 adds this version and omits empty dependency arrays on rewrite.
            result[address].setdefault("identity_schema_version", 0)
            result[address].setdefault("dependencies", [])
    return result


def _dependency_order(tmp_path: Path, source: Path, inventory: dict[str, str]) -> list[str]:
    mapped = tmp_path / "move-resources.json"
    mapped.write_text(
        json.dumps(
            sorted(
                {
                    address.partition("[")[0]
                    for address, owner in inventory.items()
                    if owner in KINDS
                }
            )
        )
    )
    order = tmp_path / "resource-order.txt"
    bash = shutil.which("bash")
    assert bash is not None and shutil.which("jq"), "Bash and jq are required."
    result = subprocess.run(  # noqa: S603 - Actual runbook command on synthetic state files.
        [bash, "-euo", "pipefail", "-c", STATE_ORDER_COMMAND],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "PRIVATE_MOVE_RESOURCES": str(mapped),
            "PRIVATE_SOURCE_COPY": str(source),
            "PRIVATE_RESOURCE_ORDER": str(order),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    resources = order.read_text().splitlines()
    assert set(resources) == set(json.loads(mapped.read_text()))
    return [
        address
        for resource in resources
        for address, owner in inventory.items()
        if owner in KINDS and address.partition("[")[0] == resource
    ]


def test_each_resource_has_exactly_one_owner_and_base_has_no_graph() -> None:
    module = INFRA / "modules/hub-service"
    assert _declarations(module) >= LEGACY_FOUNDATION | {
        "azurerm_role_assignment.registry_reader",
        "azurerm_role_assignment.secret_reader",
        "azurerm_container_app.hub",
        "azurerm_container_app_job.migrate",
    }
    for product, kind in (("release-hub", "release"), ("lifecycle-hub", "target")):
        path = INFRA / product
        source = "\n".join(file.read_text(encoding="utf-8") for file in path.glob("*.tf"))
        assert re.search(rf'kind\s*=\s*"{kind}"', source)
        assert re.search(r"app_image\s*=\s*var\.app_image", source)
        assert not _declarations(path)
        assert not re.search(r"\bazuread\b|\bazuread_|terraform_remote_state", source)
        assert not re.search(
            r"foundation_only|manage_directory_grants|browser_login_enabled", source
        )
        assert "local-exec" not in source
        lock = (path / ".terraform.lock.hcl").read_text(encoding="utf-8")
        assert "hashicorp/azuread" not in lock
    source = "\n".join(file.read_text() for file in module.glob("*.tf"))
    assert "azuread" not in source and "terraform_remote_state" not in source
    assert "toset([var.kind])" in source
    for path, resource in (
        ("apps.tf", "azurerm_container_app"),
        ("migrations.tf", "azurerm_container_app_job"),
    ):
        source = (module / path).read_text(encoding="utf-8")
        block = re.search(rf'resource "{resource}".*?\n\}}', source, re.S)
        assert block is not None and "prevent_destroy = true" in block.group()


@pytest.mark.parametrize("filename", ("apps.tf", "bootstrap.tf", "migrations.tf"))
def test_runtime_workloads_explicitly_match_environment_profile(filename: str) -> None:
    module = INFRA / "modules/hub-service"
    environment = (module / "boundaries.tf").read_text(encoding="utf-8")
    assert re.search(r'workload_profile_type\s*=\s*"Consumption"', environment)
    source = (module / filename).read_text(encoding="utf-8")
    assert re.search(r'workload_profile_name\s*=\s*"Consumption"', source)


@pytest.mark.parametrize("directory", DIRECTORY_STATES)
def test_native_state_moves_preserve_partial_azure_instances(
    tmp_path: Path, directory: str
) -> None:
    """Real Azure address shapes and native state mv, but synthetic ID-only attributes."""
    inventory = _inventory(directory)
    source = tmp_path / "legacy.tfstate"
    _write_state(source, list(inventory), counted_role=directory == "bound")
    backup = tmp_path / "before.tfstate"
    shutil.copy2(source, backup)
    backup_bytes = backup.read_bytes()
    before = _instances(backup)
    registry = tmp_path / "registry.tfstate"
    _write_state(registry, ["azurerm_container_registry.hub"])
    registry_before = registry.read_bytes()

    order = _dependency_order(tmp_path, source, inventory)
    for owner in KINDS:
        for address in order:
            if inventory[address] != owner:
                continue
            _run(
                tmp_path,
                "state",
                "mv",
                f"-state={source}",
                f"-state-out={tmp_path / (owner + '.tfstate')}",
                address,
                f"module.hub.{address}",
            )
    after = {}
    for owner in (*KINDS, "legacy"):
        instances = _instances(tmp_path / f"{owner}.tfstate")
        expected = {
            f"module.hub.{address}" if owner != "legacy" else address
            for address, root in inventory.items()
            if root == owner
        }
        if owner == "legacy" and directory == "bound":
            expected.remove("azuread_app_role_assignment.catalog_reader")
            expected.add("azuread_app_role_assignment.catalog_reader[0]")
        assert set(instances) == expected
        assert after.keys().isdisjoint(instances)
        after.update(
            {
                address.removeprefix("module.hub."): instance
                for address, instance in instances.items()
            }
        )
    assert before == after
    assert backup.read_bytes() == backup_bytes
    assert registry.read_bytes() == registry_before
    assert (
        json.loads(source.read_text(encoding="utf-8"))["lineage"]
        == (json.loads(backup_bytes)["lineage"])
    )


def test_unordered_native_move_invalidates_destination_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "source.tfstate"
    destination = tmp_path / "destination.tfstate"
    group = 'azurerm_resource_group.hub["release"]'
    identity = 'azurerm_user_assigned_identity.hub["release"]'
    _write_state(source, [group, identity])
    before = _instances(source)
    for address in (identity, group):
        _run(
            tmp_path,
            "state",
            "mv",
            f"-state={source}",
            f"-state-out={destination}",
            address,
            f"module.hub.{address}",
        )
    after = _instances(destination)
    assert before[identity]["dependencies"]
    assert after[f"module.hub.{identity}"]["dependencies"] == []
    assert before[identity]["attributes"] == after[f"module.hub.{identity}"]["attributes"]
    assert before[identity]["private"] == after[f"module.hub.{identity}"]["private"]


def test_dependency_cycle_stops_before_any_state_move(tmp_path: Path) -> None:
    source = tmp_path / "source.tfstate"
    group = 'azurerm_resource_group.hub["release"]'
    identity = 'azurerm_user_assigned_identity.hub["release"]'
    _write_state(source, [group, identity])
    state = json.loads(source.read_text())
    state["resources"][0]["instances"][0]["dependencies"] = ["azurerm_user_assigned_identity.hub"]
    source.write_text(json.dumps(state))
    before = source.read_bytes()
    with pytest.raises(AssertionError, match="State dependency cycle"):
        _dependency_order(tmp_path, source, {group: "release", identity: "release"})
    assert source.read_bytes() == before


def _model(path: Path, objects: dict[str, str]) -> None:
    path.mkdir(exist_ok=True)
    (path / "main.tf").write_text(
        'variable "objects" { type = map(string) }\n'
        'resource "terraform_data" "owned" {\n'
        "  for_each = var.objects\n"
        "  input = each.value\n"
        "}\n",
        encoding="utf-8",
    )
    (path / "input.auto.tfvars.json").write_text(json.dumps({"objects": objects}), encoding="utf-8")


@pytest.mark.parametrize("directory", DIRECTORY_STATES)
def test_offline_split_plans_have_zero_deletes_or_replacements(
    tmp_path: Path, directory: str
) -> None:
    """Built-in provider models ownership only, not Azure drift or provider normalization."""
    inventory = _inventory(directory)
    inputs = {address: f"synthetic:{address}" for address in inventory}
    foundation = tmp_path / "legacy"
    _model(foundation, inputs)
    _run(foundation, "init", "-backend=false", "-input=false", "-no-color")
    _run(foundation, "apply", "-auto-approve", "-input=false", "-no-color")
    source = foundation / "terraform.tfstate"
    backup = tmp_path / "before.tfstate"
    shutil.copy2(source, backup)
    before = _instances(backup)
    for owner in KINDS:
        destination = tmp_path / owner
        _model(
            destination,
            {address: inputs[address] for address, root in inventory.items() if root == owner},
        )
        _run(destination, "init", "-backend=false", "-input=false", "-no-color")
        for address, root in inventory.items():
            if root != owner:
                continue
            key = f"terraform_data.owned[{json.dumps(address)}]"
            _run(
                tmp_path,
                "state",
                "mv",
                f"-state={source}",
                f"-state-out={destination / 'terraform.tfstate'}",
                key,
                key,
            )
    _model(
        foundation,
        {address: inputs[address] for address, root in inventory.items() if root == "legacy"},
    )
    after = {}
    for owner in ("legacy", *KINDS):
        root = tmp_path / owner
        _run(root, "plan", "-refresh=false", "-input=false", "-no-color", "-out=split.plan")
        plan = json.loads(_run(root, "show", "-json", "split.plan").stdout)
        assert all(
            change["change"]["actions"] == ["no-op"] for change in plan.get("resource_changes", [])
        )
        instances = _instances(root / "terraform.tfstate")
        assert after.keys().isdisjoint(instances)
        after.update(instances)
    assert after == before
    assert _instances(backup) == before


def test_occupied_destination_refuses_move_without_state_loss(tmp_path: Path) -> None:
    address = 'azuread_application.api["release"]'
    source = tmp_path / "foundation.tfstate"
    destination = tmp_path / "identity.tfstate"
    _write_state(source, [address])
    _write_state(destination, [address])
    before = source.read_bytes(), destination.read_bytes()
    result = _run(
        tmp_path,
        "state",
        "mv",
        f"-state={source}",
        f"-state-out={destination}",
        address,
        address,
        success=False,
    )
    assert result.returncode != 0 and "already" in result.stderr.lower()
    assert before == (source.read_bytes(), destination.read_bytes())


def test_move_into_partial_runtime_state_preserves_existing_jobs(tmp_path: Path) -> None:
    source = tmp_path / "foundation.tfstate"
    destination = tmp_path / "runtime.tfstate"
    addresses = [
        address
        for address, owner in _inventory("absent").items()
        if owner == "release" and address.startswith("azurerm_role_assignment.")
    ]
    _write_state(source, addresses)
    _write_state(destination, ['azurerm_container_app_job.migrate["release"]'])
    before = _instances(source) | _instances(destination)
    destination_backup = tmp_path / "runtime.before.tfstate"
    shutil.copy2(destination, destination_backup)
    backup_bytes = destination_backup.read_bytes()
    for address in addresses:
        _run(
            tmp_path,
            "state",
            "mv",
            f"-state={source}",
            f"-state-out={destination}",
            address,
            address,
        )
    assert _instances(source) == {}
    assert _instances(destination) == before
    assert destination_backup.read_bytes() == backup_bytes
