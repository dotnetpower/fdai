from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import (
    license_issue,
    standalone_aks_inventory,
    standalone_application,
    standalone_console_publish,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.target import compute_target_binding


def test_standalone_application_reuses_foundation_host_key_alias() -> None:
    source = inspect.getsource(standalone_application.deploy_standalone_application)

    assert "module.stable_host_key_alias" in source
    assert "fdai-standalone-" not in source


def test_source_recovery_uses_recovered_private_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foundation = tmp_path / "foundation"
    foundation.mkdir()
    recovery = foundation / "foundation-recovery-attempt-5"
    recovery.mkdir()
    captured: dict[str, Path] = {}

    class ExpectedStop(Exception):
        pass

    def stop_after_path(path: Path, _label: str):
        captured["handoff"] = path
        raise ExpectedStop

    monkeypatch.setattr(standalone_application, "_private_json", stop_after_path)
    runtime = standalone_application.RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
    )
    with pytest.raises(ExpectedStop):
        standalone_application.deploy_standalone_application(
            kit=None,
            prepared=SimpleNamespace(root=foundation),
            foundation_status={"foundation_report": {}},
            entra_bindings=None,
            scripts=tmp_path,
            trial_token=None,
            timeout_seconds=60,
            runtime_profile=runtime,
            source_snapshot=tmp_path,
            source_snapshot_digest="a" * 64,
            source_root=tmp_path,
            foundation_recovery_directory=recovery,
        )

    assert captured["handoff"] == recovery / "recovery-private-handoff.json"


def test_focused_access_converges_before_substrate() -> None:
    source = inspect.getsource(standalone_application.deploy_standalone_application)

    assert source.index('host_preparation.get("focused_private_access")') < source.index(
        'begin_stage("substrate")'
    )
    assert 'stage="access"' in source


def test_runtime_cluster_phase_is_followed_by_runtime_association_review() -> None:
    source = inspect.getsource(standalone_application.deploy_standalone_application)

    assert "for runtime_phase in range(2)" in source
    assert 'runtime_receipt.get("operation") != "runtime-cluster"' in source
    assert "Planning Container Insights association after AKS cluster creation" in source


def test_recovered_state_rejects_destructive_plan_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        standalone_application, "validate_plan_review", lambda _review: ("substrate", 1)
    )

    with pytest.raises(ValueError, match="zero-destroy"):
        standalone_application._require_nondestructive_adoption_plan({})


def test_residual_recovery_review_skips_ordinary_replanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = {"residual_recovery": {"operation": "substrate-residual"}}
    monkeypatch.setattr(
        standalone_application,
        "_remote_json",
        lambda *_args, **_kwargs: pytest.fail("residual review must not request another plan"),
    )

    selected, command = standalone_application._plan_after_recovery(
        object(),
        "/remote",
        "/application",
        review,
        stage="substrate",
        timeout=60,
    )

    assert selected is review
    assert command == "apply-residual"


def test_residual_successor_review_uses_successor_apply() -> None:
    review = {"residual_successor": {"operation": "substrate-residual-successor"}}

    selected, command = standalone_application._plan_after_recovery(
        object(),
        "/remote",
        "/application",
        review,
        stage="substrate",
        timeout=60,
    )

    assert selected is review
    assert command == "apply-residual"


def test_remote_checkpoint_uses_recovery_host_program() -> None:
    commands: list[tuple[str, ...]] = []

    class Tunnel:
        host_program = "/remote/source-recovery-host.pyz"

        def ssh(self, command, **_kwargs):
            commands.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    result = standalone_application._remote_json(
        Tunnel(),
        "/remote",
        "/remote/application",
        ("recover-apply", "--stage", "substrate"),
        timeout=60,
    )

    assert result == {}
    assert commands[0][:3] == (
        "/remote/venv/bin/python",
        "/remote/source-recovery-host.pyz",
        "--work-dir",
    )


def test_missing_license_material_keeps_deployment_observation_only(monkeypatch) -> None:
    monkeypatch.setattr(license_issue, "discover_license_signing_key", lambda: None)

    token = standalone_application._license_token(
        trial_token=None,
        image_digest="a" * 64,
        deployment_binding="b" * 64,
        work_ref="deployment",
    )

    assert token is None


