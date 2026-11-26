"""Contract-preserving Hub coordinator input and receipt helpers."""

from argparse import Namespace
from pathlib import Path

import pytest

from fdai_deployment_cli import hub_image_deploy, source_application_inputs
from fdai_deployment_cli.contracts import canonical_digest


@pytest.mark.parametrize("mode", ["hub", "source", "offline"])
def test_default_work_directory_preserves_artifact_mode(mode):
    args = Namespace(
        hub=Path(".") if mode == "hub" else None,
        source=Path(".") if mode == "source" else None,
        work_dir=None,
    )
    directory = "azure" if mode == "offline" else f"azure-{mode}"
    assert hub_image_deploy.deployment_work_dir(args) == (
        Path.home() / ".local/state/fdai" / directory
    )


@pytest.mark.parametrize("directory", [Path("private-run"), Path("/private-run")])
def test_explicit_work_directory_needs_no_artifact_mode(directory, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = Namespace(work_dir=directory)
    expected = directory if directory.is_absolute() else tmp_path / directory
    assert hub_image_deploy.deployment_work_dir(args) == expected


@pytest.mark.parametrize("require_receipt", [False, True])
def test_hub_receipt_keeps_support_identity(hub_image_selection, require_receipt):
    result = {"state": "prepared", "receipt_digest": "a" * 64}
    hub_image_deploy.bind_support_receipt(
        result, hub_image_selection, require_receipt=require_receipt
    )
    assert result["support_receipt_digest"] == "a" * 64
    assert result["hub_selection_digest"] == hub_image_selection.digest
    assert result["receipt_digest"] == canonical_digest(
        {name: value for name, value in result.items() if name != "receipt_digest"}
    )


def test_unreceipted_review_does_not_acquire_success_receipt(hub_image_selection):
    result = {"state": "review"}
    hub_image_deploy.bind_support_receipt(result, hub_image_selection)
    assert result["hub_selection_digest"] == hub_image_selection.digest
    assert "receipt_digest" not in result
    assert "support_receipt_digest" not in result


def test_source_or_offline_receipts_and_preparation_are_unchanged():
    result = {"receipt_digest": "a" * 64}
    hub_image_deploy.bind_support_receipt(result, None, require_receipt=True)
    assert result == {"receipt_digest": "a" * 64}
    assert hub_image_deploy.application_selection(None, False, object()) is None
    assert hub_image_deploy.source_binding("b" * 64, None) == {
        "source_snapshot_digest": "b" * 64,
        "provenance": "operator-selected-source",
    }


def test_host_support_arguments_and_snapshot_identity_are_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    artifacts = source_application_inputs.SourceHostArtifacts(
        source_commit="a" * 40,
        artifact_root=tmp_path / "snapshot/tree",
        infra=tmp_path / "infra",
        terraform=tmp_path / "terraform",
        kit_bin=tmp_path / "bin",
        digest="b" * 64,
    )
    captured = {}

    def prepare(**kwargs):
        captured.update(kwargs)
        return artifacts

    monkeypatch.setattr(source_application_inputs, "source_host_artifacts", prepare)
    args = Namespace(
        source_snapshot=Path("snapshot"),
        source_snapshot_digest="b" * 64,
        runtime_support=Path("runtime.tar.gz"),
        runtime_support_digest="c" * 64,
    )
    assert source_application_inputs.prepare_host_artifacts(args, tmp_path, "a" * 40) is artifacts
    assert captured == {
        "source_snapshot": tmp_path / "snapshot",
        "snapshot_digest": "b" * 64,
        "expected_source_commit": "a" * 40,
        "work_dir": tmp_path,
        "runtime_support": tmp_path / "runtime.tar.gz",
        "runtime_support_digest": "c" * 64,
    }
    assert artifacts.snapshot_metadata() == {
        "source_snapshot": str(tmp_path / "snapshot"),
        "source_snapshot_digest": "b" * 64,
    }
