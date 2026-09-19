from __future__ import annotations

import hashlib
import json
import os
import subprocess
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application, standalone_host
from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.contracts import canonical_digest


@pytest.mark.parametrize("artifact_directory", ["kit-work/verified", "source-work/verified"])
def test_runtime_support_uses_only_admitted_artifact_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact_directory: str
) -> None:
    artifact_root = tmp_path / artifact_directory
    wheels = artifact_root / "support/python"
    wheels.mkdir(parents=True)
    wheel = wheels / "example-1.0-py3-none-any.whl"
    wheel.write_bytes(b"synthetic-wheel")
    decoy = tmp_path / "other-artifacts/support/python"
    decoy.mkdir(parents=True)
    (decoy / "unexpected.whl").write_bytes(b"not-selected")
    calls: list[tuple[str, ...]] = []

    def capture(command, **kwargs):
        assert kwargs["cwd"] == tmp_path
        calls.append(command)

    monkeypatch.setattr(standalone_host, "_run", capture)
    standalone_host._install_runtime_support(tmp_path, artifact_root=artifact_root)

    assert len(calls) == 2
    assert calls[1] == (
        str(tmp_path / "runtime-venv/bin/pip"),
        "install",
        "--no-index",
        "--no-cache-dir",
        str(wheel),
    )


def test_runtime_support_does_not_fall_back_to_kit(tmp_path: Path, monkeypatch) -> None:
    decoy = tmp_path / "kit-work/verified/support/python"
    decoy.mkdir(parents=True)
    (decoy / "unexpected.whl").write_bytes(b"not-selected")

    def unexpected(*args, **kwargs):
        pytest.fail("missing admitted support must not execute an installer")

    monkeypatch.setattr(standalone_host, "_run", unexpected)
    with pytest.raises(ValueError, match="wheelhouse is empty"):
        standalone_host._install_runtime_support(
            tmp_path, artifact_root=tmp_path / "source-work/verified"
        )


def test_foundation_application_workload_matches_resource_group_name() -> None:
    assert (
        standalone_host._foundation_application_workload(
            {"name": "rg-fdaiaks-dev-wus2"},
            environment="dev",
            region_short="wus2",
        )
        == "fdaiaks"
    )


@pytest.mark.parametrize(
    "name",
    [
        "rg-fdaiaks-staging-wus2",
        "rg-fdaiaks-dev-krc",
        "rg-invalid/name-dev-wus2",
    ],
)
def test_foundation_application_workload_rejects_mismatched_name(name: str) -> None:
    with pytest.raises(ValueError, match="Foundation application"):
        standalone_host._foundation_application_workload(
            {"name": name},
            environment="dev",
            region_short="wus2",
        )


def test_aks_baseline_defers_detailed_private_networking() -> None:
    source = Path(standalone_host.__file__).read_text(encoding="utf-8")

    assert '"enable_private_networking": not aks_baseline' in source
    assert '"acr_sku": "Basic" if aks_baseline else "Premium"' in source


@pytest.mark.parametrize(
    ("hostname", "origin"),
    [
        (
            "calm-field-012345678.3.azurestaticapps.net",
            "https://calm-field-012345678.3.azurestaticapps.net",
        ),
        (
            "calm-field-012345678.azurestaticapps.net",
            "https://calm-field-012345678.azurestaticapps.net",
        ),
    ],
)
def test_console_origin_accepts_deployed_static_web_app_hostname(
    hostname: str, origin: str
) -> None:
    assert standalone_host._console_origin(hostname) == origin


@pytest.mark.parametrize(
    "hostname",
    [
        "https://calm-field.azurestaticapps.net",
        "calm-field.example.com",
        "calm-field.azurestaticapps.net/path",
        "CALM-FIELD.azurestaticapps.net",
    ],
)
def test_console_origin_rejects_noncanonical_hostname(hostname: str) -> None:
    with pytest.raises(ValueError, match="Static Web App hostname"):
        standalone_host._console_origin(hostname)


@pytest.mark.parametrize("observed_nsg", ["", "same-subscription"])
def test_subnet_network_security_group_reads_exact_selected_subnet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observed_nsg: str,
) -> None:
    subscription_id = "00000000-0000-0000-0000-000000000001"
    subnet_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/rg-network/providers/"
        "Microsoft.Network/virtualNetworks/vnet-aks/subnets/snet-aks"
    )
    nsg_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/rg-network/providers/"
        "Microsoft.Network/networkSecurityGroups/nsg-aks"
    )
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], **kwargs: object) -> str:
        calls.append(command)
        assert kwargs == {
            "cwd": tmp_path,
            "timeout": 60,
            "reason": "AKS subnet network security group readback failed",
        }
        return f"{nsg_id}\n" if observed_nsg else "\n"

    monkeypatch.setattr(standalone_host, "_capture", capture)

    assert standalone_host._subnet_network_security_group(
        subnet_id,
        context={"subscription_id": subscription_id},
        cwd=tmp_path,
    ) == (nsg_id if observed_nsg else "")
    assert calls == [
        (
            "az",
            "network",
            "vnet",
            "subnet",
            "show",
            "--ids",
            subnet_id,
            "--subscription",
            subscription_id,
            "--query",
            "networkSecurityGroup.id",
            "--output",
            "tsv",
            "--only-show-errors",
        )
    ]


@pytest.mark.parametrize("resource", ["subnet", "nsg"])
@pytest.mark.parametrize("failure", ["malformed", "foreign"])
def test_subnet_network_security_group_rejects_invalid_resource_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    failure: str,
) -> None:
    subscription_id = "00000000-0000-0000-0000-000000000001"
    observed_subscription = (
        "00000000-0000-0000-0000-000000000002" if failure == "foreign" else subscription_id
    )
    subnet_id = (
        f"/subscriptions/{observed_subscription}/resourceGroups/rg-network/providers/"
        "Microsoft.Network/virtualNetworks/vnet-aks/subnets/snet-aks"
    )
    nsg_id = (
        f"/subscriptions/{observed_subscription}/resourceGroups/rg-network/providers/"
        "Microsoft.Network/networkSecurityGroups/nsg-aks"
    )
    if failure == "malformed":
        subnet_id = "/not-a-subnet" if resource == "subnet" else subnet_id
        nsg_id = "/not-an-nsg" if resource == "nsg" else nsg_id

    def capture(*_args: object, **_kwargs: object) -> str:
        if resource == "subnet":
            pytest.fail("invalid subnet IDs must be rejected before Azure CLI execution")
        return nsg_id

    monkeypatch.setattr(standalone_host, "_capture", capture)

    with pytest.raises(ValueError, match="subnet|network security group"):
        standalone_host._subnet_network_security_group(
            subnet_id,
            context={"subscription_id": subscription_id},
            cwd=tmp_path,
        )


def test_browser_console_binding_reads_owning_terraform_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subscription_id = "00000000-0000-0000-0000-000000000001"
    context = {
        "subscription_id": subscription_id,
        "infra": str(tmp_path / "substrate"),
        "workloads_infra": str(tmp_path / "workloads"),
    }
    values = {
        "console_default_hostname": "calm-field-012345678.3.azurestaticapps.net",
        "console_static_web_app_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-app/providers/"
            "Microsoft.Web/staticSites/swa-console"
        ),
        "browser_gateway_operator_url": "https://apim-fdai.azure-api.net/",
        "browser_gateway_ingestion_url": "https://apim-fdai.azure-api.net/ingestion/",
    }
    activations: list[str] = []
    reads: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        standalone_host,
        "_activate_terraform_stage",
        lambda stage, *_args: activations.append(stage),
    )

    def terraform_output(infra: Path, name: str) -> str:
        reads.append((infra, name))
        return values[name]

    monkeypatch.setattr(standalone_host, "_terraform_output", terraform_output)

    assert standalone_host._browser_console_binding(context, tmp_path) == {
        "console_hostname": values["console_default_hostname"],
        "console_origin": f"https://{values['console_default_hostname']}",
        "console_static_web_app_id": values["console_static_web_app_id"],
        "operator_api_base_url": "https://apim-fdai.azure-api.net",
        "ingestion_api_base_url": "https://apim-fdai.azure-api.net/ingestion",
    }
    assert activations == ["substrate", "application"]
    assert reads == [
        (tmp_path / "substrate", "console_default_hostname"),
        (tmp_path / "substrate", "console_static_web_app_id"),
        (tmp_path / "workloads", "browser_gateway_operator_url"),
        (tmp_path / "workloads", "browser_gateway_ingestion_url"),
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("console_default_hostname", "console.example.com", "hostname"),
        ("console_static_web_app_id", "/not-a-static-site", "resource ID"),
        (
            "browser_gateway_operator_url",
            "https://gateway.example.com",
            "Operator URL",
        ),
        (
            "browser_gateway_ingestion_url",
            "https://apim-fdai.azure-api.net/wrong",
            "ingestion URL",
        ),
    ],
)
def test_browser_console_binding_rejects_invalid_cross_state_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    message: str,
) -> None:
    subscription_id = "00000000-0000-0000-0000-000000000001"
    values = {
        "console_default_hostname": "calm-field-012345678.3.azurestaticapps.net",
        "console_static_web_app_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-app/providers/"
            "Microsoft.Web/staticSites/swa-console"
        ),
        "browser_gateway_operator_url": "https://apim-fdai.azure-api.net",
        "browser_gateway_ingestion_url": "https://apim-fdai.azure-api.net/ingestion",
    }
    values[field] = value
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_args: None)
    monkeypatch.setattr(
        standalone_host,
        "_terraform_output",
        lambda _infra, name: values[name],
    )

    with pytest.raises(ValueError, match=message):
        standalone_host._browser_console_binding(
            {
                "subscription_id": subscription_id,
                "infra": str(tmp_path / "substrate"),
                "workloads_infra": str(tmp_path / "workloads"),
            },
            tmp_path,
        )


