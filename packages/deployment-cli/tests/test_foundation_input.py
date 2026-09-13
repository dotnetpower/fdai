from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.target import compute_target_binding

TENANT = "00000000-0000-0000-0000-000000000000"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
BINDING = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)


def foundation_values() -> dict[str, object]:
    return {
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "target_binding": BINDING,
        "region": "koreacentral",
        "workload": "example",
        "region_short": "krc",
        "state_storage_account_name": "examplestate",
        "ops_address_space": "10.40.0.0/16",
        "runner_subnet_prefix": "10.40.1.0/24",
        "pe_subnet_prefix": "10.40.2.0/24",
        "runner_ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA==",
        "runner_source_image_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.Compute/images/example"
        ),
        "source_commit": "a" * 40,
        "run_digest": "b" * 64,
        "foundation_context_digest": "c" * 64,
        "runner_image_toolchain_digest": "d" * 64,
    }


def snapshot(source: Path, destination: Path) -> None:
    snapshot_foundation_input(
        source,
        destination,
        expected_target_binding=BINDING,
        expected_region="koreacentral",
        expected_environment="dev",
    )


def write_values(path: Path, values: dict[str, object]) -> None:
    path.write_text(json.dumps(values), encoding="utf-8")
    path.chmod(0o600)


def test_foundation_input_preserves_explicit_provider_context(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    destination = tmp_path / "snapshot.json"
    values = foundation_values()
    write_values(source, values)
    snapshot(source, destination)
    expected = {name: value for name, value in values.items() if name != "target_binding"}
    expected["env"] = "dev"
    assert json.loads(destination.read_bytes()) == expected
    assert destination.stat().st_mode & 0o777 == 0o600
    assert json.loads(source.read_bytes()) == values


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("tenant_id", None),
        ("subscription_id", "not-a-uuid"),
        ("target_binding", "d" * 64),
        ("region", "eastus"),
        ("workload", "invalid/name"),
        ("region_short", "KR"),
        ("state_storage_account_name", "UPPERCASE"),
        ("runner_ssh_public_key", "not-a-public-key"),
        ("runner_ssh_public_key", "ssh-ed25519 AAAA operator@example.com"),
        ("source_commit", "a" * 39),
        ("run_digest", "b" * 63),
        ("foundation_context_digest", "c" * 63),
        ("state_retention_days", True),
        ("state_retention_days", 0),
        ("state_retention_days", 366),
        ("state_retention_days", 30.5),
        ("runner_vm_size", None),
        ("enable_public_egress", "true"),
        ("enable_bastion", "true"),
        ("ops_address_space", None),
        ("ops_address_space", "::/64"),
        ("ops_address_space", "10.40.0.1/16"),
        ("runner_subnet_prefix", "10.41.1.0/24"),
        ("pe_subnet_prefix", "10.40.1.128/25"),
        ("runner_source_image_id", "https://example.com/image"),
        ("runner_source_image_id", "/subscriptions/example/images/latest"),
        ("runner_admin_username", "Invalid User"),
        ("runner_parallelism", 0),
        ("execution_transport", "github-actions"),
        ("postgres_admin_password", "not-accepted"),
        ("github_runner_token", "not-accepted"),
        ("env", "prod"),
    ],
)
def test_invalid_foundation_values_never_create_snapshot(
    tmp_path: Path, name: str, value: object
) -> None:
    source = tmp_path / "input.json"
    destination = tmp_path / "snapshot.json"
    values = foundation_values()
    values[name] = value
    write_values(source, values)
    with pytest.raises(ValueError):
        snapshot(source, destination)
    assert not destination.exists()


@pytest.mark.parametrize("version", ["1.2.3", "latest", "1.2", "1.2.3?query=true", ""])
def test_gallery_requires_exact_numeric_version(tmp_path: Path, version: str) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    values["runner_source_image_id"] = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/Microsoft.Compute/"
        f"galleries/example/images/example/versions/{version}"
    )
    write_values(source, values)
    if version == "1.2.3":
        snapshot(source, tmp_path / "output.json")
    else:
        with pytest.raises(ValueError, match="exact managed image"):
            snapshot(source, tmp_path / "output.json")


