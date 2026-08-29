from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/deployment/release/issue-license.py"
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("issue_license", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.remove(str(PATH.parent))
read_key_file = MODULE.read_key_file
write_private_text = MODULE._write_private_text


def test_license_output_is_created_private(tmp_path: Path) -> None:
    output = tmp_path / "license.token"

    write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "token\n"
    assert output.stat().st_mode & 0o777 == 0o600


def test_license_output_never_replaces_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "license.token"
    output.write_text("existing\n", encoding="ascii")
    output.chmod(0o644)

    with pytest.raises(FileExistsError):
        write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "existing\n"
    assert output.stat().st_mode & 0o777 == 0o644


def test_license_main_writes_canonical_token_without_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = tmp_path / "private.pem"
    private_key.write_bytes(b"private")
    private_key.chmod(0o600)
    public_key = tmp_path / "public.pem"
    public_key.write_bytes(b"public")
    output = tmp_path / "license.token"
    monkeypatch.setattr(MODULE, "issue_license", lambda **_kwargs: "abc.def")

    assert (
        MODULE.main(
            [
                "--private-key",
                str(private_key),
                "--public-key",
                str(public_key),
                "--license-id",
                "lic-test",
                "--distribution-id",
                "example-distribution",
                "--capability",
                "cost.metering",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == b"abc.def"


def test_release_key_reader_is_private_bounded_no_follow_and_nonblocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "private.pem"
    os.mkfifo(fifo, mode=0o600)
    real_open = os.open

    def open_nonblocking(path: os.PathLike[str], flags: int) -> int:
        assert flags & os.O_NONBLOCK
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", open_nonblocking)
    with pytest.raises(ValueError, match="regular file"):
        read_key_file(fifo, private=True)

    private_key = tmp_path / "key.pem"
    private_key.write_bytes(b"key")
    private_key.chmod(0o644)
    with pytest.raises(PermissionError, match="mode 0600"):
        read_key_file(private_key, private=True)
    private_key.chmod(0o600)
    assert read_key_file(private_key, private=True) == b"key"

    oversized = tmp_path / "oversized.pem"
    oversized.write_bytes(b"x" * 65_537)
    with pytest.raises(ValueError, match="65536"):
        read_key_file(oversized, private=False)

    linked = tmp_path / "linked.pem"
    linked.symlink_to(private_key)
    with pytest.raises(OSError):
        read_key_file(linked, private=False)
