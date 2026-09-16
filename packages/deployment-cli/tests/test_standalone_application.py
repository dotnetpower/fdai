from __future__ import annotations

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application
from fdai_deployment_cli.target import compute_target_binding


def test_recovered_state_rejects_destructive_plan_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        standalone_application, "validate_plan_review", lambda _review: ("substrate", 1)
    )

    with pytest.raises(ValueError, match="zero-destroy"):
        standalone_application._require_nondestructive_adoption_plan({})


def test_missing_license_material_keeps_deployment_observation_only(monkeypatch) -> None:
    monkeypatch.setattr(standalone_application, "discover_license_signing_key", lambda _key: None)

    token = standalone_application._license_token(
        key=None,
        trial_token=None,
        image_digest="a" * 64,
        deployment_binding="b" * 64,
        work_ref="deployment",
    )

    assert token is None


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


def test_publish_aks_console_uses_verified_prebuilt_artifact(tmp_path, monkeypatch) -> None:
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

    def configure(directory, settings):
        calls.append(("configure", directory, settings))
        return {"runtime_config_digest": "b" * 64}

    def run(command, **kwargs):
        calls.append(("run", command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(standalone_application, "extract_bundle_archive", extract)
    monkeypatch.setattr(standalone_application, "configure_console", configure)
    monkeypatch.setattr(standalone_application.subprocess, "run", run)
    kit = SimpleNamespace(
        materialized_root=materialized,
        bundle_root=bundle,
        runtime=SimpleNamespace(
            to_mapping=lambda: {
                "console": {
                    "archive": "runtime/console.tar.gz",
                    "archive_sha256": archive_digest,
                }
            }
        ),
    )
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

    receipt = standalone_application._publish_aks_console(
        kit=kit,
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
        ("configure", console_directory, tmp_path / "console-runtime-settings.json"),
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
    assert receipt["state"] == "published"
    assert receipt["entra_redirect_verified"] is True
    assert len(str(receipt["receipt_digest"])) == 64
    assert (tmp_path / "console-publication-receipt.json").is_file()


def test_console_archive_digest_rejects_unsigned_bytes(tmp_path) -> None:
    archive = tmp_path / "console.tar.gz"
    archive.write_bytes(b"substituted")

    with pytest.raises(ValueError, match="signed release"):
        standalone_application._require_archive_digest(archive, "a" * 64)
