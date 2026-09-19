from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import cli
from fdai_deployment_cli.source_service_update import deploy_source_service_update


def test_source_service_update_builds_imports_plans_and_verifies(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir(mode=0o700)
    application = tmp_path / "application"
    application.mkdir(mode=0o700)
    work = tmp_path / "update"
    source = SimpleNamespace(
        root=source_root,
        commit="c" * 40,
        to_mapping=lambda: {
            "schema_version": "fdai.source-deployment-input.v1",
            "source_commit": "c" * 40,
        },
        reverify=lambda: None,
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.inspect_source", lambda *_: source
    )

    def materialize(_source, destination):
        destination.mkdir(mode=0o700)
        return "s" * 64

    monkeypatch.setattr("fdai_deployment_cli.source_service_update.materialize_source", materialize)
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._build_image",
        lambda **_: {
            "state": "built",
            "service": "operator-service",
            "source_commit": "c" * 40,
            "archive_ref": "operator-service.oci.tar",
            "archive_sha256": "a" * 64,
            "image_digest": "sha256:" + "b" * 64,
        },
    )
    calls: list[tuple[str, ...]] = []

    def host(_work_dir, arguments, **_kwargs):
        calls.append(arguments)
        command = arguments[0]
        if command == "adopt-historical-aks-application":
            return {
                "schema_version": "fdai.historical-aks-application-adoption.v1",
                "state": "adopted",
                "managed_identity_verified": True,
                "remote_state_verified": True,
                "live_baseline_verified": True,
                "terraform_zero_change_verified": True,
                "azure_resource_mutation_performed": False,
            }
        if command == "service-update-context":
            return {
                "schema_version": "fdai.source-service-update-context.v1",
                "state": "verified",
                "service": "operator-service",
                "target_binding": "d" * 64,
                "active_service_update": None,
            }
        if command == "import-source-image":
            return {
                "image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
                "receipt_digest": "e" * 64,
            }
        if command == "prepare-service-update":
            return {
                "service": "operator-service",
                "image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
                "source_commit": "c" * 40,
            }
        if command == "recover-apply":
            return {"state": "not-required"}
        if command == "plan":
            return {"review_digest": "f" * 64}
        assert command == "apply"
        return {
            "receipt_digest": "1" * 64,
            "control_plane_readback_verified": True,
            "peer_state_unchanged_verified": True,
            "terraform_zero_change_verified": True,
        }

    monkeypatch.setattr("fdai_deployment_cli.source_service_update._host_json", host)
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")
    approval.chmod(0o600)
    adoption = []
    for name in ("binding", "state", "variables", "live", "plan"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o600)
        adoption.append(path)

    result = deploy_source_service_update(
        source_root=source_root,
        application_work_dir=application,
        work_dir=work,
        service="operator-service",
        timeout_seconds=14400,
        adopt_historical_binding=adoption[0],
        adopt_historical_state=adoption[1],
        adopt_historical_variables=adoption[2],
        adopt_historical_live=adoption[3],
        adopt_historical_plan=adoption[4],
        approve_import=lambda *_: approval,
        approve_plan=lambda *_: approval,
    )

    assert result["state"] == "applied"
    assert result["effect_verified"] is True
    assert result["peer_state_unchanged_verified"] is True
    assert result["terraform_zero_change_verified"] is True
    assert [call[0] for call in calls] == [
        "adopt-historical-aks-application",
        "service-update-context",
        "import-source-image",
        "prepare-service-update",
        "recover-apply",
        "plan",
        "apply",
    ]


def test_source_service_update_cli_requires_source_service_and_application_state() -> None:
    parser = cli._parser()
    args = parser.parse_args(
        [
            "provision",
            "source-service-update",
            "--source",
            "/source",
            "--service",
            "operator-service",
            "--application-work-dir",
            "/state/application",
        ]
    )

    assert args.source == Path("/source")
    assert args.service == "operator-service"
    assert args.application_work_dir == Path("/state/application")
    assert args.handler is cli._provision_source_service_update


def test_source_service_update_requires_complete_historical_adoption_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SimpleNamespace(
        root=tmp_path / "source",
        commit="c" * 40,
        to_mapping=lambda: {},
        reverify=lambda: None,
    )
    source.root.mkdir(mode=0o700)
    application = tmp_path / "application"
    application.mkdir(mode=0o700)
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.inspect_source", lambda *_: source
    )

    with pytest.raises(ValueError, match="requires all five evidence inputs"):
        deploy_source_service_update(
            source_root=source.root,
            application_work_dir=application,
            work_dir=tmp_path / "update",
            service="operator-service",
            timeout_seconds=60,
            adopt_historical_binding=tmp_path / "binding.json",
        )
