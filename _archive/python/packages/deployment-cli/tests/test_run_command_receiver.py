from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from fdai_deployment_cli import run_command_receiver as implementation
import fdai_deployment_cli.run_command_receiver as receiver
from fdai_deployment_cli.run_command_receiver import receive_execution_bundle


def test_receiver_syncs_directories_before_reporting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "bundle.tar.gz"
    digest = _archive(archive)
    synced: list[Path] = []
    original = implementation._sync_directory

    def sync(path: Path) -> None:
        synced.append(path)
        original(path)

    monkeypatch.setattr(implementation, "_sync_directory", sync)
    receive_execution_bundle(
        archive,
        tmp_path / "received",
        expected_digest=digest,
        expected_operation_id="historical-aks-1352",
    )

    assert synced[-3].name == "payload"
    assert synced[-2].name.startswith(".received.extract-")
    assert synced[-1] == tmp_path


def _archive(path: Path, *, member_name: str = "fdai-execution/payload/value.txt") -> str:
    content = b"verified payload"
    manifest = {
        "schema_version": "fdai.execution-bundle-manifest.v1",
        "operation_id": "historical-aks-1352",
        "files": {
            "payload/value.txt": {
                "sha256": hashlib.sha256(content).hexdigest(),
                "mode": "0600",
            }
        },
    }
    with tarfile.open(path, "w:gz") as stream:
        for name, value in (
            ("fdai-execution/manifest.json", json.dumps(manifest).encode()),
            (member_name, content),
        ):
            item = tarfile.TarInfo(name)
            item.size = len(value)
            stream.addfile(item, io.BytesIO(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_receiver_extracts_exact_manifest_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    digest = _archive(archive)

    result = receive_execution_bundle(
        archive,
        tmp_path / "execution",
        expected_digest=digest,
        expected_operation_id="historical-aks-1352",
    )

    assert result["state"] == "verified"
    assert result["file_count"] == 1
    assert result["bundle_digest"] == digest
    assert (tmp_path / "execution/payload/value.txt").read_bytes() == b"verified payload"
    assert (tmp_path / "execution/payload/value.txt").stat().st_mode & 0o777 == 0o600


def test_receiver_total_limit_counts_payload_not_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "bundle.tar.gz"
    digest = _archive(archive)
    monkeypatch.setattr(receiver, "_MAX_TOTAL_BYTES", len(b"verified payload"))

    result = receive_execution_bundle(
        archive,
        tmp_path / "execution",
        expected_digest=digest,
        expected_operation_id="historical-aks-1352",
    )

    assert result["file_count"] == 1


def test_receiver_rejects_traversal_before_publish(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.tar.gz"
    digest = _archive(archive, member_name="fdai-execution/../outside.txt")
    destination = tmp_path / "execution"

    with pytest.raises(ValueError, match="path is invalid"):
        receive_execution_bundle(
            archive,
            destination,
            expected_digest=digest,
            expected_operation_id="historical-aks-1352",
        )

    assert not destination.exists()
    assert not (tmp_path / "outside.txt").exists()


def test_receiver_verifies_existing_bundle_without_reextracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "bundle.tar.gz"
    digest = _archive(archive)
    destination = tmp_path / "execution"
    first = receive_execution_bundle(
        archive,
        destination,
        expected_digest=digest,
        expected_operation_id="historical-aks-1352",
    )

    monkeypatch.setattr(
        implementation,
        "_extract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("verification must not extract the archive")
        ),
    )

    second = receive_execution_bundle(
        None,
        destination,
        expected_digest=digest,
        expected_operation_id="historical-aks-1352",
        verify_existing=True,
    )

    assert second == first