def _review() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "substrate",
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "summary": {"action_counts": {"create": 1}},
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    value["review_digest"] = canonical_digest(value)
    return value


def _context(review: dict[str, object]) -> dict[str, object]:
    return {
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
    }


def test_standalone_plan_summary_counts_replacements_once() -> None:
    result = standalone_host._plan_summary(
        {
            "resource_changes": [
                {
                    "address": "azurerm_resource_group.main",
                    "type": "azurerm_resource_group",
                    "change": {"actions": ["create"]},
                },
                {
                    "address": "azurerm_linux_virtual_machine.runner",
                    "type": "azurerm_linux_virtual_machine",
                    "change": {"actions": ["delete", "create"]},
                },
                {
                    "address": "azurerm_container_app.core",
                    "type": "azurerm_container_app",
                    "change": {"actions": ["update"]},
                },
            ]
        }
    )

    assert result["action_counts"] == {
        "create": 1,
        "update": 1,
        "delete": 0,
        "replace": 1,
        "read": 0,
        "no-op": 0,
    }
    assert result["resource_type_counts"] == {
        "azurerm_container_app": 1,
        "azurerm_linux_virtual_machine": 1,
        "azurerm_resource_group": 1,
    }
    assert result["resource_changes"] == [
        {"address": "azurerm_resource_group.main", "actions": ["create"]},
        {
            "address": "azurerm_linux_virtual_machine.runner",
            "actions": ["delete", "create"],
        },
        {"address": "azurerm_container_app.core", "actions": ["update"]},
    ]


def test_standalone_apply_requires_exact_unexpired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }

    standalone_host._validate_approval(review, approval, context=_context(review))

    approval["plan_digest"] = "e" * 64
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_apply_rejects_expired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }

    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_checkpoint_lock_allows_only_one_writer(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    first = standalone_host._acquire_checkpoint_lock(tmp_path)
    try:
        with pytest.raises(ValueError, match="already running"):
            standalone_host._acquire_checkpoint_lock(tmp_path)
    finally:
        os.close(first)

    second = standalone_host._acquire_checkpoint_lock(tmp_path)
    os.close(second)


def test_standalone_apply_rejects_tampered_review_and_context() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }
    review["summary"] = {"action_counts": {"delete": 1}}
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))

    review = _review()
    approval["review_digest"] = review["review_digest"]
    approval["plan_digest"] = review["plan_digest"]
    approval["target_binding"] = review["target_binding"]
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(
            review,
            approval,
            context={**_context(review), "target_binding": "e" * 64},
        )


def test_remote_preparation_uses_only_fixed_argument_commands(tmp_path: Path) -> None:
    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def ssh(self, command: tuple[str, ...], *, timeout: int):
            del timeout
            self.commands.append(command)
            stdout = "a" * 64 + "  kit.tar.gz\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del source, destination, timeout

    tunnel = Tunnel()
    inputs = []
    for name in ("archive", "handoff", "entra"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        inputs.append(path)
    standalone_application._prepare_remote(
        tunnel,
        remote_root="/home/fdai/.fdai-transfer-abc",
        remote_archive="/home/fdai/.fdai-transfer-abc/kit.tar.gz",
        archive=inputs[0],
        archive_digest="a" * 64,
        handoff_path=inputs[1],
        remote_handoff="/home/fdai/.fdai-transfer-abc/handoff.json",
        entra_path=inputs[2],
        remote_entra="/home/fdai/.fdai-transfer-abc/entra.json",
        app_work="/home/fdai/.fdai-transfer-abc/application",
        timeout_seconds=1800,
    )

    assert all(command[0] not in {"bash", "sh"} for command in tunnel.commands)
    assert any(command[:3] == ("python3", "-m", "venv") for command in tunnel.commands)
    assert tunnel.commands[-1][1:3] == ("-m", "fdai_deployment_cli.standalone_host")


def test_remote_preparation_transfers_exact_adoption_inputs(tmp_path: Path) -> None:
    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []
            self.copies: list[tuple[Path, str]] = []

        def ssh(self, command: tuple[str, ...], *, timeout: int):
            del timeout
            self.commands.append(command)
            stdout = "a" * 64 + "  kit.tar.gz\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del timeout
            self.copies.append((source, destination))

    paths = [
        tmp_path / name for name in ("archive", "handoff", "entra", "state", "models", "adoption")
    ]
    for path in paths:
        path.write_text(path.name, encoding="utf-8")
    adoption = ApplicationStateAdoption(
        state=paths[3],
        resolved_models=paths[4],
        descriptor=paths[5],
        resource_name_suffix="abcdef",
        managed_resource_count=3,
    )
    tunnel = Tunnel()

    standalone_application._prepare_remote(
        tunnel,
        remote_root="/home/fdai/.fdai-transfer-abc",
        remote_archive="/home/fdai/.fdai-transfer-abc/kit.tar.gz",
        archive=paths[0],
        archive_digest="a" * 64,
        handoff_path=paths[1],
        remote_handoff="/home/fdai/.fdai-transfer-abc/handoff.json",
        entra_path=paths[2],
        remote_entra="/home/fdai/.fdai-transfer-abc/entra.json",
        app_work="/home/fdai/.fdai-transfer-abc/application",
        application_state_adoption=adoption,
        remote_adoption_state="/home/fdai/.fdai-transfer-abc/application-state.json",
        remote_adoption_models="/home/fdai/.fdai-transfer-abc/resolved-models.json",
        remote_adoption_descriptor="/home/fdai/.fdai-transfer-abc/adoption.json",
        timeout_seconds=1800,
    )

    assert tunnel.copies[-3:] == [
        (paths[3], "/home/fdai/.fdai-transfer-abc/application-state.json"),
        (paths[4], "/home/fdai/.fdai-transfer-abc/resolved-models.json"),
        (paths[5], "/home/fdai/.fdai-transfer-abc/adoption.json"),
    ]
    prepare = tunnel.commands[-1]
    assert prepare[prepare.index("--adoption-state") + 1].endswith("application-state.json")
    assert prepare[prepare.index("--adoption-models") + 1].endswith("resolved-models.json")
    assert prepare[prepare.index("--adoption-descriptor") + 1].endswith("adoption.json")


def _adoption_inputs(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path]:
    tmp_path.chmod(0o700)
    state = tmp_path / "application-state.json"
    models = tmp_path / "resolved-models.json"
    descriptor_path = tmp_path / "adoption.json"
    payload = {
        "version": 4,
        "serial": 2,
        "lineage": "lineage",
        "resources": [
            {
                "mode": "managed",
                "type": "terraform_data",
                "name": "example",
                "instances": [{"attributes": {"id": "opaque"}}],
            }
        ],
    }
    state.write_text(json.dumps(payload), encoding="utf-8")
    models.write_text("{}", encoding="utf-8")
    descriptor_path.write_text("{}", encoding="utf-8")
    for path in (state, models, descriptor_path):
        path.chmod(0o600)
    descriptor: dict[str, object] = {
        "staged_state_sha256": standalone_host._file_digest(state),
        "managed_resource_count": 1,
    }
    return descriptor, state, models, descriptor_path


@pytest.mark.parametrize("change", ["count", "owner"])
def test_staged_application_state_is_rejected_before_push(tmp_path: Path, change: str) -> None:
    descriptor, state, _models, _descriptor_path = _adoption_inputs(tmp_path)
    if change == "count":
        descriptor["managed_resource_count"] = 2
    else:
        payload = json.loads(state.read_text(encoding="utf-8"))
        payload["resources"].append(
            {
                "module": "module.resource_group",
                "mode": "managed",
                "type": "terraform_data",
                "name": "ownership",
                "instances": [{"attributes": {"input": "managed"}}],
            }
        )
        state.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="count differs|retains a resource-group owner"):
        standalone_host._validate_staged_application_state(state, descriptor)