def test_container_apps_initial_inventory_contract_is_unchanged() -> None:
    standalone_aks_inventory.require_initial_inventory_receipt(
        {
            "state": "inventory-verified",
            "active_generation_readback_verified": True,
            "progress_persisted": True,
        },
        runtime_platform="container-apps",
    )


def test_aks_initial_inventory_requires_complete_generation_readback() -> None:
    receipt = {
        "state": "inventory-verified",
        "active_generation_readback_verified": True,
        "progress_persisted": True,
    }
    with pytest.raises(ValueError, match="initial inventory is incomplete"):
        standalone_aks_inventory.require_initial_inventory_receipt(receipt, runtime_platform="aks")

    complete: dict[str, object] = {
        **receipt,
        "complete_generation_readback_verified": True,
        "fresh_generation": True,
        "closure_receipt_verified": True,
        "sources": ["arg", "arm"],
        "scope_digest": "sha256:" + "a" * 64,
        "closure_receipt_digest": "sha256:" + "b" * 64,
        "inventory_binding_digest": "c" * 64,
        "freshness_observed_at": datetime.now(tz=UTC).isoformat(),
        "resource_count": 1,
        "link_count": 1,
        "unmapped_object_count": 0,
        "coverage_gap_count": 0,
    }
    complete["receipt_digest"] = canonical_digest(complete)
    standalone_aks_inventory.require_initial_inventory_receipt(
        complete,
        runtime_platform="aks",
    )


