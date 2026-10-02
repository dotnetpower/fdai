from __future__ import annotations

import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from rich.console import Console

from fdai_deployment_cli import standalone_application as application
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_progress import DeploymentProgress


@pytest.mark.parametrize(
    ("failure", "label"),
    [
        ("transfer", "Managed-host transfer"),
        ("substrate", "Private infrastructure"),
        ("images", "Runtime images"),
        ("capability", "Capability mode"),
        ("migration", "Database and catalogs"),
        ("application", "Application deployment"),
        ("initial-inventory", "Initial resource inventory"),
        ("catalog-review", "Frozen catalog review"),
        ("verification", "Health and zero-change plan"),
        ("cleanup", "Cleanup and final receipt"),
        (None, None),
    ],
)
def test_managed_host_failure_stays_on_current_phase(tmp_path, monkeypatch, failure, label) -> None:
    """No SSH, Azure, model, database, or Terraform command is executed."""

    calls = []
    persisted = []
    handoff = {
        "runner": {"ssh_key_digest": "d" * 64, "admin_username": "fdai", "vm_id": "example"},
        "access": {"bastion_name": "example"},
        "ops": {"resource_group_name": "example"},
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "region": "koreacentral",
    }

    class Tunnel:
        def __init__(self, **kwargs):
            assert kwargs["host_key_alias"] == "fdai-genesis-example"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append("closed")

        def ssh(self, command, **_kwargs):
            return subprocess.CompletedProcess(command, int(failure == "cleanup"), stdout="")

    module = SimpleNamespace(
        stable_host_key_alias=lambda _vm_id: "fdai-genesis-example",
        validate_known_hosts=lambda _path: None,
        validate_ssh_private_key=lambda _path: "d" * 64,
        BastionTunnel=Tunnel,
    )
    monkeypatch.setattr(application, "_import_bastion", lambda _path: module)
    monkeypatch.setattr(application, "_private_json", lambda *_args: handoff)
    monkeypatch.setattr(application, "archive_verified_kit", lambda *_args: "e" * 64)
    monkeypatch.setattr(
        application, "_replace_private_json", lambda path, _value: persisted.append(path.name)
    )

    def check(stage):
        calls.append(stage)
        if failure == stage:
            raise ValueError("synthetic checkpoint failure")

    def prepare_remote(*_args, **_kwargs):
        check("transfer")
        return {"focused_private_access": False}

    monkeypatch.setattr(application, "_prepare_remote", prepare_remote)
    monkeypatch.setattr(application, "_license_token", lambda **_kwargs: check("capability"))

    def remote(_tunnel, _root, _work, arguments, **_kwargs):
        if arguments[0] == "prune-transfers":
            return {
                "schema_version": "fdai.standalone-transfer-prune.v1",
                "removed": [],
                "preserved": [],
                "skipped": [],
                "free_bytes_before": 0,
                "free_bytes_after": 0,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        stage = {
            "deployment-binding": "binding",
            "import-images": "images",
            "migrate": "migration",
            "verify": "verification",
        }.get(arguments[0], arguments[-1])
        check(stage)
        if stage == "binding":
            return {
                "deployment_binding": "a" * 64,
                "installation_binding": "c" * 64,
                "terraform_name_verified": True,
            }
        if arguments[0] == "recover-apply":
            return {
                "state": "applied",
                "stage": stage,
                "control_plane_readback_verified": True,
                "receipt_digest": "a" * 64,
            }
        if stage == "images":
            return {
                "image_digests": {"core-control-plane": "sha256:" + "b" * 64},
                "receipt_digest": "a" * 64,
            }
        if stage == "migration":
            return {"state": "migrated", "catalogs_materialized": True, "receipt_digest": "a" * 64}
        if stage == "initial-inventory":
            return {
                "state": "inventory-verified",
                "active_generation_readback_verified": True,
                "progress_persisted": True,
                "receipt_digest": "a" * 64,
            }
        if stage == "catalog-review":
            receipt = {
                "schema_version": "fdai.standalone-catalog-review-receipt.v3",
                "state": "skipped",
                "selected": False,
                "reason": "not_selected",
                "source_revision": "c" * 40,
                "catalog_review_profile_digest": "d" * 64,
                "mutation_performed": False,
                "subscription_ready": False,
            }
            return {**receipt, "receipt_digest": canonical_digest(receipt)}
        assert stage == "verification"
        return {
            "terraform_zero_change_verified": True,
            "runtime_health_verified": True,
            "receipt_digest": "a" * 64,
        }

    monkeypatch.setattr(application, "_remote_json", remote)
    prepared = SimpleNamespace(
        root=tmp_path,
        ssh_private_key=tmp_path / "key-path-only",
        target_binding="b" * 64,
        source_commit="c" * 40,
        kit_manifest_digest="d" * 64,
    )
    output = io.StringIO()
    display = DeploymentProgress(mode="plain", console=Console(file=output), auto_refresh=False)

    def deploy():
        return application.deploy_standalone_application(
            kit=SimpleNamespace(),
            prepared=prepared,
            foundation_status={"foundation_report": {"foundation_plan": {"plan_ref": "plan"}}},
            entra_bindings={},
            scripts=tmp_path,
            trial_token=None,
            timeout_seconds=1800,
        )

    if failure is None:
        with display:
            result = deploy()
            assert result["deployment_ready"] is True
            display.ready()
        assert "standalone-application-receipt.json" in persisted
        assert "Deployment ready" in output.getvalue()
    else:
        with pytest.raises(ValueError), display:
            deploy()
        assert f"FAIL {label}" in output.getvalue()
        assert "Deployment ready" not in output.getvalue()
        assert "standalone-application-receipt.json" not in persisted
    assert calls[-1] == "closed"


@pytest.mark.parametrize("returncode,stdout", [(1, "private-output"), (0, "not-json"), (0, "[]")])
def test_remote_failure_never_renders_provider_payload(returncode, stdout) -> None:
    tunnel = SimpleNamespace(
        ssh=lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode, stdout=stdout)
    )
    with pytest.raises(ValueError) as error:
        application._remote_json(tunnel, "example", "example", ("verify",), timeout=10)
    assert "private-output" not in str(error.value)
    assert "not-json" not in str(error.value)


def test_remote_failure_surfaces_bounded_structured_summary() -> None:
    failure = {
        "schema_version": "fdai.standalone-host-failure.v1",
        "state": "failed",
        "reason_code": "terraform_provider_error",
        "provider_error_codes": ["OverconstrainedZonalAllocationRequest"],
        "message_excerpt": "OverconstrainedZonalAllocationRequest. Use a different VM size.",
        "mutation_performed": False,
        "subscription_ready": False,
    }
    tunnel = SimpleNamespace(
        ssh=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            3,
            stdout="",
            stderr="raw provider payload\n" + json.dumps(failure),
        )
    )

    with pytest.raises(ValueError) as error:
        application._remote_json(tunnel, "example", "example", ("verify",), timeout=10)

    message = str(error.value)
    assert "reason_code=terraform_provider_error" in message
    assert "OverconstrainedZonalAllocationRequest" in message
    assert "Use a different VM size" in message
    assert "raw provider payload" not in message