def test_deployment_binding_uses_terraform_core_app_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "substrate-receipt.json").write_text("{}", encoding="utf-8")
    context = {
        "infra": str(tmp_path / "infra"),
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    context_path.chmod(0o600)
    observed: list[tuple[Path, str]] = []

    def terraform_output(infra: Path, name: str) -> str:
        observed.append((infra, name))
        return "ca-fdai-dev-wus2-core"

    monkeypatch.setattr(standalone_host, "_terraform_output", terraform_output)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    result = standalone_host._deployment_binding(SimpleNamespace(), tmp_path)

    expected = hashlib.sha256(
        (f"{context['tenant_id']}\0{context['subscription_id']}\0ca-fdai-dev-wus2-core").encode()
    ).hexdigest()
    assert result["deployment_binding"] == expected
    assert result["terraform_name_verified"] is True
    assert observed == [(tmp_path / "infra", "core_app_name")]


def test_application_state_adoption_pushes_once_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    expected = state.read_text(encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        calls.append(command)
        if command[:4] == ("az", "storage", "blob", "exists"):
            return "false\n"
        payload = json.loads(expected)
        payload["serial"] += 1
        return json.dumps(payload)

    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda command, **_kwargs: calls.append(tuple(command)),
    )
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert sum(command[:3] == ("terraform", "state", "push") for command in calls) == 1
    assert not state.exists() and not models.exists() and not descriptor_path.exists()
    receipt = json.loads(
        (tmp_path / "application-state-adoption-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["remote_backend_authority_verified"] is True
    assert receipt["remote_state_lineage"] == "lineage"
    assert receipt["remote_state_serial"] == 3
    assert receipt["azure_resource_mutation_performed"] is False
    assert receipt["original_state_retained"] is True


def test_application_state_adoption_claim_resumes_verification_without_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    claim = {
        "schema_version": "fdai.application-state-adoption-claim.v1",
        "target_binding": context["target_binding"],
        "foundation_binding_digest": context["foundation_binding_digest"],
        "adoption_descriptor_digest": canonical_digest(descriptor),
        "staged_state_sha256": descriptor["staged_state_sha256"],
        "managed_resource_count": 1,
        "mutation_performed": False,
    }
    (tmp_path / "application-state-adoption-claim.json").write_text(
        json.dumps(claim), encoding="utf-8"
    )
    (tmp_path / "application-state-adoption-claim.json").chmod(0o600)

    def pull_state(_command: tuple[str, ...], **_kwargs: object) -> str:
        payload = json.loads(state.read_text())
        payload["serial"] += 1
        return json.dumps(payload)

    monkeypatch.setattr(standalone_host, "_capture", pull_state)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("verification resume must not push state"),
    )

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert (tmp_path / "application-state-adoption-receipt.json").is_file()


def test_application_state_adoption_rejects_occupied_or_mismatched_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    monkeypatch.setattr(standalone_host, "_capture", lambda *_args, **_kwargs: "occupied\n")
    with pytest.raises(ValueError, match="existence is invalid"):
        standalone_host._adopt_application_state(
            tmp_path, context, descriptor, state, models, descriptor_path
        )
    assert not (tmp_path / "application-state-adoption-claim.json").exists()

    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda command, **_kwargs: (
            "false\n" if command[:4] == ("az", "storage", "blob", "exists") else "{}"
        ),
    )
    monkeypatch.setattr(standalone_host, "_run", lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="differs"):
        standalone_host._adopt_application_state(
            tmp_path, context, descriptor, state, models, descriptor_path
        )
    assert (tmp_path / "application-state-adoption-claim.json").is_file()
    assert not (tmp_path / "application-state-adoption-receipt.json").exists()


def test_application_state_adoption_receipt_accepts_advanced_same_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, state, models, descriptor_path = _adoption_inputs(tmp_path)
    context = {
        "infra": str(tmp_path),
        "target_binding": "a" * 64,
        "foundation_binding_digest": "b" * 64,
        "state_account": "stateaccount",
        "state_container": "tfstate",
        "state_key": "fdai-dev.tfstate",
    }
    claim = {
        "schema_version": "fdai.application-state-adoption-claim.v1",
        "target_binding": context["target_binding"],
        "foundation_binding_digest": context["foundation_binding_digest"],
        "adoption_descriptor_digest": canonical_digest(descriptor),
        "staged_state_sha256": descriptor["staged_state_sha256"],
        "managed_resource_count": 1,
        "mutation_performed": False,
    }
    receipt = {
        "schema_version": "fdai.application-state-adoption-receipt.v1",
        "state": "adopted",
        "claim_digest": canonical_digest(claim),
        "remote_state_sha256": "c" * 64,
        "remote_state_lineage": "lineage",
        "remote_state_serial": 3,
        "managed_resource_count": 1,
        "remote_backend_authority_verified": True,
        "original_state_retained": True,
        "azure_resource_mutation_performed": False,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    (tmp_path / "application-state-adoption-receipt.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    (tmp_path / "application-state-adoption-receipt.json").chmod(0o600)
    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda *_args, **_kwargs: json.dumps(
            {"version": 4, "serial": 9, "lineage": "lineage", "resources": []}
        ),
    )

    standalone_host._adopt_application_state(
        tmp_path, context, descriptor, state, models, descriptor_path
    )

    assert not state.exists() and not models.exists() and not descriptor_path.exists()


def test_destructive_plan_requires_a_second_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    review = _review()
    review["stage"] = "application"
    review["summary"] = {"action_counts": {"create": 0, "update": 0, "delete": 1, "replace": 1}}
    review["review_digest"] = canonical_digest(
        {key: value for key, value in review.items() if key != "review_digest"}
    )
    answers = iter(("application-apply", "denied"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(standalone_application, "_wait_for_approval_input", lambda _timeout: None)
    monkeypatch.setattr(standalone_application, "_azure_actor_digest", lambda _binding: "d" * 64)

    with pytest.raises(ValueError, match="destructive"):
        standalone_application._approve_plan(tmp_path, review)
    assert not (tmp_path / "application-approval.json").exists()


def test_ambiguous_apply_recovers_by_verification_without_reapply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim_path = tmp_path / "substrate-claim.json"
    claim_path.write_text("claim", encoding="utf-8")
    context = {
        "target_binding": "b" * 64,
        "infra": str(tmp_path),
    }
    review = {"plan_digest": "a" * 64}
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": "substrate",
        "plan_digest": review["plan_digest"],
        "idempotency_key": canonical_digest(
            {
                "target_binding": context["target_binding"],
                "plan_digest": review["plan_digest"],
            }
        ),
    }

    def private_json(path: Path, _label: str):
        if path.name == "context.json":
            return context
        if path.name == "substrate-review.json":
            return review
        return claim

    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    written: dict[str, object] = {}
    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host.subprocess, "run", run)
    monkeypatch.setattr(standalone_host, "_readback_stage", lambda *_: True)
    monkeypatch.setattr(
        standalone_host,
        "_replace_private_json",
        lambda _path, value: written.update(value),
    )

    result = standalone_host._recover_apply(SimpleNamespace(stage="substrate"), tmp_path)

    assert result["verification_only_recovery"] is True
    assert result["control_plane_readback_verified"] is True
    assert commands and commands[0][1] == "plan"
    assert all("apply" not in command for command in commands)
    assert written["state"] == "applied"


def test_aks_stages_use_independent_roots_and_variables(tmp_path: Path) -> None:
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-aks",
        },
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "cluster"),
        "database_infra": str(tmp_path / "database"),
        "workloads_infra": str(tmp_path / "workloads"),
    }

    assert standalone_host._stage_paths("runtime", context, tmp_path) == (
        tmp_path / "cluster",
        tmp_path / "runtime.auto.tfvars.json",
    )
    assert standalone_host._stage_paths("database", context, tmp_path) == (
        tmp_path / "database",
        tmp_path / "database.auto.tfvars.json",
    )
    assert standalone_host._stage_paths("application", context, tmp_path) == (
        tmp_path / "workloads",
        tmp_path / "workloads.auto.tfvars.json",
    )


