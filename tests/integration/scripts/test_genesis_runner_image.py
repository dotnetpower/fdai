"""Exact local Genesis runner-image planning and apply regressions."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_runner_image as command  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_runner_image_contract import (  # noqa: E402
    CLAIM_NAME,
    PLAN_JSON_NAME,
    PLAN_NAME,
    RECEIPT_NAME,
    REVIEW_NAME,
    RunnerImageInputs,
    add_source_image_version,
    create_review,
    hash_tree,
    load_review,
    load_runner_image_inputs,
    materialize_foundation_image_input,
)

TENANT = "00000000-0000-0000-0000-000000000000"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
BINDING = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
SOURCE = "a" * 40


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
    return {
        "format_version": "1.2",
        "terraform_version": "1.9.8",
        "complete": True,
        "errored": False,
        "applyable": True,
        "variables": {key: {"value": value} for key, value in values.items()},
        "resource_changes": [
            {
                "address": "azurerm_resource_group.image",
                "change": {"actions": ["create"], "before": None, "after": {}},
            },
            {
                "address": "data.azapi_resource.runner_image",
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
    assert inputs.toolchain_digest == (
        "572345bb84e151841fe8506121f9d4e246046cdf39936309aac6acd1e10ab7c8"
    )
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
    )

    verified = load_review(work, expected_review_digest=str(review["review_digest"]))
    assert verified["plan_digest"] == review["plan_digest"]
    assert verified["create_count"] == 1
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
    (work / PLAN_NAME).write_bytes(b"exact-plan")
    (work / PLAN_NAME).chmod(0o600)
    _private_json(work / PLAN_JSON_NAME, _plan_projection(inputs.terraform_values))
    review = create_review(
        directory=work,
        inputs=inputs,
        root_digest=hash_tree(root),
        terraform_digest=command._file_digest(terraform),
    )
    profile = tmp_path / "apply-profile.json"
    _profile(profile)
    image_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
        "providers/Microsoft.Compute/images/runner"
    )
    calls: list[list[str]] = []

    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setattr(command.GenesisChecks, "verify_target", lambda *a, **kw: None)
    monkeypatch.setattr(command.GenesisChecks, "verify_source", lambda *a, **kw: None)
    monkeypatch.setattr(command, "_required", lambda cmd, **kw: calls.append(cmd))

    def capture(cmd: list[str], **_: object) -> str:
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return source_commit + "\n"
        if cmd[:3] == ["az", "account", "show"]:
            return '{"type":"user","name":"operator@example.com"}'
        if cmd[1:4] == ["output", "-json", "runner_image"]:
            return json.dumps(
                {
                    "id": image_id,
                    "location": "koreacentral",
                    "source_commit": source_commit,
                    "toolchain_digest": inputs.toolchain_digest,
                    "runner_registered": False,
                    "subscription_ready": False,
                }
            )
        if cmd[:3] == ["az", "resource", "show"]:
            return json.dumps(
                {
                    "id": image_id,
                    "type": "Microsoft.Compute/images",
                    "location": "koreacentral",
                    "provisioningState": "Succeeded",
                    "osType": "Linux",
                    "tags": {
                        "fdai:source-commit": source_commit,
                        "fdai:toolchain-digest": inputs.toolchain_digest,
                    },
                }
            )
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
    assert command.main(args) == 0
    assert len(calls) == 1


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
    _profile(profile)
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
        "toolchain_digest": "1" * 64,
        "runner_image_id": image_id,
        "state_ref": "root/terraform.tfstate",
        "effect_verified": True,
        "runner_registered": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
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
    _profile(profile)
    _private_json(source, _foundation_values())
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-image-apply-receipt.v1",
        "state": "applied",
        "review_digest": "e" * 64,
        "plan_digest": "f" * 64,
        "target_binding": "9" * 64,
        "source_commit": SOURCE,
        "toolchain_digest": "1" * 64,
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
    receipt["receipt_digest"] = canonical_digest(receipt)
    _private_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="does not match"):
        materialize_foundation_image_input(
            source=source,
            image_receipt=receipt_path,
            profile_path=profile,
            destination=destination,
        )

    assert not destination.exists()


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
