from __future__ import annotations

import os
import runpy
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = runpy.run_path(str(ROOT / "scripts/deployment/release/extract-kubelogin-archive.py"))
extract_kubelogin_archive = MODULE["extract_kubelogin_archive"]
KubeloginArchiveError = MODULE["KubeloginArchiveError"]


def _write_archive(
    path: Path,
    *,
    member_name: str = "bin/linux_amd64/kubelogin",
    extra: tuple[str, bytes, int] | None = None,
) -> None:
    members = [(member_name, b"kubelogin-binary", 0o100755)]
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
    return parent / "kubelogin"


def test_extracts_sole_kubelogin_binary(tmp_path: Path) -> None:
    archive = tmp_path / "kubelogin.zip"
    output = _private_output(tmp_path)
    _write_archive(archive)

    size = extract_kubelogin_archive(archive, output)

    assert size == len(b"kubelogin-binary")
    assert output.read_bytes() == b"kubelogin-binary"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    "member_name,extra",
    [
        ("../kubelogin", None),
        ("bin/linux_amd64/other", None),
        ("bin/linux_amd64/kubelogin", ("unexpected", b"x", 0o100644)),
    ],
)
def test_rejects_unexpected_member_sets(
    tmp_path: Path,
    member_name: str,
    extra: tuple[str, bytes, int] | None,
) -> None:
    archive = tmp_path / "kubelogin.zip"
    output = _private_output(tmp_path)
    _write_archive(archive, member_name=member_name, extra=extra)

    with pytest.raises(KubeloginArchiveError):
        extract_kubelogin_archive(archive, output)

    assert not output.exists()


def test_rejects_linked_archive(tmp_path: Path) -> None:
    archive = tmp_path / "kubelogin.zip"
    linked = tmp_path / "linked.zip"
    output = _private_output(tmp_path)
    _write_archive(archive)
    os.link(archive, linked)

    with pytest.raises(KubeloginArchiveError):
        extract_kubelogin_archive(linked, output)

    assert not output.exists()


def test_cli_maps_errors_to_sanitized_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _private_output(tmp_path)
    main: Any = MODULE["main"]

    assert main(["--archive", str(tmp_path / "missing.zip"), "--output", str(output)]) == 2
    assert capsys.readouterr().err == "kubelogin archive extraction failed\n"