def test_aks_operational_history_job_is_shadow_and_uses_inventory_identity() -> None:
    identity = {"resource_id": "inventory-resource", "client_id": "inventory-client"}
    job = standalone_host._aks_job(
        {"core-control-plane": "example.azurecr.io/core@sha256:" + "a" * 64},
        identity,
        ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
        "0 * * * *",
        {
            "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": "https://example.invalid/history",
            "FDAI_OPERATIONAL_HISTORY_MODE": "shadow",
            "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS": "32",
        },
        {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
        component="operational-history",
        deadline_seconds=1800,
        retry_limit=0,
    )

    assert job["identity_resource_id"] == identity["resource_id"]
    assert job["identity_client_id"] == identity["client_id"]
    assert job["environment"]["FDAI_OPERATIONAL_HISTORY_MODE"] == "shadow"
    assert "FDAI_OPERATIONAL_HISTORY_AUTHORITY_RECEIPT" not in job["environment"]
    assert job["secret_environment"] == {"FDAI_DATABASE_URL": "fdai-state-store-dsn"}
    assert job["retry_limit"] == 0


def test_aks_job_rejects_missing_core_image() -> None:
    with pytest.raises(TypeError, match="image is unavailable"):
        standalone_host._aks_job(
            {},
            {"resource_id": "inventory-resource", "client_id": "inventory-client"},
            ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
            "0 * * * *",
            {},
            {},
            component="operational-history",
            deadline_seconds=1800,
        )


def test_aks_inventory_binding_uses_projected_service_account_identity() -> None:
    cluster_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-example/providers/"
        "Microsoft.ContainerService/managedClusters/aks-example"
    )

    environment = standalone_host._aks_inventory_binding_environment(f" {cluster_id} ")

    assert environment == {
        "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.default.svc",
        "FDAI_KUBERNETES_CLUSTER_REF": cluster_id,
        "FDAI_KUBERNETES_AUTH_MODE": "service-account",
        "FDAI_KUBERNETES_CA_PATH": ("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"),
        "FDAI_KUBERNETES_TOKEN_PATH": ("/var/run/secrets/kubernetes.io/serviceaccount/token"),
    }
    assert all("SECRET" not in name for name in environment)


@pytest.mark.parametrize(
    "cluster_id",
    ["", "/subscriptions/example/resourceGroups/example", "https://example.com/cluster"],
)
def test_aks_inventory_binding_rejects_non_cluster_identity(cluster_id: str) -> None:
    with pytest.raises(ValueError, match="cluster id is invalid"):
        standalone_host._aks_inventory_binding_environment(cluster_id)


def test_aks_kubernetes_effect_binding_is_namespace_limited() -> None:
    cluster_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-example/providers/"
        "Microsoft.ContainerService/managedClusters/aks-example"
    )

    environment = standalone_host._aks_kubernetes_direct_api_environment(
        cluster_id,
        namespace="fdai-runtime",
    )

    assert json.loads(environment["FDAI_KUBERNETES_DIRECT_API_JSON"]) == {
        "allowed_namespaces": ["fdai-runtime"],
        "api_server": "https://kubernetes.default.svc",
        "ca_path": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        "cluster_ref": cluster_id,
        "token_path": "/var/run/secrets/kubernetes.io/serviceaccount/token",
    }


@pytest.mark.parametrize("namespace", ["", "UPPER", "invalid/name"])
def test_aks_kubernetes_effect_binding_rejects_invalid_namespace(namespace: str) -> None:
    cluster_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-example/providers/"
        "Microsoft.ContainerService/managedClusters/aks-example"
    )

    with pytest.raises(ValueError, match="namespace is invalid"):
        standalone_host._aks_kubernetes_direct_api_environment(
            cluster_id,
            namespace=namespace,
        )


def test_postgres_aks_substrate_excludes_flexible_server() -> None:
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-aks",
        }
    }

    targets = standalone_host._substrate_targets(context)

    assert "module.state_store" not in targets
    assert "azurerm_key_vault_secret.state_store_dsn" not in targets
    assert "azurerm_role_assignment.inventory_kv_secrets_user" not in targets
    assert "module.event_bus" in targets
    assert "module.key_vault" in targets


def test_aks_substrate_includes_application_insights_secret_binding() -> None:
    targets = set(
        standalone_host._substrate_targets(
            {
                "runtime_profile": {
                    "runtime_platform": "aks",
                    "database_placement": "postgres-flex",
                }
            }
        )
    )

    assert "azurerm_application_insights.core" in targets
    assert "azurerm_key_vault_secret.application_insights_connection_string" in targets
    assert "azurerm_role_assignment.core_application_insights_secret_reader" in targets


def test_aks_substrate_includes_document_dependencies_without_container_apps() -> None:
    targets = set(
        standalone_host._substrate_targets(
            {
                "runtime_profile": {
                    "runtime_platform": "aks",
                    "database_placement": "postgres-flex",
                }
            }
        )
    )

    assert {
        "module.ingestion_identity",
        "module.ingestion_worker_identity",
        "module.document_storage",
        "azurerm_key_vault_secret.ingestion_api_dsn",
        "azurerm_key_vault_secret.ingestion_worker_dsn",
        "azurerm_role_assignment.ingestion_aks_eventhubs_sender",
        "azurerm_role_assignment.ingestion_worker_aks_eventhubs_receiver",
        "azurerm_role_assignment.inventory_reader",
        "azurerm_role_assignment.inventory_monitoring_reader",
        "azurerm_role_assignment.inventory_log_analytics_reader",
        "azurerm_role_assignment.inventory_cost_reader",
        "azurerm_role_assignment.inventory_kubernetes_reader",
        "azurerm_role_assignment.inventory_stage_sender",
    } <= targets
    assert "module.ingestion_gateway" not in targets