def test_approval_actor_is_bound_to_current_azure_target(monkeypatch) -> None:
    tenant = "00000000-0000-0000-0000-000000000000"
    subscription = "00000000-0000-0000-0000-000000000001"
    binding = compute_target_binding(tenant_id=tenant, subscription_id=subscription)
    payload = {
        "subscription_id": subscription,
        "tenant_id": tenant,
        "user_name": "operator@example.com",
        "user_type": "user",
    }
    monkeypatch.setattr(
        standalone_application.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    digest = standalone_application._azure_actor_digest(binding)

    assert len(digest) == 64


def test_approval_actor_rejects_changed_azure_target(monkeypatch) -> None:
    payload = {
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "user_name": "operator@example.com",
        "user_type": "user",
    }
    monkeypatch.setattr(
        standalone_application.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    with pytest.raises(ValueError, match="active Azure target"):
        standalone_application._azure_actor_digest("a" * 64)


def test_publish_verified_console_uses_verified_prebuilt_artifact(tmp_path, monkeypatch) -> None:
    materialized = tmp_path / "verified"
    bundle = tmp_path / "bundle"
    scripts = bundle / "scripts/deployment/azure"
    materialized.mkdir()
    scripts.mkdir(parents=True)
    archive = materialized / "runtime/console.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(b"verified-console")
    archive_digest = hashlib.sha256(b"verified-console").hexdigest()
    console_directory = tmp_path / "console-publish/dist"
    calls = []

    def extract(source, destination):
        calls.append(("extract", source, destination))
        console_directory.mkdir(parents=True)
        return console_directory

    def configure(directory, settings, *, manual_studio_url):
        assert directory.stat().st_mode & 0o777 == 0o700
        calls.append(("configure", directory, settings, manual_studio_url))
        return {"runtime_config_digest": "b" * 64}

    def run(command, **kwargs):
        calls.append(("run", command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(standalone_console_publish, "extract_bundle_archive", extract)
    monkeypatch.setattr(standalone_console_publish, "configure_console", configure)
    monkeypatch.setattr(standalone_console_publish.subprocess, "run", run)
    tenant_id = "00000000-0000-0000-0000-000000000001"
    subscription_id = "00000000-0000-0000-0000-000000000002"
    spa_client_id = "00000000-0000-0000-0000-000000000003"
    browser_console = {
        "console_hostname": "calm-field-012345678.3.azurestaticapps.net",
        "console_origin": "https://calm-field-012345678.3.azurestaticapps.net",
        "console_static_web_app_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-app/providers/"
            "Microsoft.Web/staticSites/swa-console"
        ),
        "operator_api_base_url": "https://apim-fdai.azure-api.net",
        "ingestion_api_base_url": "https://apim-fdai.azure-api.net/ingestion",
    }

    receipt = standalone_application.publish_verified_console(
        console_archive=archive,
        console_archive_sha256=archive_digest,
        bundle_root=bundle,
        prepared_root=tmp_path,
        entra_bindings={
            "ENTRA_CONSOLE_SPA_CLIENT_ID": spa_client_id,
            "ENTRA_CONSOLE_API_SCOPE": f"api://{spa_client_id}/access",
        },
        browser_console=browser_console,
        scripts=scripts,
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        timeout_seconds=900,
        redirect_changed=True,
    )

    settings = json.loads((tmp_path / "console-runtime-settings.json").read_text())
    assert settings == {
        "schema_version": "fdai.console-runtime.v1",
        "operator_api_base_url": browser_console["operator_api_base_url"],
        "ingestion_api_base_url": browser_console["ingestion_api_base_url"],
        "tenant_id": tenant_id,
        "spa_client_id": spa_client_id,
        "api_scope": f"api://{spa_client_id}/access",
    }
    assert calls[:2] == [
        ("extract", archive, tmp_path / "console-publish"),
        (
            "configure",
            console_directory,
            tmp_path / "console-runtime-settings.json",
            f"{browser_console['console_origin']}/manuals",
        ),
    ]
    command_call = calls[2]
    assert command_call[0] == "run"
    assert command_call[1] == (
        "/bin/bash",
        str(scripts / "publish-console.sh"),
        str(bundle / "infra/runtimes/aks/workloads"),
    )
    environment = command_call[2]["env"]
    assert environment["CONSOLE_PREBUILT_DIRECTORY"] == str(console_directory)
    assert environment["BROWSER_GATEWAY_OPERATOR_URL"] == browser_console["operator_api_base_url"]
    assert environment["ARM_SUBSCRIPTION_ID"] == subscription_id
    assert environment["FDAI_CONSOLE_VERIFY_ONLY"] == "0"
    assert receipt["state"] == "published"
    assert receipt["entra_redirect_verified"] is True
    assert len(str(receipt["receipt_digest"])) == 64
    assert (tmp_path / "console-publication-receipt.json").is_file()


def _publish_with_stubbed_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive: Path,
    archive_digest: str,
) -> dict[str, object]:
    published: dict[str, object] = {}

    def configure(directory, settings, *, manual_studio_url):
        return {"runtime_config_digest": "b" * 64}

    def run(command, **kwargs):
        directory = Path(kwargs["env"]["CONSOLE_PREBUILT_DIRECTORY"])
        published["index"] = (directory / "index.html").read_text()
        published["stale"] = (directory / "assets/stale.css").exists()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(standalone_console_publish, "configure_console", configure)
    monkeypatch.setattr(standalone_console_publish.subprocess, "run", run)
    subscription_id = "00000000-0000-0000-0000-000000000002"
    spa_client_id = "00000000-0000-0000-0000-000000000003"
    scripts = tmp_path / "bundle/scripts/deployment/azure"
    scripts.mkdir(parents=True, exist_ok=True)
    receipt = standalone_application.publish_verified_console(
        console_archive=archive,
        console_archive_sha256=archive_digest,
        bundle_root=tmp_path / "bundle",
        prepared_root=tmp_path,
        entra_bindings={
            "ENTRA_CONSOLE_SPA_CLIENT_ID": spa_client_id,
            "ENTRA_CONSOLE_API_SCOPE": f"api://{spa_client_id}/access",
        },
        browser_console={
            "console_hostname": "calm-field-012345678.3.azurestaticapps.net",
            "console_origin": "https://calm-field-012345678.3.azurestaticapps.net",
            "console_static_web_app_id": (
                f"/subscriptions/{subscription_id}/resourceGroups/rg-app/providers/"
                "Microsoft.Web/staticSites/swa-console"
            ),
            "operator_api_base_url": "https://apim-fdai.azure-api.net",
            "ingestion_api_base_url": "https://apim-fdai.azure-api.net/ingestion",
        },
        scripts=scripts,
        subscription_id=subscription_id,
        tenant_id="00000000-0000-0000-0000-000000000001",
        timeout_seconds=900,
        redirect_changed=False,
    )
    assert receipt["console_archive_sha256"] == archive_digest
    return published


def _console_archive(tmp_path: Path, index: str) -> tuple[Path, str]:
    source = tmp_path / "archive-source/dist"
    source.mkdir(parents=True)
    (source / "index.html").write_text(index)
    archive = tmp_path / "console.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(source, arcname="dist")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_publish_verified_console_replaces_a_retained_prior_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = tmp_path / "console-publish/dist/assets"
    retained.mkdir(parents=True)
    (retained.parent / "index.html").write_text("prior release")
    (retained / "stale.css").write_text("prior")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "index.html").write_text("untouched")
    (retained / "linked").symlink_to(elsewhere)
    archive, digest = _console_archive(tmp_path, "current release")

    published = _publish_with_stubbed_effects(tmp_path, monkeypatch, archive, digest)

    assert published == {"index": "current release", "stale": False}
    assert (elsewhere / "index.html").read_text() == "untouched"


@pytest.mark.parametrize("dangling", [False, True])
def test_publish_verified_console_rejects_a_substituted_extraction_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dangling: bool
) -> None:
    elsewhere = tmp_path / "elsewhere/dist"
    if not dangling:
        elsewhere.mkdir(parents=True)
        (elsewhere / "index.html").write_text("untouched")
    extraction = tmp_path / "console-publish"
    extraction.symlink_to(elsewhere.parent)
    archive, digest = _console_archive(tmp_path, "current release")

    with pytest.raises(ValueError, match="not a private directory"):
        _publish_with_stubbed_effects(tmp_path, monkeypatch, archive, digest)

    assert extraction.is_symlink()
    assert not (tmp_path / "console-runtime-settings.json").exists()
    assert not (tmp_path / "console-publication-receipt.json").exists()
    if not dangling:
        assert (elsewhere / "index.html").read_text() == "untouched"


