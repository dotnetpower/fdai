from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import cli, source_service_update
from fdai_deployment_cli.source_service_update import deploy_source_service_update
from fdai_deployment_cli.contracts import canonical_digest


@pytest.fixture(autouse=True)
def _projection_facts(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.name == "test_legacy_full_snapshot_remains_eligible_for_recovery_timing":
        return
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._projection_facts",
        lambda _snapshot: ("fdai.source-snapshot.v2", 1, 1),
    )


def _built_image(work_dir: Path, service: str) -> dict[str, object]:
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = work_dir / f"{service}.oci.tar"
    archive.write_bytes(b"oci")
    return {
        "state": "built",
        "service": service,
        "source_commit": "c" * 40,
        "archive_ref": archive.name,
        "archive_sha256": "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
    }


def _imported_image(service: str) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.source-service-image-import-receipt.v1",
        "state": "imported",
        "service": service,
        "source_commit": "c" * 40,
        "archive_sha256": "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
        "image": f"example.azurecr.io/{service}@sha256:" + "b" * 64,
        "claim_digest": "d" * 64,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def test_legacy_full_snapshot_remains_eligible_for_recovery_timing(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    tree = snapshot / "tree"
    tree.mkdir(parents=True)
    snapshot.chmod(0o700)
    tree.chmod(0o700)
    (tree / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    manifest = snapshot / "source-input.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "fdai.source-snapshot.v1",
                "source": {},
                "files": [{"path": "source.py", "mode": "100644", "sha256": "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)

    assert source_service_update._projection_facts(snapshot) == (
        "fdai.source-snapshot.v1",
        1,
        10,
    )


def test_completed_service_update_receipt_is_reused_only_after_current_readback(
    tmp_path: Path,
) -> None:
    work = tmp_path / "update"
    work.mkdir()
    result: dict[str, object] = {
        "schema_version": "fdai.source-service-update.v1",
        "state": "applied",
        "service": "operator-service",
        "source_commit": "c" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "target_binding": "d" * 64,
        "image_import_receipt_digest": "e" * 64,
        "application_receipt_digest": "1" * 64,
        "effect_verified": True,
        "peer_state_unchanged_verified": True,
        "terraform_zero_change_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
        "finalization_receipt_digest": "2" * 64,
    }
    result["receipt_digest"] = canonical_digest(result)
    receipt = work / "source-service-update-receipt.json"
    receipt.write_text(json.dumps(result), encoding="utf-8")
    receipt.chmod(0o600)
    context = {
        "current_source_commit": "c" * 40,
        "current_image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
        "active_service_update": None,
    }

    assert (
        source_service_update._verified_completed_receipt(
            work,
            source_commit="c" * 40,
            service="operator-service",
            target_binding="d" * 64,
            context=context,
        )
        == result
    )

    context["current_source_commit"] = "a" * 40
    with pytest.raises(ValueError, match="not currently verified"):
        source_service_update._verified_completed_receipt(
            work,
            source_commit="c" * 40,
            service="operator-service",
            target_binding="d" * 64,
            context=context,
        )


def test_source_service_update_pins_the_expected_source_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    application = tmp_path / "application"
    source_root.mkdir(mode=0o700)
    application.mkdir(mode=0o700)
    observed: list[str | None] = []

    def inspect(_root: Path, *, expected_commit: str | None = None):
        observed.append(expected_commit)
        raise ValueError("stop after source admission")

    monkeypatch.setattr("fdai_deployment_cli.source_service_update.inspect_source", inspect)

    with pytest.raises(ValueError, match="stop after source admission"):
        deploy_source_service_update(
            source_root=source_root,
            application_work_dir=application,
            work_dir=tmp_path / "update",
            service="operator-service",
            timeout_seconds=60,
            expected_source_commit="c" * 40,
        )

    assert observed == ["c" * 40]


def test_source_service_update_rejects_a_changed_update_base_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    application = tmp_path / "application"
    source_root.mkdir(mode=0o700)
    application.mkdir(mode=0o700)
    source = SimpleNamespace(
        root=source_root,
        commit="c" * 40,
        to_mapping=lambda: {},
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.inspect_source", lambda *_args, **_kwargs: source
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._host_json",
        lambda *_args, **_kwargs: {
            "schema_version": "fdai.source-service-update-context.v1",
            "state": "verified",
            "service": "operator-service",
            "target_binding": "d" * 64,
            "current_source_commit": "a" * 40,
            "current_image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
            "active_service_update": None,
        },
    )

    with pytest.raises(ValueError, match="differs from the changed-update base"):
        deploy_source_service_update(
            source_root=source_root,
            application_work_dir=application,
            work_dir=tmp_path / "update",
            service="operator-service",
            timeout_seconds=60,
            expected_current_source_commit="b" * 40,
        )


def test_source_service_update_rejects_unbound_image_import_receipt() -> None:
    receipt: dict[str, object] = {
        "schema_version": "fdai.source-service-image-import-receipt.v1",
        "state": "imported",
        "service": "operator-service",
        "source_commit": "c" * 40,
        "archive_sha256": "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
        "image": "example.azurecr.io/operator-service@sha256:" + "b" * 64,
        "claim_digest": "d" * 64,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)

    source_service_update._validate_import_receipt(
        receipt,
        service="operator-service",
        source_commit="c" * 40,
        archive_sha256="a" * 64,
        image_digest="sha256:" + "b" * 64,
    )

    receipt["image"] = "example.azurecr.io/isolated-executor@sha256:" + "b" * 64
    with pytest.raises(ValueError, match="image import receipt is invalid"):
        source_service_update._validate_import_receipt(
            receipt,
            service="operator-service",
            source_commit="c" * 40,
            archive_sha256="a" * 64,
            image_digest="sha256:" + "b" * 64,
        )


@pytest.mark.parametrize(
    ("service", "active_update"),
    [
        ("operator-service", None),
        (
            "core-control-plane",
            {
                "service": "core-control-plane",
                "image": "example.azurecr.io/core-control-plane@sha256:" + "9" * 64,
                "source_commit": "9" * 40,
            },
        ),
    ],
)
def test_source_service_update_builds_imports_plans_and_verifies(
    tmp_path: Path,
    monkeypatch,
    service: str,
    active_update: dict[str, str] | None,
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

    def materialize(_source, destination, **_kwargs):
        destination.mkdir(mode=0o700)
        return "s" * 64

    monkeypatch.setattr("fdai_deployment_cli.source_service_update.materialize_source", materialize)
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.service_source_projection",
        lambda *_args: ("service.py",),
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._build_image",
        lambda **kwargs: _built_image(Path(kwargs["work_dir"]), service),
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
                "service": service,
                "target_binding": "d" * 64,
                "active_service_update": active_update,
            }
        if command == "import-source-image":
            return _imported_image(service)
        if command == "prepare-service-update":
            return {
                "service": service,
                "image": f"example.azurecr.io/{service}@sha256:" + "b" * 64,
                "source_commit": "c" * 40,
            }
        if command == "recover-apply":
            return {"state": "not-required"}
        if command == "plan":
            return {"review_digest": "f" * 64}
        if command == "finalize-service-update":
            return {
                "state": "finalized",
                "service": service,
                "apply_receipt_digest": "1" * 64,
                "mutation_performed": False,
                "receipt_digest": "2" * 64,
            }
        assert command == "apply"
        return {
            "operation": f"service-update-{service}-aaaaaaaaaaaa",
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
        service=service,
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
    timing_files = list((work / "timing").glob("*.json"))
    assert len(timing_files) == 1
    timing = json.loads(timing_files[0].read_text(encoding="utf-8"))
    assert timing["lane"] == "source-service-update"
    assert timing["source_snapshot_schema"] == "fdai.source-snapshot.v2"
    assert timing["source_projection_file_count"] == 1
    assert timing["source_projection_bytes"] == 1
    assert timing["image_archive_bytes"] == 3
    assert timing["effect_receipt_digest"] == result["receipt_digest"]
    assert timing["timing_evidence_only"] is True
    assert [call[0] for call in calls] == [
        "adopt-historical-aks-application",
        "service-update-context",
        "import-source-image",
        "prepare-service-update",
        "recover-apply",
        "plan",
        "apply",
        "finalize-service-update",
    ]


def test_new_authority_profile_is_written_after_intent_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    application = tmp_path / "application"
    source_root.mkdir(mode=0o700)
    application.mkdir(mode=0o700)
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
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.materialize_source",
        lambda _source, destination, **_kwargs: destination.mkdir(mode=0o700) or "s" * 64,
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.service_source_projection",
        lambda *_args: ("service.py",),
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._host_json",
        lambda *_args, **_kwargs: {
            "schema_version": "fdai.source-service-update-context.v1",
            "state": "verified",
            "service": "core-control-plane",
            "target_binding": "d" * 64,
            "active_service_update": None,
        },
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._build_image",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("reached image build")),
    )
    profile = SimpleNamespace(profile_json='{"profile_id":"dev"}', input_digest="e" * 64)

    with pytest.raises(RuntimeError, match="reached image build"):
        deploy_source_service_update(
            source_root=source_root,
            application_work_dir=application,
            work_dir=tmp_path / "update",
            service="core-control-plane",
            timeout_seconds=300,
            development_authority_profile=profile,
        )

    update = tmp_path / "update"
    assert (update / "source-service-update-intent.json").is_file()
    assert (update / "development-authority-profile.json").is_file()


def test_source_image_builder_cannot_write_into_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "0")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(snapshot / "redirected-cache"))
    script = snapshot / "tree/scripts/deployment/azure/source_image_build.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        'import snapshot_import_probe\nprint(\'{"state":"built"}\')\n',
        encoding="utf-8",
    )
    (script.parent / "snapshot_import_probe.py").write_text(
        "VALUE = 'loaded'\n",
        encoding="utf-8",
    )

    result = source_service_update._build_image(
        snapshot=snapshot,
        snapshot_digest="a" * 64,
        work_dir=tmp_path / "work",
        service="core-control-plane",
        timeout_seconds=60,
    )

    assert result["state"] == "built"
    assert not (script.parent / "__pycache__").exists()
    assert not (snapshot / "redirected-cache").exists()


@pytest.mark.parametrize("recovery_state", ["not-required", "applied"])
def test_source_service_update_reconciles_historical_baseline_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery_state: str
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir(mode=0o700)
    application = tmp_path / "application"
    application.mkdir(mode=0o700)
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
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.materialize_source",
        lambda _source, destination, **_kwargs: (
            destination.mkdir(mode=0o700),
            "s" * 64,
        )[1],
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update.service_source_projection",
        lambda *_args: ("service.py",),
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_service_update._build_image",
        lambda **kwargs: _built_image(Path(kwargs["work_dir"]), "operator-service"),
    )
    calls: list[tuple[str, ...]] = []
    adoption_attempts = 0

    def host(_work_dir, arguments, **_kwargs):
        nonlocal adoption_attempts
        calls.append(arguments)
        command = arguments[0]
        if command == "adopt-historical-aks-application":
            adoption_attempts += 1
            if adoption_attempts == 1:
                return {
                    "schema_version": "fdai.historical-aks-application-adoption.v1",
                    "state": "reconciliation-required",
                    "reconciliation_review": {
                        "schema_version": "fdai.standalone-application-plan.v1",
                        "stage": "application",
                        "review_digest": "r" * 64,
                        "historical_reconciliation": {
                            "operation": "historical-reconciliation",
                            "variables_digest": "v" * 64,
                            "mutations": ['kubernetes_deployment_v1.workload["operator-service"]'],
                        },
                    },
                    "mutation_performed": False,
                }
            return {
                "schema_version": "fdai.historical-aks-application-adoption.v1",
                "state": "adopted",
                "managed_identity_verified": True,
                "remote_state_verified": True,
                "live_baseline_verified": True,
                "terraform_zero_change_verified": True,
                "azure_resource_mutation_performed": False,
            }
        if command == "recover-historical-aks-reconciliation":
            return {
                "state": recovery_state,
                "effect_verified": recovery_state == "applied",
                "terraform_zero_change_verified": recovery_state == "applied",
                "mutation_performed": recovery_state == "applied",
            }
        if command == "apply-historical-aks-reconciliation":
            return {
                "state": "applied",
                "effect_verified": True,
                "terraform_zero_change_verified": True,
                "mutation_performed": True,
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
            return _imported_image("operator-service")
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
        if command == "apply":
            return {
                "operation": "service-update-operator-service-aaaaaaaaaaaa",
                "receipt_digest": "1" * 64,
                "control_plane_readback_verified": True,
                "peer_state_unchanged_verified": True,
                "terraform_zero_change_verified": True,
            }
        if command == "finalize-service-update":
            return {
                "state": "finalized",
                "service": "operator-service",
                "apply_receipt_digest": "1" * 64,
                "mutation_performed": False,
                "receipt_digest": "2" * 64,
            }
        raise AssertionError(f"unexpected command: {command}")

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
    plan_reviews: list[dict[str, object]] = []

    def approve_plan(_root: Path, review: dict[str, object]) -> Path:
        plan_reviews.append(review)
        return approval

    result = deploy_source_service_update(
        source_root=source_root,
        application_work_dir=application,
        work_dir=tmp_path / "update",
        service="operator-service",
        timeout_seconds=14400,
        adopt_historical_binding=adoption[0],
        adopt_historical_state=adoption[1],
        adopt_historical_variables=adoption[2],
        adopt_historical_live=adoption[3],
        adopt_historical_plan=adoption[4],
        approve_import=lambda *_: approval,
        approve_plan=approve_plan,
    )

    assert result["state"] == "applied"
    assert [call[0] for call in calls] == [
        "adopt-historical-aks-application",
        "recover-historical-aks-reconciliation",
        *(["apply-historical-aks-reconciliation"] if recovery_state == "not-required" else []),
        "adopt-historical-aks-application",
        "service-update-context",
        "import-source-image",
        "prepare-service-update",
        "recover-apply",
        "plan",
        "apply",
        "finalize-service-update",
    ]
    assert len(plan_reviews) == (2 if recovery_state == "not-required" else 1)
    if recovery_state == "not-required":
        assert plan_reviews[0]["historical_reconciliation"]["operation"] == (
            "historical-reconciliation"
        )
    assert plan_reviews[-1] == {"review_digest": "f" * 64}


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
        to_mapping=dict,
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