@pytest.mark.parametrize("existing", [False, True])
def test_aks_kubeconfig_uses_explicit_host_identity(tmp_path, monkeypatch, existing):
    tmp_path.chmod(0o700)
    kubeconfig = tmp_path / "aks.kubeconfig"
    if existing:
        kubeconfig.write_text("prior kubeconfig")
        kubeconfig.chmod(0o600)
    context = {
        "client_id": "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kubeconfig.stat().st_mode & 0o777 == 0o600
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] in (60, 180)
        kubeconfig.write_text("generated kubeconfig")

    monkeypatch.setattr(standalone_host, "_run", run)
    reads = []

    def capture(command, **kwargs):
        reads.append(command)
        assert command[:3] == ("kubectl", "config", "view")
        assert "--minify" in command and "--raw" not in command
        return json.dumps(
            {
                "users": [
                    {
                        "user": {
                            "exec": {
                                "command": "kubelogin",
                                "args": [
                                    "get-token",
                                    "--login",
                                    "msi",
                                    "--client-id",
                                    context["client_id"],
                                ],
                            }
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(standalone_host, "_capture", capture)
    assert (
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )
        == kubeconfig
    )
    assert commands[0][commands[0].index("--subscription") + 1] == context["subscription_id"]
    assert "--admin" not in commands[0]
    assert len(reads) == 1
    assert commands[1] == (
        "kubelogin",
        "convert-kubeconfig",
        "--kubeconfig",
        str(kubeconfig),
        "--login",
        "msi",
        "--client-id",
        context["client_id"],
    )


@pytest.mark.parametrize("failure", ["link", "public-file", "missing-client", "convert"])
def test_aks_kubeconfig_fails_closed(tmp_path, monkeypatch, failure):
    tmp_path.chmod(0o700)
    kubeconfig = tmp_path / "aks.kubeconfig"
    if failure == "link":
        kubeconfig.symlink_to(tmp_path / "missing")
    elif failure == "public-file":
        kubeconfig.write_text("unsafe config")
        kubeconfig.chmod(0o644)
    context = {
        "client_id": "" if failure == "missing-client" else "00000000-0000-0000-0000-000000000001",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
    }
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[0] == "kubelogin":
            raise ValueError("conversion failed")
        kubeconfig.write_text("generated")

    monkeypatch.setattr(standalone_host, "_run", run)
    with pytest.raises((ValueError, OSError)):
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )
    assert len(commands) == (2 if failure == "convert" else 0)


@pytest.mark.parametrize(
    "authentication", ["devicecode", "wrong-client", "duplicate", "secret", "multiple-users", "env"]
)
def test_aks_kubeconfig_readback_rejects_wrong_authentication(
    tmp_path, monkeypatch, authentication
):
    tmp_path.chmod(0o700)
    client = "00000000-0000-0000-0000-000000000001"
    context = {"client_id": client, "subscription_id": "00000000-0000-0000-0000-000000000002"}
    user = {
        "exec": {
            "command": "kubelogin",
            "args": ["get-token", "--login", "msi", "--client-id", client],
        }
    }
    if authentication == "devicecode":
        user["exec"]["args"][2] = "devicecode"
    elif authentication == "wrong-client":
        user["exec"]["args"][-1] = "unselected-client"
    elif authentication == "duplicate":
        user["exec"]["args"].extend(["--login", "devicecode"])
    elif authentication == "secret":
        user["token"] = "synthetic-test-token"
    elif authentication == "env":
        user["exec"]["env"] = [{"name": "AZURE_CLIENT_ID", "value": "other"}]
    users = [{"user": user}] * (2 if authentication == "multiple-users" else 1)
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda *_args, **_kwargs: (tmp_path / "aks.kubeconfig").write_text("config"),
    )
    monkeypatch.setattr(
        standalone_host, "_capture", lambda *_args, **_kwargs: json.dumps({"users": users})
    )
    with pytest.raises(ValueError, match="AKS authentication"):
        standalone_host._prepare_aks_kubeconfig(
            context, tmp_path, resource_group="example-group", cluster_name="example-cluster"
        )


def test_aks_workload_binds_digest_image_and_additional_identity() -> None:
    digest = "a" * 64
    workload = standalone_host._aks_workload(
        "operator",
        {"operator-service": f"example.azurecr.io/operator-service@sha256:{digest}"},
        {"resource_id": "/identities/operator", "client_id": "operator-client"},
        {"RUNTIME_ENV": "dev"},
        {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
        "/healthz",
        "/healthz",
        external=True,
        additional_identities={
            "command": {
                "resource_id": "/identities/command",
                "client_id": "command-client",
            }
        },
    )

    assert workload["image"] == (f"example.azurecr.io/operator-service@sha256:{digest}")
    assert workload["external"] is True
    assert workload["environment"]["FDAI_DATABASE_ROLE"] == "fdai_operator"
    assert workload["environment"]["PGOPTIONS"] == "-c role=fdai_operator"
    assert workload["environment"]["FDAI_EXECUTION_VENUE"] == "deployed"
    assert workload["additional_identities"] == {
        "command": {
            "resource_id": "/identities/command",
            "client_id": "command-client",
        }
    }


def test_aks_core_conversation_environment_binds_topics_and_enabled_model() -> None:
    digest = "a" * 64
    environment = standalone_host._aks_core_conversation_environment(
        application_values={"enable_llm": True},
        substrate_outputs={
            "semantic_physical": "fdai.pantheon.objects",
            "llm_endpoint": "https://example.openai.azure.com/",
            "llm_model_endpoints": {"azure-openai:example": "https://example.openai.azure.com/"},
            "resolved_models_sha256": digest,
        },
        semantic_topics=[
            "operator.semantic-turn.requests",
            "core.semantic-turn.projections",
            "operator.read-investigation.requests",
        ],
    )

    assert environment == {
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
        "LLM_MODE": "azure",
        "LLM_RESOLVED_MODELS_PATH": "/app/resolved-models.json",
        "LLM_RESOLVED_MODELS_SHA256": digest,
        "FDAI_LLM_ENDPOINT": "https://example.openai.azure.com/",
        "FDAI_MODEL_ENDPOINTS_JSON": (
            '{"azure-openai:example":"https://example.openai.azure.com/"}'
        ),
    }


def test_aks_core_conversation_environment_keeps_transport_when_model_is_disabled() -> None:
    environment = standalone_host._aks_core_conversation_environment(
        application_values={"enable_llm": False},
        substrate_outputs={"semantic_physical": "fdai.pantheon.objects"},
        semantic_topics=["requests", "projections", "investigations"],
    )

    assert environment == {
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "projections",
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "investigations",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
    }


@pytest.mark.parametrize("enable_llm", [None, "true", 1])
def test_aks_core_conversation_environment_rejects_non_boolean_model_activation(
    enable_llm: object,
) -> None:
    with pytest.raises(TypeError, match="enable_llm setting MUST be a boolean"):
        standalone_host._aks_core_conversation_environment(
            application_values={"enable_llm": enable_llm},
            substrate_outputs={"semantic_physical": "physical"},
            semantic_topics=["requests", "projections", "investigations"],
        )


@pytest.mark.parametrize(
    ("substrate_update", "message"),
    [
        ({"llm_endpoint": ""}, "LLM endpoint"),
        ({"llm_model_endpoints": {}}, "model endpoint outputs"),
        ({"resolved_models_sha256": "invalid"}, "lowercase SHA-256"),
    ],
)
def test_aks_core_conversation_environment_rejects_incomplete_enabled_model(
    substrate_update: dict[str, object], message: str
) -> None:
    substrate_outputs: dict[str, object] = {
        "semantic_physical": "physical",
        "llm_endpoint": "https://example.openai.azure.com/",
        "llm_model_endpoints": {"azure-openai:example": "https://example.openai.azure.com/"},
        "resolved_models_sha256": "a" * 64,
        **substrate_update,
    }

    with pytest.raises(ValueError, match=message):
        standalone_host._aks_core_conversation_environment(
            application_values={"enable_llm": True},
            substrate_outputs=substrate_outputs,
            semantic_topics=["requests", "projections", "investigations"],
        )


def test_prepare_aks_application_requires_core_semantic_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("runtime-receipt.json", "image-import-receipt.json", "migration-receipt.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
        },
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "runtime"),
        "tenant_id": "tenant",
        "subscription_id": "subscription",
    }
    application = {"enable_llm": True, "region": "westus2", "env": "dev"}
    identities = {
        name: {"resource_id": f"/identities/{name}", "client_id": f"{name}-client"}
        for name in (
            "core",
            "operator",
            "command",
            "executor",
            "inventory",
            "canary",
            "ingestion",
            "ingestion_worker",
        )
    }
    semantic_topics = ["requests", "projections", "investigations"]

    def private_json(path: Path, _label: str) -> dict[str, object]:
        return context if path.name == "context.json" else application

    def json_output(_infra: Path, name: str) -> object:
        return {
            "runtime_identity_bindings": identities,
            "event_bus_topics": ["events"],
            "event_bus_semantic_topics": semantic_topics,
            "llm_model_endpoints": {"model": "endpoint"},
        }.get(name, {})

    def require_semantic_environment(**kwargs: object) -> dict[str, str]:
        assert kwargs["application_values"] == application
        assert kwargs["semantic_topics"] == semantic_topics
        outputs = kwargs["substrate_outputs"]
        assert isinstance(outputs, dict)
        assert outputs["semantic_physical"] == "event_bus_semantic_physical_topic"
        assert outputs["llm_endpoint"] == "llm_endpoint"
        assert outputs["llm_model_endpoints"] == {"model": "endpoint"}
        assert outputs["resolved_models_sha256"] == "resolved_models_sha256"
        raise RuntimeError("core semantic environment required")

    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_terraform_output",
        lambda _infra, name: (
            "console.azurestaticapps.net" if name == "console_default_hostname" else name
        ),
    )
    monkeypatch.setattr(standalone_host, "_terraform_json_output", json_output)
    monkeypatch.setattr(
        standalone_host,
        "_subnet_network_security_group",
        lambda *_args, **_kwargs: "/networkSecurityGroups/aks",
    )
    monkeypatch.setattr(
        standalone_host,
        "_prepare_aks_kubeconfig",
        lambda *_args, **_kwargs: tmp_path / "aks.kubeconfig",
    )
    monkeypatch.setattr(
        standalone_host,
        "_subnet_network_security_group",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        standalone_host,
        "_aks_core_conversation_environment",
        require_semantic_environment,
    )

    with pytest.raises(RuntimeError, match="core semantic environment required"):
        standalone_host._prepare_aks_application(SimpleNamespace(), tmp_path)


def test_aks_document_workloads_bind_complete_service_contracts() -> None:
    digest = "a" * 64
    refs = {
        name: f"example.azurecr.io/{name}@sha256:{digest}"
        for name in ("document-ingestion-api", "document-processing-worker", "clamav")
    }
    application = {
        "env": "dev",
        "tenant_id": "tenant",
        "operator_api_audience": "audience",
        "rbac_readers_group_id": "readers",
        "rbac_contributors_group_id": "contributors",
        "rbac_approvers_group_id": "approvers",
        "rbac_owners_group_id": "owners",
        "rbac_break_glass_group_id": "break-glass",
        "ingestion_cors_allow_origins": "https://localhost",
    }
    workloads = standalone_host._aks_document_workloads(
        refs=refs,
        ingestion_identity={"resource_id": "/identities/api", "client_id": "api-client"},
        worker_identity={"resource_id": "/identities/worker", "client_id": "worker-client"},
        application_values=application,
        kafka="example.servicebus.windows.net:9093",
        postgres_fqdn="example.postgres.database.azure.com",
        document_store={
            "account_name": "documents",
            "account_url": "https://documents.dfs.core.windows.net/",
            "source_file_system": "documents",
            "derived_file_system": "derived",
        },
        document_topics={
            "pipeline_stages": "fdai.pipeline.stages",
            "pantheon_objects": "fdai.pantheon.objects",
        },
        console_origin="https://example.azurestaticapps.net",
    )

    assert set(workloads) == {"document-ingestion-api", "document-processing-worker"}
    api = workloads["document-ingestion-api"]
    worker = workloads["document-processing-worker"]
    assert api["environment"]["FDAI_DATABASE_ROLE"] == "fdai_ingestion_api"
    assert api["environment"]["FDAI_DOCUMENT_RETRIEVAL_MODE"] == "lexical"
    assert api["environment"]["FDAI_INGESTION_CORS_ALLOW_ORIGINS"] == (
        "https://example.azurestaticapps.net"
    )
    assert api["service_port"] == 80
    assert worker["environment"]["FDAI_DATABASE_ROLE"] == "fdai_ingestion_worker"
    assert worker["environment"]["FDAI_CLAMAV_HOST"] == "127.0.0.1"
    assert worker["fs_group"] == 101
    assert worker["sidecars"]["clamav"]["image"] == refs["clamav"]
    assert worker["sidecars"]["clamav"]["run_as_user"] == 100
    assert worker["sidecars"]["clamav"]["run_as_group"] == 101
    assert worker["sidecars"]["clamav"]["init"] == {
        "name": "clamav-database",
        "command": ["/bin/sh", "-c"],
        "args": ["cp -a /var/lib/clamav/. /target/"],
        "image_pull_policy": "IfNotPresent",
        "run_as_user": 100,
        "run_as_group": 101,
        "writable_path": "database",
        "mount_path": "/target",
    }
    assert worker["sidecars"]["clamav"]["writable_paths"]["database"] == {
        "mount_path": "/var/lib/clamav",
        "size_limit": "1Gi",
    }


