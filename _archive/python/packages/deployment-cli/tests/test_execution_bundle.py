from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fdai_deployment_cli import execution_bundle as implementation
from fdai_deployment_cli.execution_bundle import (
    ExecutionBundleSource,
    prepare_execution_bundle,
    prepare_run_command_receiver,
)
from fdai_deployment_cli.run_command_receiver import receive_execution_bundle


def test_execution_bundle_prepares_reusable_exact_inventory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    config = source / "binding.json"
    config.write_text("{}", encoding="utf-8")
    config.chmod(0o600)
    tool = source / "terraform"
    tool.write_bytes(b"verified tool")
    tool.chmod(0o700)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)

    receipt = prepare_execution_bundle(
        (
            ExecutionBundleSource(config, "evidence/binding.json"),
            ExecutionBundleSource(tool, "toolchain/terraform"),
        ),
        work,
        operation_id="historical-aks-1352",
    )
    reused = prepare_execution_bundle(
        (
            ExecutionBundleSource(config, "evidence/binding.json"),
            ExecutionBundleSource(tool, "toolchain/terraform"),
        ),
        work,
        operation_id="historical-aks-1352",
    )
    received = receive_execution_bundle(
        work / "execution-bundle.tar.gz",
        tmp_path / "received",
        expected_digest=str(receipt["bundle_digest"]),
        expected_operation_id="historical-aks-1352",
    )

    assert reused == receipt
    assert received["file_count"] == 2
    assert received["inventory_digest"] == receipt["inventory_digest"]
    assert (tmp_path / "received/evidence/binding.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "received/toolchain/terraform").stat().st_mode & 0o777 == 0o700


def test_execution_bundle_rejects_linked_input(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    target = source / "target"
    target.write_text("value", encoding="utf-8")
    link = source / "link"
    link.symlink_to(target)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="regular single-link file"):
        prepare_execution_bundle(
            (ExecutionBundleSource(link, "evidence/link"),),
            work,
            operation_id="historical-aks-1352",
        )

    assert not (work / "execution-bundle.tar.gz").exists()


def test_execution_bundle_holds_source_directory_across_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    selected = source / "binding.json"
    selected.write_text("original", encoding="utf-8")
    selected.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o700)
    (replacement / "binding.json").write_text("redirected", encoding="utf-8")
    (replacement / "binding.json").chmod(0o600)
    retained = tmp_path / "retained"
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    original_digest = implementation._descriptor_digest
    swapped = False

    def digest(*args: object, **kwargs: object) -> str:
        nonlocal swapped
        value = original_digest(*args, **kwargs)  # type: ignore[arg-type]
        if not swapped:
            source.rename(retained)
            source.symlink_to(replacement, target_is_directory=True)
            swapped = True
        return value

    monkeypatch.setattr(implementation, "_descriptor_digest", digest)
    receipt = prepare_execution_bundle(
        (ExecutionBundleSource(source, "evidence"),),
        work,
        operation_id="historical-aks-1352",
    )
    receive_execution_bundle(
        work / "execution-bundle.tar.gz",
        tmp_path / "received",
        expected_digest=str(receipt["bundle_digest"]),
        expected_operation_id="historical-aks-1352",
    )

    assert (tmp_path / "received/evidence/binding.json").read_text() == "original"


def test_fixed_receiver_zipapp_verifies_bundle(tmp_path: Path) -> None:
    source = tmp_path / "binding.json"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    receipt = prepare_execution_bundle(
        (ExecutionBundleSource(source, "evidence/binding.json"),),
        work,
        operation_id="historical-aks-1352",
    )
    receiver_digest = prepare_run_command_receiver(work)

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            str(work / "run-command-receiver.pyz"),
            "--archive",
            str(work / "execution-bundle.tar.gz"),
            "--destination",
            str(tmp_path / "received"),
            "--bundle-digest",
            str(receipt["bundle_digest"]),
            "--operation-id",
            "historical-aks-1352",
            "--claim-digest",
            "d" * 64,
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["state"] == "verified"
    assert len(receiver_digest) == 64
