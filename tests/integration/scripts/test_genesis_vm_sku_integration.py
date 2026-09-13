"""Automatic input binding and exact-plan rechecks without an Azure effect."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_foundation as foundation  # noqa: E402
import genesis_foundation_apply as foundation_apply  # noqa: E402
import genesis_prepare_inputs as prepare  # noqa: E402
import genesis_vm_sku_preflight as preflight  # noqa: E402
from fdai_deployment_cli import foundation_plan  # noqa: E402
from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_sku_selection import (  # noqa: E402
    recheck_image_vm_inputs,
    select_image_vm_inputs,
)
from genesis_runner_image_skus import selection_sizes  # noqa: E402
from tests.integration.scripts.test_genesis_foundation import (  # noqa: E402
    _inputs as foundation_inputs,
)
from tests.integration.scripts.test_genesis_foundation_apply import (  # noqa: E402
    _args,
    _mock_execution,
)
from tests.integration.scripts.test_genesis_runner_image import (  # noqa: E402
    _inputs,
    _plan_projection,
)
from tests.integration.scripts.test_genesis_vm_sku_choice import (  # noqa: E402
    POLICY,
    restrict,
    rows,
    usages,
)


@pytest.fixture
def isolated_environment(tmp_path, monkeypatch):
    config = tmp_path / "azure-config"
    config.mkdir(mode=0o700)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(config))
    return config


def capture_for(catalog, quota=None, *, image_disk=64):
    calls = []

    def capture(command, **kwargs):
        assert command[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        assert kwargs["timeout"] <= 30
        url = command[command.index("--url") + 1]
        calls.append(url)
        if "/usages?" in url:
            return json.dumps({"value": usages() if quota is None else quota})
        if "/images/" in url:
            return json.dumps(
                {
                    "id": url.split("management.azure.com", 1)[1].split("?", 1)[0],
                    "location": catalog[0]["locations"][0],
                    "provisioningState": "Succeeded",
                    "osState": "Generalized",
                    "diskSizeGB": image_disk,
                    "hyperVGeneration": "V2",
                    "osType": "Linux",
                }
            )
        query = command[command.index("--query") + 1]
        selected = catalog
        if "name ==" in query:
            selected = [row for row in catalog if f"'{row['name']}'" in query]
        return json.dumps({"value": selected})

    return capture, calls


def test_new_preparation_selects_host_and_preserves_private_replay(tmp_path, isolated_environment):
    capture, calls = capture_for(rows())
    size = preflight.discover_foundation_vm_size(
        repository_root=ROOT,
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="eastus",
        evidence_directory=tmp_path,
        source_commit="a" * 40,
        target_binding="b" * 64,
        capture=capture,
    )
    assert size == "Standard_D4ds_v4"
    assert len(calls) == 2
    folder = next(tmp_path.glob("vm-discovery-*"))
    result = json.loads((folder / "result.json").read_bytes())
    assert result["runner_vm_size"] == size
    assert result["build_vm_size"] == result["verify_vm_size"] == "Standard_D2ds_v4"
    assert result["capacity_reserved"] is False
    assert folder.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in folder.iterdir())


def test_all_restricted_saves_negative_counts_not_a_success(tmp_path, isolated_environment):
    catalog = rows()
    for item in catalog:
        restrict(item)
    capture, _ = capture_for(catalog)
    with pytest.raises(CheckError, match="restricted_in_selected_region"):
        preflight.discover_foundation_vm_size(
            repository_root=ROOT,
            subscription_id="00000000-0000-0000-0000-000000000001",
            region="eastus",
            evidence_directory=tmp_path,
            source_commit="a" * 40,
            target_binding="b" * 64,
            capture=capture,
        )
    result = json.loads(next(tmp_path.glob("vm-discovery-*/result.json")).read_bytes())
    assert result["state"] == "blocked"
    assert result["catalog_count"] == result["restricted_count"] == 2
    assert result["mutation_performed"] is False


def test_ineligible_vms_stop_before_image_name_or_network_discovery(monkeypatch):
    def unavailable(**_kwargs):
        raise CheckError("deployment_vm_skus_restricted_in_selected_region", 3)

    def forbidden(*_args, **_kwargs):
        pytest.fail("No downstream discovery should start without compatible VMs")

    monkeypatch.setattr(prepare, "discover_foundation_vm_size", unavailable)
    monkeypatch.setattr(prepare, "_capture", forbidden)
    monkeypatch.setattr(prepare, "network_layout", forbidden)
    monkeypatch.setattr(prepare, "state_account_name", forbidden)
    with pytest.raises(ValueError, match="restricted"):
        prepare.foundation_values(
            repository_root=ROOT,
            source_commit="a" * 40,
            tenant_id="synthetic",
            subscription_id="synthetic",
            region="eastus",
            target_binding="b" * 64,
            run_binding="c" * 64,
            ssh_public_key="synthetic",
        )


def test_incomplete_hardware_snapshot_records_unknown_counts(tmp_path, isolated_environment):
    catalog = rows()
    catalog[0]["capabilities"] = []
    capture, _calls = capture_for(catalog)
    with pytest.raises(CheckError, match="evidence_incomplete"):
        preflight.discover_foundation_vm_size(
            repository_root=ROOT,
            subscription_id="00000000-0000-0000-0000-000000000001",
            region="eastus",
            evidence_directory=tmp_path,
            source_commit="a" * 40,
            target_binding="b" * 64,
            capture=capture,
        )
    result = json.loads(next(tmp_path.glob("vm-discovery-*/result.json")).read_bytes())
    assert result["state"] == "blocked"
    assert result["restricted_count"] is None
    assert result["role_candidate_counts"] is None


def selected_image(tmp_path):
    inputs, destination = _inputs(tmp_path)
    inputs = replace(inputs, foundation_vm_size="Standard_D4ds_v4")
    terraform_root = tmp_path / "root"
    terraform_root.mkdir(mode=0o700)
    path = terraform_root / preflight.POLICY_NAME
    path.write_bytes(POLICY.read_bytes())
    path.chmod(0o600)
    catalog = rows(inputs.region)
    capture, calls = capture_for(catalog)
    selected = select_image_vm_inputs(
        inputs,
        terraform_root=terraform_root,
        destination=destination,
        azure_cli=Path("/usr/bin/az"),
        capture=capture,
        cwd=ROOT,
        environment={},
    )
    return inputs, selected, destination, terraform_root, catalog, calls


def test_image_review_v2_seals_the_discovered_pair_and_prepared_host(tmp_path):
    inputs, selected, destination, _root, _catalog, calls = selected_image(tmp_path)
    assert len(calls) == 2
    assert selected.sku_selection["schema_version"] == "fdai.runner-image-sku-selection.v2"
    assert selection_sizes(selected.sku_selection) == ("Standard_D2ds_v4", "Standard_D2ds_v4")
    assert selected.sku_selection["foundation_vm_size"] == "Standard_D4ds_v4"
    assert selected.sku_selection["image_disk_gib"] == 64
    assert selected.toolchain_digest == inputs.toolchain_digest
    assert json.loads(destination.read_bytes()) == selected.terraform_values
    assert "foundation_vm_size" not in selected.terraform_values


@pytest.mark.parametrize("fault", [None, "host_quota", "host_restricted", "changed_plan"])
def test_apply_rechecks_triplet_without_reselection(tmp_path, monkeypatch, fault):
    inputs, selected, _path, root, catalog, _calls = selected_image(tmp_path)
    quota = usages(limit=7 if fault == "host_quota" else 8)
    if fault == "host_restricted":
        restrict(catalog[1])
    projection = _plan_projection(selected.terraform_values)
    if fault == "changed_plan":
        for item in projection["resource_changes"]:
            if item["address"] == "azurerm_linux_virtual_machine.builder":
                item["change"]["after"]["size"] = "Standard_D2ds_v5"
    capture, calls = capture_for(catalog, quota)
    import genesis_vm_sku_image

    monkeypatch.setattr(
        genesis_vm_sku_image,
        "choose_deployment_vms",
        lambda *_a, **_k: pytest.fail("No reranking at apply"),
    )
    kwargs = {
        "selection": selected.sku_selection,
        "terraform_root": root,
        "subscription_id": inputs.terraform_values["subscription_id"],
        "region": inputs.region,
        "azure_cli": Path("/usr/bin/az"),
        "capture": capture,
        "cwd": ROOT,
        "environment": {},
    }
    if fault is None:
        recheck_image_vm_inputs(json.dumps(projection).encode(), **kwargs)
        assert len(calls) == 2
    else:
        with pytest.raises(CheckError):
            recheck_image_vm_inputs(json.dumps(projection).encode(), **kwargs)


@pytest.mark.parametrize("disk", [None, 64, 256])
def test_host_preflight_reads_actual_image_disk(tmp_path, isolated_environment, disk):
    inputs, _destination = _inputs(tmp_path)
    path = tmp_path / "foundation.json"
    values = json.loads(path.read_bytes())
    values["runner_vm_size"] = "Standard_D4ds_v4"
    path.write_text(json.dumps(values))
    capture, calls = capture_for(rows(inputs.region), image_disk=disk)
    kwargs = {
        "repository_root": ROOT,
        "variables_file": path,
        "evidence_directory": tmp_path,
        "capture": capture,
    }
    if disk == 64:
        preflight.recheck_foundation_vm(**kwargs)
        assert next(tmp_path.glob("host-sku-check-*/evidence.json")).exists()
    else:
        with pytest.raises(CheckError):
            preflight.recheck_foundation_vm(**kwargs)
    assert len(calls) == 3


def test_host_restriction_blocks_before_foundation_plan(tmp_path, monkeypatch):
    def blocked(**_kwargs):
        raise CheckError("deployment_vm_no_compatible_hardware", 3)

    monkeypatch.setattr(foundation, "recheck_foundation_vm", blocked)
    with pytest.raises(foundation.FoundationPlanError, match="no_compatible_hardware"):
        foundation.prepare_foundation_plan(
            inputs=foundation_inputs(tmp_path),
            repository_root=ROOT,
            orchestration_work_dir=tmp_path,
            attempt=1,
            prior_report=None,
            timeout=900,
            capture=lambda *_a, **_k: pytest.fail("No Terraform plan on incompatible host"),
        )


def test_host_restriction_blocks_before_new_claim_or_apply(tmp_path, monkeypatch):
    plan, calls = _mock_execution(tmp_path, monkeypatch)

    def blocked(**_kwargs):
        raise CheckError("deployment_vm_no_compatible_hardware", 3)

    monkeypatch.setattr(foundation_apply, "recheck_foundation_vm", blocked)
    with pytest.raises(CheckError, match="no_compatible_hardware"):
        foundation_apply._execute(
            foundation_apply._parser().parse_args(_args(tmp_path, "--approve"))
        )
    assert calls == ["init"]
    assert not (plan / foundation_apply.CLAIM_NAME).exists()
    assert not (plan / foundation_apply.RECEIPT_NAME).exists()


@pytest.mark.parametrize("late_read", ["host", "identity"])
def test_foundation_expiry_is_rechecked_after_preclaim_reads(tmp_path, monkeypatch, late_read):
    plan, calls = _mock_execution(tmp_path, monkeypatch)
    now = datetime(2026, 9, 10, tzinfo=UTC)
    timestamps = {
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    def verify(**kwargs):
        foundation_plan._validate_review_time(
            timestamps, require_unexpired=kwargs["require_unexpired"]
        )
        return {"plan_digest": "b" * 64, "integrity_verified": True}

    original_claim = foundation_apply._claim

    def delayed_read(**kwargs):
        nonlocal now
        now += timedelta(hours=1)
        return original_claim(**kwargs) if late_read == "identity" else None

    monkeypatch.setattr(foundation_plan, "datetime", Clock)
    monkeypatch.setattr(foundation_apply, "verify_foundation_plan", verify)
    monkeypatch.setattr(
        foundation_apply,
        "recheck_foundation_vm" if late_read == "host" else "_claim",
        delayed_read,
    )
    with pytest.raises(ValueError, match="expired"):
        foundation_apply._execute(
            foundation_apply._parser().parse_args(_args(tmp_path, "--approve"))
        )
    assert calls == ["init"]
    assert not (plan / foundation_apply.CLAIM_NAME).exists()
    assert not (plan / foundation_apply.RECEIPT_NAME).exists()


def test_existing_foundation_claim_never_reruns_sku_selection(tmp_path, monkeypatch):
    plan, calls = _mock_execution(tmp_path, monkeypatch)
    first = foundation_apply._parser().parse_args(_args(tmp_path, "--approve"))
    foundation_apply._execute(first)

    def forbidden(**_kwargs):
        pytest.fail("Existing claims must verify effects, not reselect or reserve VM quota")

    monkeypatch.setattr(foundation_apply, "recheck_foundation_vm", forbidden)
    resume = foundation_apply._parser().parse_args(_args(tmp_path, "--resume-verification"))
    foundation_apply._execute(resume)
    assert calls == ["init", "apply", "init"]
    assert (plan / foundation_apply.CLAIM_NAME).is_file()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("foundation_vm_size", "private\ncontrol"),
        ("foundation_vm_size", None),
        ("image_disk_gib", True),
        ("image_disk_gib", 128),
    ],
)
def test_v2_selection_cannot_change_host_or_image_contract(tmp_path, field, value):
    _inputs_value, selected, *_rest = selected_image(tmp_path)
    altered = {**selected.sku_selection, field: value}
    with pytest.raises(CheckError, match="plan_invalid"):
        selection_sizes(altered)