@pytest.mark.parametrize(
    ("component", "service", "role"),
    [
        ("operator", "operator-service", "fdai_operator"),
        ("executor", "isolated-executor", "fdai_executor"),
        ("ingestion", "document-ingestion-api", "fdai_ingestion_api"),
        ("worker", "document-processing-worker", "fdai_ingestion_worker"),
    ],
)
def test_aks_workload_preserves_service_database_role(component, service, role) -> None:
    environment = {"RUNTIME_ENV": "dev", "FDAI_DATABASE_ROLE": "wrong-role", "PGOPTIONS": ""}
    workload = standalone_host._aks_workload(
        component,
        {service: f"example.com/{service}@sha256:{'a' * 64}"},
        {"resource_id": f"/identities/{component}", "client_id": f"{component}-client"},
        environment,
        {},
        "/ready",
        "/live",
    )

    assert workload["environment"]["FDAI_DATABASE_ROLE"] == role
    assert workload["environment"]["PGOPTIONS"] == f"-c role={role}"
    assert workload["environment"]["FDAI_EXECUTION_VENUE"] == "deployed"
    assert "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER" not in workload["environment"]
    assert environment == {
        "RUNTIME_ENV": "dev",
        "FDAI_DATABASE_ROLE": "wrong-role",
        "PGOPTIONS": "",
    }


@pytest.mark.parametrize(
    "missing_service",
    [
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        None,
    ],
)
def test_aks_application_readback_requires_complete_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_service: str | None
) -> None:
    kubeconfig = tmp_path / "aks.kubeconfig"
    kubeconfig.write_text("test configuration", encoding="utf-8")
    expected = {
        name: {"image": f"example.com/{name}@sha256:{'a' * 64}", "replicas": 2}
        for name in (
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
        )
        if name != missing_service
    }
    observations: list[str] = []
    health_checks: list[dict[str, object]] = []

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        observations.append(command[2])
        return "observed-json"

    def verify_health(**kwargs: object) -> bool:
        health_checks.append(kwargs)
        return True

    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(standalone_host, "verify_workload_health", verify_health)
    context = {
        "runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"},
        "kubeconfig": str(kubeconfig),
        "expected_workloads": expected,
        "source_commit": "c" * 40,
    }

    assert standalone_host._readback_stage("application", context) is (missing_service is None)
    if missing_service is None:
        assert observations == ["deployments", "pods"]
        assert health_checks == [
            {
                "deployments": "observed-json",
                "pods": "observed-json",
                "expected": expected,
                "source_commit": "c" * 40,
            }
        ]
    else:
        assert observations == []
        assert health_checks == []


def test_aks_service_update_prepares_and_targets_only_selected_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    service_names = (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    )
    old_source = "a" * 40
    new_source = "b" * 40
    old_images = {
        name: f"example.com/fdai/{name}@sha256:{index:064x}"
        for index, name in enumerate(service_names, start=1)
    }
    new_image = f"example.com/fdai/core-control-plane@sha256:{'f' * 64}"
    workloads = {
        name: {
            "component": name,
            "image": image,
            "replicas": 2,
            "max_replicas": 3,
        }
        for name, image in old_images.items()
    }
    expected = {
        name: {"image": image, "replicas": 2, "max_replicas": 3}
        for name, image in old_images.items()
    }
    context = {
        "runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"},
        "runtime_profile_digest": "c" * 64,
        "target_binding": "d" * 64,
        "source_commit": old_source,
        "expected_workloads": expected,
        "workloads_infra": str(tmp_path),
        "workloads_terraform_data": str(tmp_path / "terraform-data-workloads"),
    }

    def write_private(name: str, value: object) -> None:
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)

    write_private("context.json", context)
    write_private("workloads.auto.tfvars.json", {"workloads": workloads})
    write_private("application-receipt.json", {"state": "applied"})
    for prerequisite in (
        "substrate-receipt.json",
        "image-import-receipt.json",
        "migration-receipt.json",
        "runtime-receipt.json",
    ):
        write_private(prerequisite, {"state": "applied"})
    deployment_items = [
        {
            "metadata": {"name": name, "uid": f"uid-{name}", "generation": 1},
            "spec": {
                "template": {
                    "metadata": {"labels": {"fdai.io/source-commit": old_source}},
                    "spec": {"containers": [{"name": name, "image": old_images[name]}]},
                }
            },
        }
        for name in service_names
    ]
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_capture_aks_deployments",
        lambda _context: json.dumps({"kind": "DeploymentList", "items": deployment_items}),
    )

    prepared = standalone_host._prepare_aks_service_update(
        SimpleNamespace(service="core-control-plane", image=new_image, source_commit=new_source),
        tmp_path,
    )

    values = json.loads((tmp_path / "workloads.auto.tfvars.json").read_text(encoding="utf-8"))
    assert values["workloads"]["core-control-plane"]["image"] == new_image
    assert values["workloads"]["core-control-plane"]["source_commit"] == new_source
    assert all(
        values["workloads"][name]["image"] == old_images[name]
        and values["workloads"][name]["source_commit"] == old_source
        for name in service_names
        if name != "core-control-plane"
    )
    plan_commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...] | list[str], **_kwargs: object) -> None:
        normalized = tuple(command)
        plan_commands.append(normalized)
        output = next(value for value in normalized if value.startswith("-out="))
        plan_path = Path(output.removeprefix("-out="))
        plan_path.write_bytes(b"plan")
        plan_path.chmod(0o600)

    monkeypatch.setattr(standalone_host, "_run", run)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda *_args, **_kwargs: json.dumps(
            {
                "resource_changes": [
                    {
                        "address": ('kubernetes_deployment_v1.workload["core-control-plane"]'),
                        "type": "kubernetes_deployment_v1",
                        "change": {"actions": ["update"]},
                    }
                ]
            }
        ),
    )

    review = standalone_host._plan(
        SimpleNamespace(stage="application", service="core-control-plane"), tmp_path
    )

    assert review["service_update"] == {
        "service": "core-control-plane",
        "image": new_image,
        "source_commit": new_source,
        "update_digest": prepared["update_digest"],
    }
    assert '-target=kubernetes_deployment_v1.workload["core-control-plane"]' in plan_commands[0]


