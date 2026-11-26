from __future__ import annotations

import os
import runpy
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = runpy.run_path(str(ROOT / "scripts/deployment/release/extract-terraform-archive.py"))
extract_terraform_archive = MODULE["extract_terraform_archive"]
TerraformArchiveError = MODULE["TerraformArchiveError"]


def _write_archive(
    path: Path,
    *,
    terraform_mode: int = 0o100755,
    extra: tuple[str, bytes, int] | None = None,
) -> None:
    members = [
        ("LICENSE.txt", b"license", 0o100644),
        ("terraform", b"terraform-binary", terraform_mode),
    ]
    if extra is not None:
        members.append(extra)
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, payload, mode in members:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)


def _private_output(tmp_path: Path) -> Path:
    parent = tmp_path / "output"
    parent.mkdir(mode=0o700)
    return parent / "terraform"


def test_extracts_exact_official_shape_as_executable(tmp_path: Path) -> None:
    archive = tmp_path / "terraform.zip"
    output = _private_output(tmp_path)
    _write_archive(archive)

    size = extract_terraform_archive(archive, output)

    assert size == len(b"terraform-binary")
    assert output.read_bytes() == b"terraform-binary"
    assert stat.S_IMODE(output.stat().st_mode) == 0o755


def test_stream_failure_removes_partial_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "terraform.zip"
    output = _private_output(tmp_path)
    _write_archive(archive)
    original_read = zipfile.ZipExtFile.read
    calls = 0

    def interrupted_read(stream: zipfile.ZipExtFile, size: int = -1) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic read failure")
        return original_read(stream, size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", interrupted_read)

    with pytest.raises(OSError, match="synthetic read failure"):
        extract_terraform_archive(archive, output)

    assert not output.exists()


@pytest.mark.parametrize("failure", ["extra", "missing", "mode", "oversize", "truncated"])
def test_rejects_invalid_archive_without_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    archive = tmp_path / "terraform.zip"
    output = _private_output(tmp_path)
    if failure == "extra":
        _write_archive(archive, extra=("unexpected", b"x", 0o100644))
    elif failure == "missing":
        with zipfile.ZipFile(archive, mode="w") as zipped:
            zipped.writestr("terraform", b"binary")
    elif failure == "mode":
        _write_archive(archive, terraform_mode=0o120777)
    elif failure == "oversize":
        _write_archive(archive)
        monkeypatch.setitem(extract_terraform_archive.__globals__, "_MAX_BINARY_BYTES", 4)
    else:
        archive.write_bytes(b"not-a-zip")

    with pytest.raises((TerraformArchiveError, zipfile.BadZipFile)):
        extract_terraform_archive(archive, output)

    assert not output.exists()


@pytest.mark.parametrize("failure", ["symlink", "hardlink", "fifo", "existing", "public-parent"])
def test_rejects_unsafe_paths_without_replacement(tmp_path: Path, failure: str) -> None:
    archive = tmp_path / "terraform.zip"
    _write_archive(archive)
    output = _private_output(tmp_path)
    if failure == "symlink":
        linked = tmp_path / "linked.zip"
        linked.symlink_to(archive)
        archive = linked
    elif failure == "hardlink":
        linked = tmp_path / "linked.zip"
        os.link(archive, linked)
        archive = linked
    elif failure == "fifo":
        archive.unlink()
        os.mkfifo(archive)
    elif failure == "existing":
        output.write_bytes(b"keep")
    else:
        output.parent.chmod(0o755)

    with pytest.raises(TerraformArchiveError):
        extract_terraform_archive(archive, output)

    if failure == "existing":
        assert output.read_bytes() == b"keep"
    else:
        assert not output.exists()


def test_cli_maps_archive_errors_to_sanitized_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _private_output(tmp_path)
    main: Any = MODULE["main"]

    assert main(["--archive", str(tmp_path / "missing.zip"), "--output", str(output)]) == 2
    assert capsys.readouterr().err == "terraform archive extraction failed\n"
