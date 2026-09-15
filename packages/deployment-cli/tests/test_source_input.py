"""Real local Git inputs cannot acquire release or execution authority."""

from __future__ import annotations

import os
import hashlib
import io
import json
import tarfile
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import source_input
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_snapshot import materialize_source, verify_source_snapshot
from fdai_deployment_cli.source_transport import (
    archive_source_snapshot,
    receive_source_snapshot,
    prepare_source_transport,
)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "user@example.com")
    _git(root, "config", "user.name", "Example")
    _git(root, "config", "core.hooksPath", "/dev/null")
    (root / "source.py").write_text("VALUE = 1\n")
    (root / ".gitignore").write_text(".cache/\n")
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
    return root


def test_source_provenance_is_stable_and_not_a_release(checkout: Path) -> None:
    source = inspect_source(checkout)
    source.reverify()
    assert source.digest == inspect_source(checkout).digest
    assert source.to_mapping()["provenance"] == "operator-selected-source"
    assert source.to_mapping()["release_signature_verified"] is False
    assert str(checkout) not in str(source.to_mapping())


@pytest.mark.parametrize("change", ["dirty", "untracked", "index-hidden", "symlink", "hardlink"])
def test_source_drift_is_rejected(checkout: Path, change: str) -> None:
    source = inspect_source(checkout)
    path = checkout / "source.py"
    if change == "index-hidden":
        _git(checkout, "update-index", "--assume-unchanged", "source.py")
        path.write_text("VALUE = 2\n")
    elif change == "dirty":
        path.write_text("VALUE = 2\n")
    elif change == "untracked":
        (checkout / "extra.py").write_text("VALUE = 2\n")
    elif change == "symlink":
        path.unlink()
        path.symlink_to(checkout / ".gitignore")
        _git(checkout, "add", "source.py")
        _git(checkout, "-c", "commit.gpgsign=false", "commit", "-m", "symlink")
    else:
        os.link(path, checkout.parent / "hardlink")
    with pytest.raises((ValueError, OSError)):
        source.reverify()


def test_ignored_outputs_are_not_certified(checkout: Path) -> None:
    source = inspect_source(checkout)
    (checkout / ".cache").mkdir()
    (checkout / ".cache/output").write_text("not a deployment input")
    assert inspect_source(checkout) == source


def test_changed_commit_cannot_resume(checkout: Path) -> None:
    source = inspect_source(checkout)
    (checkout / "source.py").write_text("VALUE = 2\n")
    _git(checkout, "add", "source.py")
    _git(checkout, "-c", "commit.gpgsign=false", "commit", "-m", "next")
    with pytest.raises(ValueError, match="revision differs"):
        source.reverify()