def test_aks_deployment_capture_uses_typed_apps_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("synthetic kubeconfig", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def capture(command: tuple[str, ...], **kwargs: object) -> str:
        calls.append((command, kwargs))
        return '{"kind":"DeploymentList","items":[]}'

    monkeypatch.setattr(standalone_host, "_capture", capture)
    context = {"kubeconfig": str(kubeconfig)}

    assert json.loads(standalone_host._capture_aks_deployments(context))["kind"] == (
        "DeploymentList"
    )
    standalone_host._capture_aks_deployments(context, service="operator-service")

    common_tail = (
        "--request-timeout=60s",
        f"--kubeconfig={kubeconfig}",
    )
    assert calls == [
        (
            (
                "kubectl",
                "get",
                "--raw=/apis/apps/v1/namespaces/fdai-runtime/deployments",
                *common_tail,
            ),
            {
                "cwd": tmp_path,
                "timeout": 90,
                "reason": "AKS Deployment observation failed",
            },
        ),
        (
            (
                "kubectl",
                "get",
                (
                    "--raw=/apis/apps/v1/namespaces/fdai-runtime/deployments?"
                    "labelSelector=app.kubernetes.io%2Fname%3Doperator-service"
                ),
                *common_tail,
            ),
            {
                "cwd": tmp_path,
                "timeout": 90,
                "reason": "AKS Deployment observation failed",
            },
        ),
    ]


def test_historical_aks_baseline_requires_matching_state_live_and_bounded_plan() -> None:
    services = sorted(
        {
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
        }
    )
    source_commit = "a" * 40
    workloads = {
        name: {
            "image": f"example.azurecr.io/{name}@sha256:{index:064x}",
            "replicas": 2,
            "max_replicas": 3,
            "source_commit": source_commit,
        }
        for index, name in enumerate(services, start=1)
    }
    state = {
        "version": 4,
        "serial": 7,
        "lineage": "retained-lineage",
        "resources": [
            {
                "mode": "managed",
                "type": "kubernetes_deployment_v1",
                "name": "workload",
                "instances": [
                    {
                        "index_key": name,
                        "attributes": {
                            "metadata": [{"name": name}],
                            "spec": [
                                {
                                    "template": [
                                        {
                                            "metadata": [
                                                {"labels": {"fdai.io/source-commit": source_commit}}
                                            ],
                                            "spec": [
                                                {
                                                    "container": [
                                                        {
                                                            "name": name,
                                                            "image": workload["image"],
                                                        }
                                                    ]
                                                }
                                            ],
                                        }
                                    ]
                                }
                            ],
                        },
                    }
                    for name, workload in workloads.items()
                ],
            }
        ],
    }
    live = {
        "kind": "DeploymentList",
        "items": [
            {
                "metadata": {"name": name, "uid": f"uid-{name}", "generation": 1},
                "spec": {
                    "template": {
                        "metadata": {"labels": {"fdai.io/source-commit": source_commit}},
                        "spec": {"containers": [{"name": name, "image": workload["image"]}]},
                    }
                },
            }
            for name, workload in workloads.items()
        ],
    }
    historical_plan = {
        "applyable": True,
        "complete": False,
        "errored": False,
        "resource_changes": [
            {
                "address": f'kubernetes_deployment_v1.workload["{name}"]',
                "change": {"actions": ["update"] if name == "core-control-plane" else ["no-op"]},
            }
            for name in services
        ],
    }

    baseline = standalone_host._validate_historical_aks_baseline(
        state=state,
        variables={"namespace": "fdai-runtime", "workloads": workloads},
        live=live,
        plan=historical_plan,
    )

    assert baseline["expected_workloads"] == workloads
    assert baseline["state_lineage"] == "retained-lineage"
    assert baseline["historical_plan_service"] == "core-control-plane"
    operator_change = next(
        change
        for change in historical_plan["resource_changes"]
        if 'workload["operator-service"]' in change["address"]
    )
    operator_change["change"]["actions"] = ["update"]
    with pytest.raises(ValueError, match="mutation is invalid"):
        standalone_host._validate_historical_aks_baseline(
            state=state,
            variables={"namespace": "fdai-runtime", "workloads": workloads},
            live=live,
            plan=historical_plan,
        )
    operator_change["change"]["actions"] = ["no-op"]
    live["items"][0]["spec"]["template"]["spec"]["containers"][0]["image"] = (
        "example.azurecr.io/changed@sha256:" + "f" * 64
    )
    with pytest.raises(ValueError, match="live baseline differs"):
        standalone_host._validate_historical_aks_baseline(
            state=state,
            variables={"namespace": "fdai-runtime", "workloads": workloads},
            live=live,
            plan=historical_plan,
        )


def _historical_adoption_inputs(tmp_path: Path) -> tuple[Path, SimpleNamespace, dict[str, object]]:
    work_dir = tmp_path / "application"
    work_dir.mkdir(mode=0o700)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    for directory in (
        "repository",
        "azure-terraform",
        "terraform-data",
        "tools",
        "workloads",
    ):
        (evidence / directory).mkdir(mode=0o700)
    terraform = evidence / "tools/terraform"
    terraform.write_bytes(b"verified terraform")
    terraform.chmod(0o700)
    (evidence / "kubeconfig").write_text("verified kubeconfig", encoding="utf-8")
    (evidence / "kubeconfig").chmod(0o600)
    source_commit = "a" * 40
    binding = {
        "schema_version": "fdai.historical-aks-application-binding.v1",
        "source_commit": source_commit,
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "client_id": "00000000-0000-0000-0000-000000000003",
        "principal_id": "00000000-0000-0000-0000-000000000004",
        "runtime_profile": {
            "schema_version": "fdai.runtime-deployment-profile.v1",
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
            "system_node_count": 3,
            "system_node_sku": "Standard_D4as_v5",
            "user_node_min_count": 3,
            "user_node_max_count": 5,
            "user_node_sku": "Standard_D4as_v5",
        },
        "source_root": "repository",
        "terraform": "tools/terraform",
        "terraform_sha256": hashlib.sha256(terraform.read_bytes()).hexdigest(),
        "provider_mirror": "azure-terraform",
        "workloads_infra": "workloads",
        "terraform_data": "terraform-data",
        "kubeconfig": "kubeconfig",
        "kit_bin": "tools",
    }
    documents: dict[str, object] = {
        "binding": binding,
        "state": {"version": 4, "serial": 7, "lineage": "lineage", "resources": []},
        "variables": {"namespace": "fdai-runtime", "workloads": {}},
        "live": {"kind": "DeploymentList", "items": []},
        "plan": {"errored": False, "resource_changes": []},
    }
    paths: dict[str, Path] = {}
    for name, value in documents.items():
        path = evidence / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
        paths[name] = path
    args = SimpleNamespace(
        binding=paths["binding"],
        state=paths["state"],
        variables=paths["variables"],
        live=paths["live"],
        plan=paths["plan"],
    )
    baseline = {
        "expected_workloads": {
            "operator-service": {
                "image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
                "replicas": 2,
                "max_replicas": 3,
                "source_commit": source_commit,
            }
        },
        "state_lineage": "lineage",
        "state_serial": 7,
        "historical_plan_service": "core-control-plane",
    }
    return work_dir, args, baseline


def _current_aks_zero_change_plan() -> dict[str, object]:
    return {
        "complete": True,
        "errored": False,
        "resource_changes": [
            {
                "type": "kubernetes_deployment_v1",
                "address": f'kubernetes_deployment_v1.workload["{service}"]',
                "change": {"actions": ["no-op"]},
            }
            for service in sorted(standalone_host.AKS_SERVICES)
        ],
    }


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("remote", "remote state differs"),
        ("live", "live readback differs"),
        ("plan", "current plan is not zero-change"),
    ],
)
def test_historical_aks_adoption_fails_closed_on_current_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    work_dir, args, baseline = _historical_adoption_inputs(tmp_path)
    validation_calls = 0

    def validate(**_kwargs: object) -> dict[str, object]:
        nonlocal validation_calls
        validation_calls += 1
        if failure == "live" and validation_calls == 2:
            raise ValueError("historical AKS live readback differs")
        return baseline

    retained_state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    remote_state = dict(retained_state)
    if failure == "remote":
        remote_state["resources"] = [{"type": "unexpected"}]

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        if command[0] == "git":
            return "a" * 40 + "\n"
        if command[1:3] == ("state", "pull"):
            return json.dumps(remote_state)
        return json.dumps(_current_aks_zero_change_plan())

    monkeypatch.setattr(standalone_host, "_validate_historical_aks_baseline", validate)
    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(standalone_host, "_capture_aks_deployments", lambda *_: "{}")
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2 if failure == "plan" else 0),
    )

    with pytest.raises(ValueError, match=message):
        standalone_host._adopt_historical_aks_application(args, work_dir)
    assert not (work_dir / "historical-aks-application-adoption-receipt.json").exists()


def test_historical_aks_adoption_is_idempotent_and_rejects_tampered_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir, args, baseline = _historical_adoption_inputs(tmp_path)
    retained_state = Path(args.state).read_text(encoding="utf-8")

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        if command[0] == "git":
            return "a" * 40 + "\n"
        if command[1:3] == ("state", "pull"):
            return retained_state
        return json.dumps(_current_aks_zero_change_plan())

    monkeypatch.setattr(standalone_host, "_validate_historical_aks_baseline", lambda **_: baseline)
    monkeypatch.setattr(standalone_host, "_capture", capture)
    monkeypatch.setattr(standalone_host, "_capture_aks_deployments", lambda *_: "{}")
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    first = standalone_host._adopt_historical_aks_application(args, work_dir)
    second = standalone_host._adopt_historical_aks_application(args, work_dir)
    assert second == first
    context = json.loads((work_dir / "context.json").read_text(encoding="utf-8"))
    standalone_host._require_aks_application_baseline(work_dir, context)

    receipt_path = work_dir / "historical-aks-application-adoption-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["remote_state_verified"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    receipt_path.chmod(0o600)
    with pytest.raises(ValueError, match="historical AKS adoption receipt is invalid"):
        standalone_host._require_aks_application_baseline(work_dir, context)
    with pytest.raises(ValueError, match="retained historical AKS adoption receipt differs"):
        standalone_host._adopt_historical_aks_application(args, work_dir)


