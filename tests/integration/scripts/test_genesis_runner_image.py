"""Exact local Genesis runner-image planning and apply regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_runner_image as command  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_runner_image_contract import (  # noqa: E402
    _EXPECTED_RESOURCE_TYPES,
    CLAIM_NAME,
    PLAN_JSON_NAME,
    PLAN_NAME,
    RECEIPT_NAME,
    REVIEW_NAME,
    RunnerImageInputs,
    add_source_image_version,
    create_review,
    executor_identity_digest,
    hash_tree,
    load_review,
    load_runner_image_inputs,
    materialize_foundation_image_input,
    snapshot_terraform_root,
)

TENANT = "00000000-0000-0000-0000-000000000000"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
BINDING = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
SOURCE = subprocess.run(
    ["/usr/bin/git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def _private_json(path: Path, value: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def _profile(path: Path) -> ProvisionProfile:
    profile = ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=BINDING,
        connectivity="offline",
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=500,
    )
    write_profile(path, profile)
    return profile


def _claim_for_receipt(receipt: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-runner-image-apply-claim.v1",
        "state": "applying",
        "review_digest": receipt["review_digest"],
        "plan_digest": receipt["plan_digest"],
        "target_binding": receipt["target_binding"],
        "source_commit": receipt["source_commit"],
        "run_digest": receipt["run_digest"],
        "environment": receipt["environment"],
        "region": receipt["region"],
        "profile_digest": receipt["profile_digest"],
        "approver_actor_digest": "2" * 64,
        "credential_actor_digest": "2" * 64,
        "executor_identity_digest": receipt["executor_identity_digest"],
        "idempotency_key": canonical_digest(
            {
                "target_binding": receipt["target_binding"],
                "plan_digest": receipt["plan_digest"],
            }
        ),
        "claimed_at": "2026-09-10T00:00:00+00:00",
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _write_review_for_receipt(directory: Path, receipt: dict[str, object]) -> None:
    plan = b"exact-plan"
    (directory / PLAN_NAME).write_bytes(plan)
    (directory / PLAN_NAME).chmod(0o600)
    review: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-plan.v1",
        "state": "review",
        "target_binding": receipt["target_binding"],
        "source_commit": receipt["source_commit"],
        "run_digest": receipt["run_digest"],
        "environment": receipt["environment"],
        "region": receipt["region"],
        "profile_digest": receipt["profile_digest"],
        "toolchain_digest": receipt["toolchain_digest"],
        "terraform_digest": "4" * 64,
        "provider_digest": "5" * 64,
        "plan_digest": command.hashlib.sha256(plan).hexdigest(),
        "created_at": "2026-09-10T00:00:00+00:00",
        "expires_at": "2026-09-10T01:00:00+00:00",
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    review["review_digest"] = canonical_digest(review)
    receipt["plan_digest"] = review["plan_digest"]
    receipt["review_digest"] = review["review_digest"]
    receipt["executor_identity_digest"] = executor_identity_digest(review)
    _private_json(directory / REVIEW_NAME, review)


def _foundation_values(source_commit: str = SOURCE) -> dict[str, object]:
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
        "build_address_space": "10.41.0.0/16",
        "build_subnet_prefix": "10.41.0.0/26",
        "firewall_subnet_prefix": "10.41.0.64/26",
        "firewall_management_subnet_prefix": "10.41.0.128/26",
        "runner_ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA==",
        "runner_source_image_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.Compute/images/example"
        ),
        "source_commit": source_commit,
        "run_digest": "b" * 64,
        "foundation_context_digest": "c" * 64,
        "runner_image_toolchain_digest": "d" * 64,
        "enable_public_egress": True,
    }


def _inputs(tmp_path: Path, *, source_commit: str = SOURCE) -> tuple[RunnerImageInputs, Path]:
    profile = tmp_path / "profile.json"
    foundation = tmp_path / "foundation.json"
    destination = tmp_path / "runner-image.json"
    _profile(profile)
    _private_json(foundation, _foundation_values(source_commit))
    inputs = load_runner_image_inputs(
        foundation_variables=foundation,
        profile_path=profile,
        repository_root=ROOT,
        destination=destination,
    )
    return add_source_image_version(
        inputs, version="24.04.202608270", destination=destination
    ), destination


def _plan_projection(values: dict[str, object]) -> dict[str, object]:
    creates = [
        "azapi_resource_action.builder_deallocate",
        "azapi_resource_action.builder_generalize",
        "azapi_resource_action.verifier_deallocate",
        "azapi_resource.builder_deprovision",
        "azurerm_image.runner",
        "azurerm_linux_virtual_machine.builder",
        "azurerm_linux_virtual_machine.verifier",
        "azurerm_firewall.builder",
        "azurerm_firewall_policy.builder",
        "azurerm_firewall_policy_rule_collection_group.builder",
        "azurerm_network_interface.builder",
        "azurerm_network_interface.verifier",
        "azurerm_network_interface_security_group_association.builder",
        "azurerm_network_interface_security_group_association.verifier",
        "azurerm_network_security_group.builder",
        "azurerm_public_ip.firewall",
        "azurerm_public_ip.firewall_management",
        "azurerm_resource_group.image",
        "azurerm_resource_group.staging",
        "azurerm_route.builder_default",
        "azurerm_route_table.builder",
        "azurerm_subnet.builder",
        "azurerm_subnet.firewall",
        "azurerm_subnet.firewall_management",
        "azurerm_subnet_network_security_group_association.builder",
        "azurerm_subnet_route_table_association.builder",
        "azurerm_virtual_machine_extension.builder",
        "azurerm_virtual_machine_extension.verifier",
        "azurerm_virtual_network.builder",
        "terraform_data.await_builder_poweroff",
    ]

    def after(address: str) -> dict[str, object]:
        if address == "azapi_resource_action.builder_deallocate":
            return {"action": "deallocate"}
        if address == "azapi_resource_action.builder_generalize":
            return {"action": "generalize"}
        if address == "azapi_resource_action.verifier_deallocate":
            return {"action": "deallocate"}
        if address == "azapi_resource.builder_deprovision":
            return {
                "body": {
                    "properties": {
                        "treatFailureAsDeploymentFailure": True,
                        "source": {
                            "script": (
                                "systemd-run --unit=fdai-deprovision --on-active=5s "
                                "/bin/bash -c 'cloud-init clean; "
                                "waagent -force -deprovision+user; "
                                "printf complete >/var/lib/fdai/image-deprovisioned; "
                                "systemctl poweroff'"
                            )
                        },
                    }
                }
            }
        if address == "azurerm_image.runner":
            return {"hyper_v_generation": "V2"}
        if address == "azurerm_firewall.builder":
            return {"sku_tier": "Basic"}
        if address == "azurerm_route.builder_default":
            return {"next_hop_type": "VirtualAppliance"}
        if address == "azurerm_firewall_policy_rule_collection_group.builder":
            return {
                "application_rule_collection": [
                    {
                        "action": "Allow",
                        "priority": 100,
                        "rule": [
                            {
                                "protocols": [{"type": "Https", "port": 443}],
                                "source_addresses": [values["build_subnet_prefix"]],
                                "destination_fqdns": [
                                    "*.githubusercontent.com",
                                    "azure.archive.ubuntu.com",
                                    "github.com",
                                    "packages.microsoft.com",
                                    "releases.hashicorp.com",
                                    "security.ubuntu.com",
                                ],
                            },
                            {
                                "protocols": [{"type": "Http", "port": 80}],
                                "source_addresses": [values["build_subnet_prefix"]],
                                "destination_fqdns": [
                                    "azure.archive.ubuntu.com",
                                    "security.ubuntu.com",
                                ],
                            },
                        ],
                    }
                ]
            }
        if address in {
            "azurerm_network_interface.builder",
            "azurerm_network_interface.verifier",
        }:
            return {"ip_configuration": [{"public_ip_address_id": None}]}
        return {}

    return {
        "format_version": "1.2",
        "terraform_version": "1.9.8",
        "complete": True,
        "errored": False,
        "applyable": True,
        "variables": {key: {"value": value} for key, value in values.items()},
        "resource_changes": [
            *[
                {
                    "address": address,
                    "type": _EXPECTED_RESOURCE_TYPES[address],
                    "change": {
                        "actions": ["create"],
                        "before": None,
                        "after": after(address),
                    },
                }
                for address in creates
            ],
            {
                "address": "data.azapi_resource.runner_image",
                "type": _EXPECTED_RESOURCE_TYPES["data.azapi_resource.runner_image"],
                "change": {"actions": ["read"], "before": None, "after": {}},
            },
        ],
    }


def test_inputs_pin_reviewed_toolchain_and_exact_source_image(tmp_path: Path) -> None:
    inputs, destination = _inputs(tmp_path)

    values = json.loads(destination.read_text(encoding="utf-8"))
    assert values["source_image_version"] == "24.04.202608270"
    assert values["github_runner_version"] == "2.337.0"
    assert values["terraform_version"] == "1.9.8"
    assert values["terraform_sha256"] == (
        "186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8"
    )
    assert values["terraform_binary_sha256"] == (
        "7386e89a97d0f24024955acc79ccf693b75b97f7c6383cb9d966e7d59aa5b223"
    )
    assert values["opa_version"] == "0.68.0"
    assert inputs.source_commit == SOURCE
    toolchain = json.loads(
        (ROOT / "infra/genesis-runner-image/toolchain.json").read_text(encoding="utf-8")
    )
    assert inputs.toolchain_digest == canonical_digest(
        {
            "schema_version": "fdai.genesis-runner-image.v1",
            "source_commit": SOURCE,
            "source_image_version": "24.04.202608270",
            **{key: value for key, value in toolchain.items() if key != "schema_version"},
        }
    )
    assert values["runner_ssh_public_key"] == _foundation_values()["runner_ssh_public_key"]
    assert destination.stat().st_mode & 0o777 == 0o600
    assert "runner_source_image_id" not in values


@pytest.mark.parametrize("version", ["latest", "24.04", "24.04?latest", ""])
def test_source_image_version_must_be_exact(tmp_path: Path, version: str) -> None:
    profile = tmp_path / "profile.json"
    foundation = tmp_path / "foundation.json"
    destination = tmp_path / "runner-image.json"
    _profile(profile)
    _private_json(foundation, _foundation_values())
    inputs = load_runner_image_inputs(
        foundation_variables=foundation,
        profile_path=profile,
        repository_root=ROOT,
        destination=destination,
    )
    if version == "24.04":
        add_source_image_version(inputs, version=version, destination=destination)
    else:
        with pytest.raises(ValueError, match="not exact"):
            add_source_image_version(inputs, version=version, destination=destination)


def test_review_binds_plan_projection_and_rejects_tampering(tmp_path: Path) -> None:
    inputs, _ = _inputs(tmp_path)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    (work / PLAN_NAME).write_bytes(b"exact-plan")
    (work / PLAN_NAME).chmod(0o600)
    _private_json(work / PLAN_JSON_NAME, _plan_projection(inputs.terraform_values))

    review = create_review(
        directory=work,
        inputs=inputs,
        root_digest="d" * 64,
        terraform_digest="e" * 64,
        provider_digest="f" * 64,
    )

    verified = load_review(work, expected_review_digest=str(review["review_digest"]))
    assert verified["plan_digest"] == review["plan_digest"]
    assert verified["create_count"] == 30
    assert verified["retained_resource_count"] == 26
    assert verified["effect_summary"]["public_ip_count"] == 2
    assert verified["effect_summary"]["monthly_fixed_cost_upper_bound_usd"] == 500
    assert verified["effect_summary"]["approved_monthly_cost_ceiling_usd"] == 500
    assert verified["effect_summary"]["egress_class"] == "fqdn-allowlisted-firewall-basic"
    assert verified["apply_authorized"] is False
    with (work / PLAN_NAME).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="plan digest"):
        load_review(work, expected_review_digest=str(review["review_digest"]))


def test_expired_image_review_is_usable_only_for_claimed_effect_verification(
    tmp_path: Path,
) -> None:
    inputs, _ = _inputs(tmp_path)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    (work / PLAN_NAME).write_bytes(b"exact-plan")
    (work / PLAN_NAME).chmod(0o600)
    _private_json(work / PLAN_JSON_NAME, _plan_projection(inputs.terraform_values))
    review = create_review(
        directory=work,
        inputs=inputs,
        root_digest="d" * 64,
        terraform_digest="e" * 64,
        provider_digest="f" * 64,
    )
    retained = json.loads((work / REVIEW_NAME).read_text(encoding="utf-8"))
    retained["created_at"] = "2000-01-01T00:00:00+00:00"
    retained["expires_at"] = "2000-01-01T01:00:00+00:00"
    retained.pop("review_digest")
    retained["review_digest"] = canonical_digest(retained)
    (work / REVIEW_NAME).unlink()
    _private_json(work / REVIEW_NAME, retained)

    with pytest.raises(ValueError, match="expired"):
        load_review(work, expected_review_digest=str(retained["review_digest"]))
    verified = load_review(
        work,
        expected_review_digest=str(retained["review_digest"]),
        require_unexpired=False,
    )

    assert verified["plan_digest"] == review["plan_digest"]


def test_root_digest_ignores_only_post_apply_state(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    before = hash_tree(root)
    (root / "terraform.tfstate").write_text("{}\n", encoding="utf-8")
    assert hash_tree(root) == before
    (root / "main.tf").write_text('terraform { required_version = ">= 1.9" }\n')
    assert hash_tree(root) != before


def test_review_rejects_storage_or_incomplete_direct_builder_graph(tmp_path: Path) -> None:
    inputs, _ = _inputs(tmp_path)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    (work / PLAN_NAME).write_bytes(b"exact-plan")
    (work / PLAN_NAME).chmod(0o600)
    projection = _plan_projection(inputs.terraform_values)
    projection["resource_changes"].append(
        {
            "address": "azurerm_storage_account.hidden_staging",
            "type": "azurerm_storage_account",
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    )
    _private_json(work / PLAN_JSON_NAME, projection)

    with pytest.raises(ValueError, match="unexpected resource type"):
        create_review(
            directory=work,
            inputs=inputs,
            root_digest="d" * 64,
            terraform_digest="e" * 64,
            provider_digest="f" * 64,
        )


def test_terraform_snapshot_reads_exact_git_objects_not_worktree(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source = repository / "infra" / "genesis-runner-image"
    source.mkdir(parents=True)
    tracked = source / "main.tf"
    tracked.write_text("terraform {}\n", encoding="utf-8")
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["/usr/bin/git", "add", "infra/genesis-runner-image/main.tf"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "user.name=FDAI Test",
            "-c",
            "user.email=fdai-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=repository,
        check=True,
    )
    tracked.write_text('resource "unsafe" "worktree" {}\n', encoding="utf-8")
    destination = tmp_path / "snapshot"

    commit = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    snapshot_terraform_root(source, destination, source_commit=commit)

    assert (destination / "main.tf").read_text(encoding="utf-8") == "terraform {}\n"


def test_apply_writes_claim_once_and_requires_independent_image_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_commit = command._capture(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=30, reason="test"
    ).strip()
    inputs, variables = _inputs(tmp_path, source_commit=source_commit)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    root = work / "root"
    root.mkdir(mode=0o700)
    (root / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    (root / "main.tf").chmod(0o600)
    variables.replace(work / "runner-image.auto.tfvars.json")
    terraform = tmp_path / "terraform"
    terraform.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    terraform.chmod(0o755)
    provider_root = work / "terraform-data"
    provider_root.mkdir(mode=0o700)
    provider = provider_root / "provider"
    provider.write_bytes(b"sealed-provider")
    provider.chmod(0o700)
    (work / PLAN_NAME).write_bytes(b"exact-plan")
    (work / PLAN_NAME).chmod(0o600)
    _private_json(work / PLAN_JSON_NAME, _plan_projection(inputs.terraform_values))
    review = create_review(
        directory=work,
        inputs=inputs,
        root_digest=hash_tree(root),
        terraform_digest=command._file_digest(terraform),
        provider_digest=command._execution_tree_digest(provider_root),
    )
    profile = tmp_path / "apply-profile.json"
    _profile(profile)
    image_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        "providers/Microsoft.Compute/images/runner"
    )
    builder_vm_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        "providers/Microsoft.Compute/virtualMachines/builder"
    )
    verifier_vm_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        "providers/Microsoft.Compute/virtualMachines/verifier"
    )
    builder_extension = f"{builder_vm_id}/extensions/install"
    verifier_extension = f"{verifier_vm_id}/extensions/verify"
    calls: list[list[str]] = []

    for name in (
        "ARM_RESOURCE_PROVIDER_REGISTRATIONS",
        "ARM_SUBSCRIPTION_ID",
        "ARM_TENANT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setattr(command.GenesisChecks, "verify_target", lambda *a, **kw: None)
    monkeypatch.setattr(command.GenesisChecks, "verify_source", lambda *a, **kw: None)
    monkeypatch.setattr(command, "_required", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(
        command,
        "load_genesis_approval",
        lambda *a, **kw: SimpleNamespace(
            actor_digest=command.hashlib.sha256(
                (f"{inputs.run_digest}:{TENANT}:00000000-0000-0000-0000-000000000002").encode()
            ).hexdigest(),
            authorizes=lambda *a, **kw: True,
        ),
    )

    def capture(cmd: list[str], **_: object) -> str:
        if cmd[:3] == ["/usr/bin/git", "rev-parse", "HEAD"]:
            return source_commit + "\n"
        if cmd[:3] == ["/usr/bin/az", "account", "show"]:
            return json.dumps({"type": "user", "tenantId": TENANT})
        if cmd[:4] == ["/usr/bin/az", "ad", "signed-in-user", "show"]:
            return "00000000-0000-0000-0000-000000000002\n"
        if cmd[1:4] == ["output", "-json", "runner_image"]:
            return json.dumps(
                {
                    "id": image_id,
                    "location": "koreacentral",
                    "source_commit": source_commit,
                    "toolchain_digest": inputs.toolchain_digest,
                    "builder_vm_id": builder_vm_id,
                    "verifier_vm_id": verifier_vm_id,
                    "builder_extension": builder_extension,
                    "verifier_extension": verifier_extension,
                    "runner_registered": False,
                    "subscription_ready": False,
                }
            )
        if cmd[:3] == ["/usr/bin/az", "resource", "show"] and cmd[4] == image_id:
            return json.dumps(
                {
                    "id": image_id,
                    "type": "Microsoft.Compute/images",
                    "location": "koreacentral",
                    "provisioningState": "Succeeded",
                    "sourceVm": builder_vm_id,
                    "hyperVGeneration": "V2",
                    "osState": "Generalized",
                    "osType": "Linux",
                    "tags": {
                        "fdai:source-commit": source_commit,
                        "fdai:run-digest": inputs.run_digest,
                        "fdai:toolchain-digest": inputs.toolchain_digest,
                    },
                }
            )
        if cmd[:4] == ["/usr/bin/az", "vm", "extension", "show"]:
            assert cmd[4] == "--ids"
            assert cmd[5] in {
                builder_extension,
                verifier_extension,
            }
            return json.dumps(
                {
                    "id": cmd[5],
                    "type": "Microsoft.Compute/virtualMachines/extensions",
                    "provisioningState": "Succeeded",
                    "statuses": ["ProvisioningState/succeeded"],
                }
            )
        if cmd[:3] == ["/usr/bin/az", "vm", "get-instance-view"]:
            return "1\n"
        if cmd[:3] == ["/usr/bin/az", "vm", "show"]:
            assert cmd[4] == verifier_vm_id
            return image_id + "\n"
        raise AssertionError(cmd)

    monkeypatch.setattr(command, "_capture", capture)
    args = [
        "apply",
        "--work-dir",
        str(work),
        "--profile",
        str(profile),
        "--terraform",
        str(terraform),
        "--expected-review-digest",
        str(review["review_digest"]),
        "--expected-plan-digest",
        str(review["plan_digest"]),
        "--repository",
        "example/repository",
        "--approval-file",
        str(tmp_path / "approval.json"),
        "--approve",
        "--output",
        "json",
    ]

    assert command.main(args) == 0
    assert len(calls) == 1
    assert calls[0][1] == "apply"
    assert (work / CLAIM_NAME).is_file()
    receipt = json.loads((work / RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["runner_image_id"] == image_id
    assert receipt["effect_verified"] is True
    assert receipt["subscription_ready"] is False
    assert receipt["claim_digest"]
    assert receipt["approver_actor_digest"] == receipt["credential_actor_digest"]
    assert receipt["executor_identity_digest"] != receipt["approver_actor_digest"]
    assert command.main(args) == 0
    assert len(calls) == 1


def test_direct_apply_without_exact_approval_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "load_genesis_approval", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="exact approval"):
        command._require_apply_approval(
            None,
            review={
                "run_digest": "a" * 64,
                "source_commit": "b" * 40,
                "review_digest": "c" * 64,
                "plan_digest": "d" * 64,
            },
        )


@pytest.mark.parametrize("name", ["TF_VAR_password", "TF_LOG", "ARM_CLIENT_SECRET"])
def test_terraform_environment_rejects_ambient_authority_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    for key in tuple(os.environ):
        if key.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG", "ARM_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(name, "redacted-test-value")

    with pytest.raises(ValueError, match="ambient Terraform control"):
        command._terraform_environment(
            tmp_path,
            subscription_id=SUBSCRIPTION,
            tenant_id=TENANT,
        )


def test_terraform_environment_uses_private_empty_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in tuple(os.environ):
        if key.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG", "ARM_")):
            monkeypatch.delenv(key, raising=False)
    ambient_home = tmp_path / "ambient-home"
    ambient_home.mkdir(mode=0o700)
    (ambient_home / ".terraformrc").write_text("provider_installation {}\n")
    azure_config = tmp_path / "azure"
    azure_config.mkdir(mode=0o700)
    github_config = tmp_path / "gh"
    github_config.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(ambient_home))
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(azure_config))
    monkeypatch.setenv("GH_CONFIG_DIR", str(github_config))
    monkeypatch.setenv("HTTPS_PROXY", "http://unreviewed.invalid")
    work = tmp_path / "work"
    work.mkdir(mode=0o700)

    environment = command._terraform_environment(
        work,
        subscription_id=SUBSCRIPTION,
        tenant_id=TENANT,
    )

    assert environment["HOME"] != str(ambient_home)
    assert Path(environment["TF_CLI_CONFIG_FILE"]).read_bytes() == b""
    assert environment["AZURE_CONFIG_DIR"] == str(azure_config)
    assert environment["GH_CONFIG_DIR"] == str(github_config)
    assert "HTTPS_PROXY" not in environment
    assert environment["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def test_provider_drift_is_rejected_before_apply_claim(tmp_path: Path) -> None:
    provider_root = tmp_path / "terraform-data"
    provider_root.mkdir(mode=0o700)
    provider = provider_root / "provider"
    provider.write_bytes(b"changed")
    provider.chmod(0o700)
    assert command._execution_tree_digest(provider_root) != "f" * 64
    assert not (tmp_path / CLAIM_NAME).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approver_actor_digest", "not-a-digest"),
        ("credential_actor_digest", "e" * 64),
        ("executor_identity_digest", "f" * 64),
        ("claimed_at", "not-a-time"),
    ],
)
def test_apply_claim_rejects_invalid_authority_metadata(
    tmp_path: Path, field: str, value: str
) -> None:
    review = {
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "target_binding": "c" * 64,
        "source_commit": "d" * 40,
        "run_digest": "1" * 64,
        "environment": "dev",
        "region": "koreacentral",
        "profile_digest": "2" * 64,
        "terraform_digest": "3" * 64,
        "provider_digest": "4" * 64,
    }
    claim = {
        "schema_version": "fdai.genesis-runner-image-apply-claim.v1",
        "state": "applying",
        **review,
        "approver_actor_digest": "f" * 64,
        "credential_actor_digest": "f" * 64,
        "executor_identity_digest": executor_identity_digest(review),
        "idempotency_key": canonical_digest(
            {
                "target_binding": review["target_binding"],
                "plan_digest": review["plan_digest"],
            }
        ),
        "claimed_at": command._utc_now().replace(microsecond=0).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    claim[field] = value
    path = tmp_path / "claim.json"
    _private_json(path, claim)

    with pytest.raises(ValueError, match="claim"):
        command._load_apply_claim(path, review=review)


def test_child_timeout_uses_stable_reason_without_command_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise command.subprocess.TimeoutExpired(["tool", "/private/path"], 1)

    monkeypatch.setattr(command, "run_with_heartbeat", timeout)

    with pytest.raises(ValueError, match="^stable_reason$"):
        command._capture(
            ["tool", "/private/path"],
            cwd=tmp_path,
            timeout=1,
            reason="stable_reason",
        )


def test_new_genesis_image_entrypoints_remain_python_310_compatible() -> None:
    for path in (
        SCRIPT_DIR / "genesis_runner_image.py",
        SCRIPT_DIR / "genesis_runner_image_contract.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "from datetime import UTC" not in source
        compile(source, str(path), "exec")


def test_verified_image_receipt_materializes_new_private_foundation_input(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile.json"
    source = tmp_path / "foundation.json"
    receipt_path = tmp_path / "image-receipt.json"
    destination = tmp_path / "foundation-with-image.json"
    profile_digest = canonical_digest(_profile(profile).to_mapping())
    _private_json(source, _foundation_values())
    image_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        "providers/Microsoft.Compute/images/verified-runner"
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": "e" * 64,
        "plan_digest": "f" * 64,
        "target_binding": BINDING,
        "source_commit": SOURCE,
        "run_digest": "b" * 64,
        "environment": "dev",
        "region": "koreacentral",
        "profile_digest": profile_digest,
        "toolchain_digest": "1" * 64,
        "approver_actor_digest": "2" * 64,
        "credential_actor_digest": "2" * 64,
        "executor_identity_digest": "3" * 64,
        "runner_image_id": image_id,
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    _write_review_for_receipt(tmp_path, receipt)
    claim = _claim_for_receipt(receipt)
    receipt["claim_digest"] = canonical_digest(claim)
    receipt["receipt_digest"] = canonical_digest(receipt)
    _private_json(tmp_path / CLAIM_NAME, claim)
    _private_json(receipt_path, receipt)

    result = materialize_foundation_image_input(
        source=source,
        image_receipt=receipt_path,
        profile_path=profile,
        destination=destination,
    )

    values = json.loads(destination.read_text(encoding="utf-8"))
    assert values["runner_source_image_id"] == image_id
    assert values["runner_image_toolchain_digest"] == "1" * 64
    assert result["state"] == "prepared"
    assert result["mutation_performed"] is False
    assert destination.stat().st_mode & 0o777 == 0o600


def test_foundation_input_rejects_wrong_target_image_receipt(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    source = tmp_path / "foundation.json"
    receipt_path = tmp_path / "image-receipt.json"
    destination = tmp_path / "output.json"
    profile_digest = canonical_digest(_profile(profile).to_mapping())
    _private_json(source, _foundation_values())
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": "e" * 64,
        "plan_digest": "f" * 64,
        "target_binding": "9" * 64,
        "source_commit": SOURCE,
        "run_digest": "b" * 64,
        "environment": "dev",
        "region": "koreacentral",
        "profile_digest": profile_digest,
        "toolchain_digest": "1" * 64,
        "approver_actor_digest": "2" * 64,
        "credential_actor_digest": "2" * 64,
        "executor_identity_digest": "3" * 64,
        "runner_image_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.Compute/images/verified-runner"
        ),
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    _write_review_for_receipt(tmp_path, receipt)
    claim = _claim_for_receipt(receipt)
    receipt["claim_digest"] = canonical_digest(claim)
    receipt["receipt_digest"] = canonical_digest(receipt)
    _private_json(tmp_path / CLAIM_NAME, claim)
    _private_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="does not match"):
        materialize_foundation_image_input(
            source=source,
            image_receipt=receipt_path,
            profile_path=profile,
            destination=destination,
        )

    assert not destination.exists()


def test_foundation_input_rejects_profile_replay(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    source = tmp_path / "foundation.json"
    receipt_path = tmp_path / "image-receipt.json"
    destination = tmp_path / "output.json"
    profile_digest = canonical_digest(_profile(profile).to_mapping())
    _private_json(source, _foundation_values())
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": "e" * 64,
        "plan_digest": "f" * 64,
        "target_binding": BINDING,
        "source_commit": SOURCE,
        "run_digest": "b" * 64,
        "environment": "dev",
        "region": "eastus",
        "profile_digest": profile_digest,
        "toolchain_digest": "1" * 64,
        "approver_actor_digest": "2" * 64,
        "credential_actor_digest": "2" * 64,
        "executor_identity_digest": "3" * 64,
        "runner_image_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            "providers/Microsoft.Compute/images/verified-runner"
        ),
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    _write_review_for_receipt(tmp_path, receipt)
    claim = _claim_for_receipt(receipt)
    receipt["claim_digest"] = canonical_digest(claim)
    receipt["receipt_digest"] = canonical_digest(receipt)
    _private_json(tmp_path / CLAIM_NAME, claim)
    _private_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="does not match"):
        materialize_foundation_image_input(
            source=source,
            image_receipt=receipt_path,
            profile_path=profile,
            destination=destination,
        )


def test_apply_json_output_excludes_resource_identity_and_state_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "target_binding": "c" * 64,
        "source_commit": "d" * 40,
        "toolchain_digest": "e" * 64,
        "runner_image_id": "/subscriptions/private/resourceGroups/private/providers/image",
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
        "receipt_digest": "f" * 64,
    }

    command._print(receipt, "json", "unused")

    output = capsys.readouterr().out
    assert "runner_image_id" not in output
    assert "terraform.tfstate" not in output
    assert "/subscriptions/" not in output