def test_symlink_checkout_root_is_rejected(checkout: Path) -> None:
    link = checkout.parent / "linked"
    link.symlink_to(checkout, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlink"):
        inspect_source(link)


def test_tracked_relative_document_link_is_supported(checkout: Path) -> None:
    (checkout / "linked.py").symlink_to("source.py")
    _git(checkout, "add", "linked.py")
    _git(checkout, "-c", "commit.gpgsign=false", "commit", "-m", "internal link")
    assert inspect_source(checkout).file_count == 3


@pytest.mark.parametrize("target", ["../outside", "loop.py", ".cache/output"])
def test_unsafe_tracked_links_are_rejected(checkout: Path, target: str) -> None:
    (checkout.parent / "outside").write_text("outside")
    (checkout / ".cache").mkdir()
    (checkout / ".cache/output").write_text("ignored")
    (checkout / "loop.py").symlink_to(target)
    _git(checkout, "add", "loop.py")
    _git(checkout, "-c", "commit.gpgsign=false", "commit", "-m", "unsafe link")
    with pytest.raises(ValueError, match="source link"):
        inspect_source(checkout)


def test_source_snapshot_excludes_ignored_inputs_and_rechecks_bytes(checkout: Path) -> None:
    source = inspect_source(checkout)
    (checkout / ".cache").mkdir()
    (checkout / ".cache/private").write_text("must not transfer")
    destination = checkout.parent / "snapshot"
    digest = materialize_source(source, destination)
    assert verify_source_snapshot(destination, expected_digest=digest) == source.to_mapping()
    assert not (destination / "tree/.cache").exists()
    (destination / "tree/source.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="content changed"):
        verify_source_snapshot(destination, expected_digest=digest)


def test_source_snapshot_rejects_extra_files_and_never_overwrites(checkout: Path) -> None:
    source = inspect_source(checkout)
    destination = checkout.parent / "snapshot"
    digest = materialize_source(source, destination)
    (destination / "tree/extra").write_text("unexpected input")
    with pytest.raises(ValueError, match="file set"):
        verify_source_snapshot(destination, expected_digest=digest)
    with pytest.raises(FileExistsError):
        materialize_source(source, destination)


def test_reading_a_link_may_update_access_time(checkout: Path, monkeypatch) -> None:
    access_times = iter((1, 2))

    def observed_stat(*_args, **_kwargs):
        return SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_mode=0o120777,
            st_size=9,
            st_mtime_ns=10,
            st_ctime_ns=11,
            st_atime_ns=next(access_times),
        )

    monkeypatch.setattr(source_input.os, "stat", observed_stat)
    monkeypatch.setattr(source_input.os, "readlink", lambda *_args, **_kwargs: "source.py")
    assert source_input._read_tracked(checkout, "linked.py", mode="120000") == b"source.py"


def test_source_preparation_resumes_exact_intent_without_renewal(checkout: Path) -> None:
    arguments = {
        "source_root": checkout,
        "work_dir": checkout.parent / "run",
        "runtime_profile": RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        "region": "eastus",
        "monthly_cost_ceiling": 1000,
    }
    receipt = prepare_source_deployment(**arguments)
    assert prepare_source_deployment(**arguments) == receipt
    assert receipt["deployment_ready"] is False
    assert receipt["release_signature_verified"] is False
    with pytest.raises(ValueError, match="intent differs"):
        prepare_source_deployment(**{**arguments, "region": "westus"})


def test_source_preparation_cannot_adopt_kit_state(checkout: Path) -> None:
    work = checkout.parent / "kit-run"
    work.mkdir(mode=0o700)
    (work / "kit-work").mkdir()
    with pytest.raises(ValueError, match="cannot adopt"):
        prepare_source_deployment(
            source_root=checkout,
            work_dir=work,
            runtime_profile=RuntimeDeploymentProfile.create(
                runtime_platform="aks", database_placement="postgres-flex"
            ),
            region="eastus",
            monthly_cost_ceiling=1000,
        )


def test_source_transport_roundtrip_preserves_modes_and_internal_links(checkout):
    (checkout / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    (checkout / "run.sh").chmod(0o755)
    (checkout / "nested").mkdir()
    (checkout / "nested/linked.py").symlink_to("../source.py")
    _git(checkout, "add", ".")
    _git(checkout, "-c", "commit.gpgsign=false", "commit", "-m", "fixture executable and link")
    source = inspect_source(checkout)
    snapshot = checkout.parent / "snapshot"
    snapshot_digest = materialize_source(source, snapshot)
    archive = checkout.parent / "source.tar"
    digest = archive_source_snapshot(snapshot, archive, snapshot_digest=snapshot_digest)
    other = checkout.parent / "source-again.tar"
    assert archive_source_snapshot(snapshot, other, snapshot_digest=snapshot_digest) == digest
    destination = checkout.parent / "received"
    receipt = receive_source_snapshot(
        archive, destination, archive_digest=digest, snapshot_digest=snapshot_digest
    )
    assert (
        verify_source_snapshot(destination, expected_digest=snapshot_digest) == source.to_mapping()
    )
    assert (destination / "tree/run.sh").stat().st_mode & 0o777 == 0o700
    assert (destination / "tree/nested/linked.py").readlink() == Path("../source.py")
    assert not (destination / "tree/.git").exists()
    assert receipt["apply_authorized"] is False
    with pytest.raises(FileExistsError):
        receive_source_snapshot(
            archive, destination, archive_digest=digest, snapshot_digest=snapshot_digest
        )
    with pytest.raises(FileExistsError):
        archive_source_snapshot(snapshot, archive, snapshot_digest=snapshot_digest)


@pytest.mark.parametrize("corruption", ["archive", "snapshot", "mode", "link", "content"])
def test_source_transport_rejects_corruption_before_execution(checkout, corruption):
    source = inspect_source(checkout)
    snapshot = checkout.parent / "snapshot"
    snapshot_digest = materialize_source(source, snapshot)
    archive = checkout.parent / "source.tar"
    digest = archive_source_snapshot(snapshot, archive, snapshot_digest=snapshot_digest)
    if corruption == "archive":
        digest = "f" * 64
    elif corruption == "snapshot":
        snapshot_digest = "f" * 64
    elif corruption == "mode":
        archive.chmod(0o644)
    elif corruption == "link":
        linked = checkout.parent / "linked.tar"
        linked.symlink_to(archive)
        archive = linked
    else:
        with archive.open("ab") as stream:
            stream.write(b"unverified")
    destination = checkout.parent / "received"
    with pytest.raises((ValueError, OSError)):
        receive_source_snapshot(
            archive, destination, archive_digest=digest, snapshot_digest=snapshot_digest
        )
    assert not destination.exists()


def test_source_transfer_preparation_reverifies_without_overwriting(checkout):
    snapshot = checkout.parent / "snapshot"
    snapshot_digest = materialize_source(inspect_source(checkout), snapshot)
    work_dir = checkout.parent / "transfer"
    work_dir.mkdir(mode=0o700)
    first = prepare_source_transport(snapshot, work_dir, snapshot_digest=snapshot_digest)
    assert prepare_source_transport(snapshot, work_dir, snapshot_digest=snapshot_digest) == first
    assert first["remote_transfer_verified"] is False
    assert first["deployment_ready"] is False
    with (work_dir / "source-transfer.tar").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="digest differs"):
        prepare_source_transport(snapshot, work_dir, snapshot_digest=snapshot_digest)


@pytest.mark.parametrize(
    "corruption",
    [
        "absolute",
        "traversal",
        "extra",
        "duplicate",
        "symlink",
        "hardlink",
        "missing",
        "blob",
        "manifest-path",
        "directory-collision",
    ],
)
def test_source_transport_rejects_untrusted_archive_structure(checkout, corruption):
    snapshot = checkout.parent / "snapshot"
    snapshot_digest = materialize_source(inspect_source(checkout), snapshot)
    original = checkout.parent / "source.tar"
    archive_source_snapshot(snapshot, original, snapshot_digest=snapshot_digest)
    with tarfile.open(original) as archive:
        entries = [(member, archive.extractfile(member).read()) for member in archive]
    if corruption in {"manifest-path", "directory-collision"}:
        manifest = json.loads(entries[0][1])
        manifest["files"][0]["path"] = (
            "../escaped"
            if corruption == "manifest-path"
            else manifest["files"][1]["path"] + "/child"
        )
        manifest["source"]["content_digest"] = canonical_digest({"files": manifest["files"]})
        snapshot_digest = canonical_digest(manifest)
        entries[0] = (entries[0][0], canonical_bytes(manifest))
    if corruption == "absolute":
        entries[1][0].name = "/escaped"
    elif corruption == "traversal":
        entries[1][0].name = "../escaped"
    elif corruption in {"symlink", "hardlink"}:
        entries[1][0].type = tarfile.SYMTYPE if corruption == "symlink" else tarfile.LNKTYPE
        entries[1][0].linkname = "../../escaped"
    elif corruption == "extra":
        entries.append((tarfile.TarInfo("unexpected"), b"extra"))
    elif corruption == "duplicate":
        entries.insert(2, entries[1])
    elif corruption == "missing":
        entries.pop()
    elif corruption == "blob":
        entries[1] = (entries[1][0], b"changed")
    malicious = checkout.parent / "untrusted.tar"
    with tarfile.open(malicious, "w", format=tarfile.USTAR_FORMAT) as archive:
        for member, content in entries:
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    malicious.chmod(0o600)
    digest = hashlib.sha256(malicious.read_bytes()).hexdigest()
    with pytest.raises((ValueError, OSError)):
        receive_source_snapshot(
            malicious,
            checkout.parent / "received",
            archive_digest=digest,
            snapshot_digest=snapshot_digest,
        )
    assert not (checkout.parent / "escaped").exists()


@pytest.mark.parametrize("valid", [True, False])
def test_source_transport_cli_receives_without_execution(checkout, valid):
    source = inspect_source(checkout)
    snapshot = checkout.parent / "snapshot"
    snapshot_digest = materialize_source(source, snapshot)
    archive = checkout.parent / "source.tar"
    digest = archive_source_snapshot(snapshot, archive, snapshot_digest=snapshot_digest)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fdai_deployment_cli.source_transport",
            "--archive",
            str(archive),
            "--destination",
            str(checkout.parent / "received"),
            "--archive-digest",
            digest if valid else "f" * 64,
            "--snapshot-digest",
            snapshot_digest,
        ],
        cwd=checkout.parent,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(Path(source_input.__file__).parents[1])},
    )
    if valid:
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["source_commit"] == source.commit
        assert receipt["provenance"] == "operator-selected-source"
        assert receipt["deployment_ready"] is False
        assert receipt["apply_authorized"] is False
    else:
        assert result.returncode == 3
        assert result.stdout == ""
        assert "Traceback" not in result.stderr
        assert str(checkout.parent) not in result.stderr
