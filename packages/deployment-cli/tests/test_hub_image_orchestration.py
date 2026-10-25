"""Exercise the real transfer/parser and coordinator seams without live services."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import (
    aks_preflight,
    cli,
    hub_image_deploy,
    source_azure,
    source_deploy,
    source_recovery,
    standalone_application_completion,
    standalone_host,
)
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.hub_image_deploy import prepare_hub_selection
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_remote_prepare import prepare_remote
from fdai_deployment_cli.target import compute_target_binding

COMMIT = "a" * 40
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def catalog(hub_image_catalog):
    return hub_image_catalog


@pytest.fixture
def selection(hub_image_selection):
    return hub_image_selection


@pytest.fixture
def checkout(hub_image_checkout):
    return hub_image_checkout


def mock_catalog(catalog, monkeypatch):
    raw, signature = catalog.export()
    from fdai_deployment_cli.hub_image_trust import key_id

    monkeypatch.setattr(
        hub_image_deploy,
        "hub_request",
        lambda *_args, **_kwargs: (
            200,
            {
                "x-fdai-export-signature": signature,
                "x-fdai-export-key-id": key_id(catalog.key.public_key()),
            },
            raw,
        ),
    )
    return raw


def test_selection_is_immutable_and_does_not_mix_checkout_revisions(catalog, monkeypatch):
    root = catalog.root / "checkout"
    root.mkdir()
    work = catalog.root / "work"
    key = catalog.root / "public.pem"
    key.write_bytes(catalog.pem)
    monkeypatch.setattr(
        hub_image_deploy, "inspect_source", lambda _root: SimpleNamespace(root=root, commit=COMMIT)
    )
    mock_catalog(catalog, monkeypatch)
    args = {"source_root": root, "work_dir": work, "public_key_path": key}
    selected = prepare_hub_selection(**args)
    assert prepare_hub_selection(**args).digest == selected.digest
    assert selected.path == work / "hub-images/selection.json"
    assert selected.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="channel"):
        prepare_hub_selection(**args, channel="DEV")
    catalog.document["revision"] = 3
    mock_catalog(catalog, monkeypatch)
    with pytest.raises(ValueError, match="rollback"):
        prepare_hub_selection(**args)
    catalog.document["revision"] = 5
    mock_catalog(catalog, monkeypatch)
    with pytest.raises(ValueError, match="immutable catalog selection changed"):
        prepare_hub_selection(**args)
    catalog.manifest["source_commit"] = "b" * 40
    mock_catalog(catalog, monkeypatch)
    with pytest.raises(ValueError, match="Check out the exact approved commit"):
        prepare_hub_selection(**{**args, "work_dir": catalog.root / "other-work"})
    assert not (catalog.root / "other-work").exists()


def test_source_mode_never_adopts_hub_image_preparation(selection, tmp_path, monkeypatch):
    monkeypatch.setattr(
        source_deploy, "inspect_source", lambda _root: SimpleNamespace(root=tmp_path, commit=COMMIT)
    )
    work = tmp_path / "hub-run"
    (work / "hub-images").mkdir(parents=True)
    with pytest.raises(ValueError, match="source builds cannot reuse"):
        source_deploy.prepare_source_deployment(
            source_root=tmp_path,
            work_dir=work,
            runtime_profile=RuntimeDeploymentProfile.create(
                runtime_platform="aks", database_placement="postgres-flex"
            ),
            region="westus2",
            monthly_cost_ceiling=500,
        )


def test_hub_selection_is_sealed_into_real_source_preparation(checkout, catalog, monkeypatch):
    from fdai_deployment_cli.source_input import inspect_source

    catalog.manifest["source_commit"] = inspect_source(checkout).commit
    mock_catalog(catalog, monkeypatch)
    key = catalog.root / "public.pem"
    key.write_bytes(catalog.pem)
    work = catalog.root / "real-hub-run"
    selected = prepare_hub_selection(source_root=checkout, work_dir=work, public_key_path=key)
    arguments = {
        "source_root": checkout,
        "work_dir": work,
        "runtime_profile": RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        "region": "westus2",
        "monthly_cost_ceiling": 500,
        "hub_selection_digest": selected.digest,
    }
    prepared = source_deploy.prepare_source_deployment(**arguments)
    assert source_deploy.prepare_source_deployment(**arguments) == prepared
    assert prepared["hub_selection_digest"] == selected.digest
    assert prepared["image_artifact_source"] == "hub-signed-images"
    intent = json.loads(read_private_bytes(work / "source-intent.json", max_bytes=65_536))
    assert intent["hub_selection_digest"] == selected.digest
    assert intent["artifact_source"] == "hub-signed-images"
    with pytest.raises(ValueError, match="source builds cannot reuse"):
        source_deploy.prepare_source_deployment(
            **{key: value for key, value in arguments.items() if key != "hub_selection_digest"}
        )


class Tunnel:
    def __init__(self):
        self.copies = {}
        self.commands = []

    def copy_to(self, source, destination, *, timeout):
        self.copies[destination] = source.read_bytes()

    def ssh(self, command, *, timeout):
        self.commands.append(command)
        if command[0] == "sha256sum":
            stdout = hashlib.sha256(self.copies[command[1]]).hexdigest() + "  file\n"
        elif "prepare-source" in command:
            stdout = '{"state":"prepared","focused_private_access":false}'
        else:
            stdout = ""
        return SimpleNamespace(returncode=0, stdout=stdout)


def test_real_remote_transfer_carries_exact_hub_selection_into_host_parser(
    selection, tmp_path, monkeypatch
):
    handoff = tmp_path / "handoff.json"
    handoff.write_text("{}")
    source = tmp_path / "source.tar"
    source.write_bytes(b"source snapshot")
    receiver = tmp_path / "receiver.pyz"
    receiver.write_bytes(b"receiver")
    support = tmp_path / "support.tar"
    support.write_bytes(b"support")
    remote = "/home/fdai/.fdai-transfer-test"
    tunnel = Tunnel()
    prepare_remote(
        tunnel,
        remote_root=remote,
        remote_archive=f"{remote}/kit.tar.gz",
        archive=None,
        archive_digest=None,
        handoff_path=handoff,
        remote_handoff=f"{remote}/handoff.json",
        entra_path=None,
        remote_entra=None,
        app_work=str(tmp_path / "application"),
        source_archive=source,
        source_archive_digest=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_receiver=receiver,
        source_receiver_digest=hashlib.sha256(receiver.read_bytes()).hexdigest(),
        source_runtime_support=support,
        source_runtime_support_digest=hashlib.sha256(support.read_bytes()).hexdigest(),
        source_snapshot_digest="d" * 64,
        timeout_seconds=1800,
        hub_selection=selection,
    )
    transferred = tunnel.copies[f"{remote}/hub-selection.json"]
    assert transferred == read_private_bytes(selection.path, max_bytes=12 * 1024 * 1024)
    command = next(command for command in tunnel.commands if "prepare-source" in command)
    captured = {}
    monkeypatch.setattr(
        standalone_host,
        "_prepare",
        lambda args, _work_dir: captured.update(vars(args)) or {"state": "prepared"},
    )
    # Parsing the actual transfer command must neither drop nor reconstruct the selection.
    assert standalone_host.main(list(command[3:])) == 0
    assert str(captured["hub_selection"]) == f"{remote}/hub-selection.json"
    assert captured["hub_selection_digest"] == selection.digest
    assert captured["source_snapshot_digest"] == "d" * 64


def test_recovery_keeps_exact_hub_selection_and_final_mixed_provenance(
    selection, tmp_path, monkeypatch
):
    source_root = tmp_path / "checkout"
    source_root.mkdir()
    work = tmp_path / "work"
    recovery = work / "foundation-recovery-attempt-1"
    binding = compute_target_binding(subscription_id=SUBSCRIPTION, tenant_id=SUBSCRIPTION)
    (work / "foundation").mkdir(mode=0o700, parents=True)
    work.chmod(0o700)
    write_private_bytes(
        work / "source-intent.json",
        canonical_bytes(
            {
                "hub_selection_digest": selection.digest,
                "artifact_source": "hub-signed-images",
            }
        ),
    )
    marker = {"source_commit": COMMIT, "target_binding": binding}
    marker["receipt_digest"] = canonical_digest(marker)
    write_private_bytes(work / "foundation/source-genesis.json", canonical_bytes(marker))
    monkeypatch.setattr(
        aks_preflight,
        "_active_human_target",
        lambda _deadline: (
            SUBSCRIPTION,
            SUBSCRIPTION,
        ),
    )
    monkeypatch.setattr(
        source_azure,
        "inspect_source",
        lambda *_args, **_kwargs: SimpleNamespace(root=source_root, commit=COMMIT),
    )
    calls = []
    monkeypatch.setattr(
        hub_image_deploy,
        "record_deployment_request",
        lambda selected, **kwargs: calls.append(("request", selected.digest)) or {},
    )
    progress = {
        "stage": "application-plan",
        "source_commit": COMMIT,
        "target_binding": binding,
        "foundation_receipt_digest": "a" * 64,
        "receipt_digest": "b" * 64,
        "execution_source_commit": COMMIT,
    }
    monkeypatch.setattr(source_recovery, "resume_source_installation", lambda **_: progress)
    monkeypatch.setattr(
        source_recovery,
        "recovered_application_evidence",
        lambda **_: SimpleNamespace(
            run_binding="c" * 64,
            status={},
            source_snapshot_digest="d" * 64,
            state_handoff_digest="e" * 64,
        ),
    )
    captured = {}

    def deploy(**kwargs):
        calls.append(("application", kwargs["hub_selection"].digest))
        captured.update(kwargs)
        return {
            "receipt_digest": "f" * 64,
            "catalog_review_receipt_digest": "a" * 64,
            "catalog_review_state": "skipped",
            "inventory_ready": True,
            "license_mode": "trial",
        }

    monkeypatch.setattr(standalone_application_completion, "deploy_standalone_application", deploy)
    result = source_azure.plan_source_installation(
        source_root=source_root,
        work_dir=work,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="westus2",
        monthly_cost_ceiling=500,
        timeout_seconds=1800,
        foundation_recovery_directory=recovery,
        hub_selection=selection,
    )
    assert calls == [("request", selection.digest), ("application", selection.digest)]
    assert captured["source_snapshot"] == work / "source-snapshot"
    assert captured["foundation_recovery_directory"] == recovery
    assert result["hub_release_id"] == "1.2.0"
    assert result["provenance"] == "hub-signed-images-with-checkout-support"
    assert result["support_artifact_source"] == "operator-selected-source"
    assert result["image_signature_verified"] is True
    assert result["release_signature_verified"] is False


@pytest.mark.parametrize("key_from_environment", [False, True])
def test_cli_uses_hub_coordinator_and_reports_no_full_release_claim(
    selection, tmp_path, monkeypatch, capsys, key_from_environment
):
    if key_from_environment:
        monkeypatch.setenv("FDAI_HUB_PUBLIC_KEY", "public.pem")
    selected_arguments = {}
    monkeypatch.setattr(
        hub_image_deploy,
        "prepare_hub_selection",
        lambda **kwargs: selected_arguments.update(kwargs) or selection,
    )
    monkeypatch.setattr(cli, "ensure_azure_session", lambda: None)
    calls = []
    monkeypatch.setattr(
        cli,
        "plan_source_installation",
        lambda **kwargs: (
            calls.append(kwargs)
            or {
                "state": "deployment-ready",
                "deployment_ready": True,
            }
        ),
    )
    assert (
        cli.main(
            [
                "provision",
                "azure",
                "--hub",
                ".",
                *([] if key_from_environment else ["--hub-public-key", "public.pem"]),
                "--work-dir",
                str(tmp_path / "cli-work"),
                "--region",
                "westus2",
                "--output",
                "json",
            ]
        )
        == 0
    )
    assert calls[0]["hub_selection"].digest == selection.digest
    assert calls[0]["source_root"] == Path(".")
    assert selected_arguments["hub_url"] == "https://hub.msfdai.com"
    assert selected_arguments["channel"] == "RELEASE"
    assert selected_arguments["public_key_path"] == Path("public.pem")
    result = json.loads(capsys.readouterr().out)
    assert result["image_signature_verified"] is True
    assert result["release_signature_verified"] is False
    assert result["artifact_source"] == "hub-signed-images"


def test_hub_failure_never_falls_back_to_a_source_or_kit_coordinator(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hub_image_deploy,
        "prepare_hub_selection",
        lambda **_: (_ for _ in ()).throw(ValueError("catalog unavailable")),
    )
    monkeypatch.setattr(cli, "plan_source_installation", lambda **_: pytest.fail("source fallback"))
    monkeypatch.setattr(cli, "deploy_azure_foundation", lambda **_: pytest.fail("kit fallback"))
    assert (
        cli.main(
            [
                "provision",
                "azure",
                "--hub",
                ".",
                "--hub-public-key",
                "public.pem",
                "--work-dir",
                str(tmp_path / "run"),
            ]
        )
        == 3
    )


@pytest.mark.parametrize("mode", ["--source", "--offline-kit"])
def test_explicit_modes_have_no_hub_network_dependency(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("FDAI_HUB_PUBLIC_KEY", "unrelated-key.pem")
    monkeypatch.setattr(
        hub_image_deploy, "hub_request", lambda *_, **__: pytest.fail("unexpected Hub network")
    )
    ready = {"state": "deployment-ready", "deployment_ready": True}
    monkeypatch.setattr(cli, "plan_source_installation", lambda **_: dict(ready))
    monkeypatch.setattr(cli, "deploy_azure_foundation", lambda **_: dict(ready))
    assert (
        cli.main(
            [
                "provision",
                "azure",
                mode,
                "." if mode == "--source" else "kit.tar.gz",
                "--work-dir",
                str(tmp_path / "run"),
                "--output",
                "json",
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://hub.example.com",
        "https://user:secret@hub.example.com",
        "https://hub.example.com/v1",
        "https://hub.example.com?token=secret",
        "https://hub.example.com#fragment",
        "https://hub.example.com:99999",
    ],
)
def test_transport_origin_is_exact_https_without_credentials(origin):
    with pytest.raises(ValueError):
        hub_image_deploy.validate_hub_url(origin)