def test_publish_verified_console_rejects_a_foreign_owned_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = tmp_path / "console-publish/dist"
    retained.mkdir(parents=True)
    (retained / "index.html").write_text("untouched")
    archive, digest = _console_archive(tmp_path, "current release")
    monkeypatch.setattr(standalone_console_publish.os, "getuid", lambda: retained.stat().st_uid + 1)

    with pytest.raises(ValueError, match="not a private directory"):
        _publish_with_stubbed_effects(tmp_path, monkeypatch, archive, digest)

    assert (retained / "index.html").read_text() == "untouched"
    assert not (tmp_path / "console-runtime-settings.json").exists()
    assert not (tmp_path / "console-publication-receipt.json").exists()


def test_publish_verified_console_rejects_a_non_directory_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction = tmp_path / "console-publish"
    extraction.write_text("untouched")
    archive, digest = _console_archive(tmp_path, "current release")

    with pytest.raises(ValueError, match="not a private directory"):
        _publish_with_stubbed_effects(tmp_path, monkeypatch, archive, digest)

    assert extraction.read_text() == "untouched"
    assert not (tmp_path / "console-runtime-settings.json").exists()
    assert not (tmp_path / "console-publication-receipt.json").exists()


def test_publish_verified_console_rejects_unsigned_bytes_before_removing_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = tmp_path / "console-publish/dist"
    retained.mkdir(parents=True)
    (retained / "index.html").write_text("untouched")
    archive, _digest = _console_archive(tmp_path, "current release")

    with pytest.raises(ValueError, match="signed release"):
        _publish_with_stubbed_effects(tmp_path, monkeypatch, archive, "a" * 64)

    assert (retained / "index.html").read_text() == "untouched"
    assert not (tmp_path / "console-runtime-settings.json").exists()
    assert not (tmp_path / "console-publication-receipt.json").exists()


def test_console_archive_digest_rejects_unsigned_bytes(tmp_path) -> None:
    archive = tmp_path / "console.tar.gz"
    archive.write_bytes(b"substituted")

    with pytest.raises(ValueError, match="signed release"):
        standalone_console_publish._require_archive_digest(archive, "a" * 64)