def test_source_service_image_import_uses_managed_identity_and_registry_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_oci_archive import COMMIT, make_archive

    tmp_path.chmod(0o700)
    archive = tmp_path / "operator-service.oci.tar"
    fixture = make_archive(archive)
    archive.chmod(0o600)
    context = {
        "registry_login_server": "example.azurecr.io",
        "registry_name": "example",
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "target_binding": "d" * 64,
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
        },
    }
    (tmp_path / "context.json").write_text(json.dumps(context), encoding="utf-8")
    (tmp_path / "context.json").chmod(0o600)
    (tmp_path / "substrate-receipt.json").write_text("{}", encoding="utf-8")
    (tmp_path / "substrate-receipt.json").chmod(0o600)
    (tmp_path / "application.auto.tfvars.json").write_text('{"env":"dev"}', encoding="utf-8")
    (tmp_path / "application.auto.tfvars.json").chmod(0o600)
    now = datetime.now(UTC).replace(microsecond=0)
    approval = {
        "schema_version": "fdai.source-service-image-import-approval.v1",
        "service": "operator-service",
        "source_commit": COMMIT,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "image_digest": fixture.manifest_digest,
        "target_binding": "d" * 64,
        "actor_digest": "e" * 64,
        "approved_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    approval["approval_digest"] = canonical_digest(approval)
    approval_path = tmp_path / "source-image-approval.json"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    approval_path.chmod(0o600)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_capture",
        lambda command, **_kwargs: (
            "registry-token" if command[:3] == ("az", "acr", "login") else fixture.manifest_digest
        ),
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        standalone_host,
        "_run",
        lambda command, **_kwargs: commands.append(tuple(command)),
    )
    monkeypatch.setattr(
        standalone_host.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    receipt = standalone_host._import_source_service_image(
        SimpleNamespace(
            service="operator-service",
            archive=archive,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            image_digest=fixture.manifest_digest,
            source_commit=COMMIT,
            approval=approval_path,
        ),
        tmp_path,
    )

    assert receipt["state"] == "imported"
    assert receipt["service"] == "operator-service"
    assert receipt["source_commit"] == COMMIT
    assert receipt["image"] == f"example.azurecr.io/operator-service@{fixture.manifest_digest}"
    assert receipt["effect_verified"] is True
    assert any(command[:2] == ("oras", "cp") for command in commands)
    assert (tmp_path / "source-image-import-operator-service-claim.json").is_file()
    assert (tmp_path / "source-image-import-operator-service-receipt.json").is_file()

    recovered = standalone_host._import_source_service_image(
        SimpleNamespace(
            service="operator-service",
            archive=archive,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            image_digest=fixture.manifest_digest,
            source_commit=COMMIT,
            approval=approval_path,
        ),
        tmp_path,
    )

    assert recovered["mutation_performed"] is True
    assert sum(command[:2] == ("oras", "cp") for command in commands) == 1


def test_source_image_import_approval_expiry_is_recovery_only() -> None:
    approved_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    approval = {
        "schema_version": "fdai.source-service-image-import-approval.v1",
        "service": "operator-service",
        "source_commit": "c" * 40,
        "archive_sha256": "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
        "target_binding": "d" * 64,
        "actor_digest": "e" * 64,
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (approved_at + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    approval["approval_digest"] = canonical_digest(approval)
    arguments = {
        "service": "operator-service",
        "source_commit": "c" * 40,
        "archive_digest": "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
        "target_binding": "d" * 64,
    }

    with pytest.raises(ValueError, match="expired"):
        standalone_host._validate_source_image_import_approval(approval, **arguments)
    assert (
        standalone_host._validate_source_image_import_approval(
            approval, **arguments, allow_expired=True
        )
        == approval["approval_digest"]
    )


def test_source_service_update_rejects_non_dev_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
        },
        "expected_workloads": {
            "operator-service": {
                "image": "example.azurecr.io/operator-service@sha256:" + "a" * 64,
                "source_commit": "b" * 40,
            }
        },
    }
    for name, value in (
        ("context.json", context),
        ("application.auto.tfvars.json", {"env": "production"}),
        ("application-receipt.json", {"state": "applied"}),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
    monkeypatch.setattr(
        standalone_host,
        "_managed_identity_login_from_context",
        lambda *_: pytest.fail("non-dev source update acquired deployment identity"),
    )

    with pytest.raises(ValueError, match="only for retained dev"):
        standalone_host._service_update_context(
            SimpleNamespace(service="operator-service"), tmp_path
        )


def test_database_plan_requires_cluster_and_image_receipts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="database plan prerequisites"):
        standalone_host._plan(SimpleNamespace(stage="database"), tmp_path)


def test_standalone_migration_uses_interpreter_for_private_bundle_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    infra = bundle / "infra"
    infra.mkdir(parents=True)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "substrate-receipt.json").write_text("{}", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def private_json(path: Path, _label: str) -> dict[str, object]:
        if path.name == "context.json":
            return {"infra": str(infra), "source_commit": "c" * 40}
        service_id = "core-control-plane"
        if path.name.endswith("-schema.json"):
            return {
                "schema_version": 1,
                "service_id": service_id,
                "observed_schema_fingerprint": "fingerprint",
            }
        return {
            "service_id": service_id,
            "observed_schema_fingerprint": "fingerprint",
        }

    def run_env(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> None:
        commands.append(command)
        if "--evidence-output" in command:
            evidence = Path(command[command.index("--evidence-output") + 1])
            schema = Path(command[command.index("--schema-output") + 1])
            evidence.write_text("{}", encoding="utf-8")
            schema.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_terraform_output", lambda *_: "unused")
    monkeypatch.setattr(standalone_host, "_vault_name", lambda *_: "vault")
    monkeypatch.setattr(standalone_host, "_capture", lambda *_args, **_kwargs: "dsn")
    monkeypatch.setattr(
        standalone_host,
        "_capture_env",
        lambda *_args, **_kwargs: "core-control-plane\n",
    )
    monkeypatch.setattr(standalone_host, "_run_env", run_env)
    monkeypatch.setattr(standalone_host, "_replace_private_json", lambda *_: None)

    result = standalone_host._migrate(SimpleNamespace(), work_dir)

    migration_commands = [command for command in commands if "--evidence-output" in command]
    assert migration_commands == [
        (
            "/bin/sh",
            str(bundle / "service-migrations/bin/core-control-plane"),
            "bootstrap",
            "--evidence-output",
            str(work_dir / "migration-evidence/core-control-plane.json"),
            "--schema-output",
            str(work_dir / "migration-evidence/core-control-plane-schema.json"),
            "--rollback-reference",
            "bundle:cccccccccccccccccccccccccccccccccccccccc:service-migrations/branches/core-control-plane/adoption.json#rollback",
        )
    ]
    assert result["state"] == "migrated"


def test_initial_inventory_runs_full_scope_with_private_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    infra = bundle / "infra"
    infra.mkdir(parents=True)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    for name in ("migration-receipt.json", "application-receipt.json"):
        (work_dir / name).write_text("{}", encoding="utf-8")
    context = {
        "infra": str(infra),
        "source_commit": "c" * 40,
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "client_id": "00000000-0000-0000-0000-000000000002",
        "inventory_progress_container_url": (
            "https://storage.blob.core.windows.net/provisioning-events"
        ),
    }
    observed_environment: dict[str, str] = {}

    monkeypatch.setattr(standalone_host, "_private_json", lambda *_: context)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_terraform_output", lambda *_: "unused")
    monkeypatch.setattr(standalone_host, "_vault_name", lambda *_: "vault")
    monkeypatch.setattr(standalone_host, "_capture", lambda *_args, **_kwargs: "dsn")
    monkeypatch.setattr(
        standalone_host,
        "_capture_env",
        lambda *_args, **_kwargs: json.dumps(
            {
                "observer_distinct": True,
                "active_generation_matches": True,
                "provider_coverage_complete": True,
                "receipt_digest": "sha256:" + "a" * 64,
            }
        ),
    )

    def run_env(_command: tuple[str, ...], **kwargs: object) -> None:
        observed_environment.update(kwargs["env"])  # type: ignore[arg-type]

    monkeypatch.setattr(standalone_host, "_run_env", run_env)
    monkeypatch.setattr(standalone_host, "_replace_private_json", lambda *_: None)

    result = standalone_host._initial_inventory(SimpleNamespace(), work_dir)

    assert observed_environment["FDAI_INVENTORY_SCOPES"] == context["subscription_id"]
    assert observed_environment["FDAI_INVENTORY_SOURCES"] == "arg,arm"
    assert observed_environment["FDAI_INVENTORY_PROGRESS_CONTAINER_URL"].startswith("https://")
    assert result["active_generation_readback_verified"] is True
    assert result["subscription_ready"] is False


def test_private_service_migration_launcher_runs_through_fixed_interpreter(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    launcher = tmp_path / "service-migrations/bin/core-control-plane"
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(repository / "service-migrations/bin/core-control-plane", launcher)
    launcher.chmod(0o600)
    fake_python = tmp_path / "migration-python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\"\n",
        encoding="ascii",
    )
    fake_python.chmod(0o700)

    result = subprocess.run(
        ["/bin/sh", str(launcher), "bootstrap"],
        env={**os.environ, "FDAI_MIGRATION_PYTHON": str(fake_python)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("service-migrations/migrate.py core-control-plane bootstrap\n")