def test_foundation_optional_inputs_are_preserved(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    values.update(
        state_retention_days=45,
        runner_vm_size="Standard_D8ds_v5",
        runner_admin_username="fdairunner",
        runner_parallelism=3,
        enable_public_egress=True,
        enable_bastion=True,
        bastion_subnet_prefix="10.40.3.0/24",
    )
    write_values(source, values)
    output = tmp_path / "output.json"
    snapshot(source, output)
    actual = json.loads(output.read_bytes())
    for name in (
        "state_retention_days",
        "runner_vm_size",
        "runner_admin_username",
        "runner_parallelism",
        "enable_public_egress",
        "enable_bastion",
        "bastion_subnet_prefix",
    ):
        assert actual[name] == values[name]


def test_runner_image_networks_are_validated_but_not_forwarded_to_foundation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    values.update(
        build_address_space="10.41.0.0/16",
        build_subnet_prefix="10.41.0.0/26",
        firewall_subnet_prefix="10.41.0.64/26",
        firewall_management_subnet_prefix="10.41.0.128/26",
    )
    write_values(source, values)
    output = tmp_path / "output.json"
    snapshot(source, output)
    actual = json.loads(output.read_bytes())
    assert set(actual).isdisjoint(
        {
            "build_address_space",
            "build_subnet_prefix",
            "firewall_subnet_prefix",
            "firewall_management_subnet_prefix",
        }
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("build_subnet_prefix", "10.42.0.0/26"),
        ("firewall_subnet_prefix", "10.41.0.0/26"),
        ("firewall_management_subnet_prefix", "10.41.0.65/26"),
    ],
)
def test_runner_image_networks_reject_invalid_layout(tmp_path: Path, name: str, value: str) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    values.update(
        build_address_space="10.41.0.0/16",
        build_subnet_prefix="10.41.0.0/26",
        firewall_subnet_prefix="10.41.0.64/26",
        firewall_management_subnet_prefix="10.41.0.128/26",
    )
    values[name] = value
    write_values(source, values)
    with pytest.raises(ValueError, match="runner image"):
        snapshot(source, tmp_path / "output.json")


@pytest.mark.parametrize(
    "prefix",
    [None, "10.40.1.0/24", "10.41.0.0/24", "10.40.3.0/27", "10.40.3.1/24"],
)
def test_bastion_subnet_must_be_disjoint_contained_and_at_least_26(
    tmp_path: Path, prefix: str | None
) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    values["enable_bastion"] = True
    if prefix is not None:
        values["bastion_subnet_prefix"] = prefix
    write_values(source, values)

    with pytest.raises(ValueError, match="Bastion"):
        snapshot(source, tmp_path / "output.json")


@pytest.mark.parametrize("kind", ["missing", "duplicate", "public", "link", "fifo", "oversized"])
def test_foundation_input_refuses_unsafe_source(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "input.json"
    values = foundation_values()
    if kind == "missing":
        del values["run_digest"]
    write_values(source, values)
    if kind == "duplicate":
        source.write_text('{"tenant_id":1,"tenant_id":2}', encoding="utf-8")
    elif kind == "public":
        source.chmod(0o644)
    elif kind == "link":
        target = tmp_path / "target.json"
        source.rename(target)
        source.symlink_to(target)
    elif kind == "fifo":
        source.unlink()
        os.mkfifo(source, mode=0o600)
    elif kind == "oversized":
        source.write_bytes(b" " * 1_048_577)
    output = tmp_path / "output.json"
    with pytest.raises((ValueError, OSError)):
        snapshot(source, output)
    assert not output.exists()


def test_foundation_does_not_replace_existing_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    write_values(source, foundation_values())
    output.write_text("preserved", encoding="utf-8")
    with pytest.raises(FileExistsError):
        snapshot(source, output)
    assert output.read_text(encoding="utf-8") == "preserved"
