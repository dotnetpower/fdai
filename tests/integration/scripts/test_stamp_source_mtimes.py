"""Contracts for content-derived source times that keep cached bytecode valid across checkouts."""

from __future__ import annotations

import importlib.util
import os
import py_compile
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "stamp_source_mtimes", ROOT / "scripts/quality/ci/stamp-source-mtimes.py"
)
assert SPEC is not None and SPEC.loader is not None
STAMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAMP)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "HOME": str(repository),
        },
    )


def _checkout(path: Path, files: dict[str, str]) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    _git(path, "add", "-A")
    return path


def test_the_stamp_comes_from_the_blob_id_inside_the_pyc_header_range() -> None:
    listing = (
        "100644 ab12cd34ef567890ab12cd34ef567890ab12cd34 0\tpkg/a.py\n"
        "100755 ffffffffffffffffffffffffffffffffffffffff 0\tpkg/b.py\n"
        "120000 1111111111111111111111111111111111111111 0\tlink.py\n"
        "160000 2222222222222222222222222222222222222222 0\tmodule.py\n"
        "100644 0000000000000000000000000000000000000000 0\tzero.py\n"
    )
    stamps = STAMP.stamps(listing)
    assert set(stamps) == {"pkg/a.py", "pkg/b.py", "zero.py"}
    assert stamps["pkg/a.py"] == 0xAB12CD34 & 0x7FFFFFFF
    assert all(0 < value <= 0x7FFFFFFF for value in stamps.values())


def test_identical_content_gets_the_same_time_in_independent_checkouts(tmp_path: Path) -> None:
    files = {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"}
    first = _checkout(tmp_path / "one", files)
    second = _checkout(tmp_path / "two", files)
    os.utime(second / "a.py", (1_700_000_000, 1_700_000_000))
    assert STAMP.main(["--root", str(first)]) == 0
    assert STAMP.main(["--root", str(second)]) == 0
    for name in files:
        assert (first / name).stat().st_mtime == (second / name).stat().st_mtime


def test_changed_content_changes_the_time(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"a.py": "x = 1\n"})
    STAMP.main(["--root", str(repository)])
    before = (repository / "a.py").stat().st_mtime
    (repository / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repository, "add", "-A")
    STAMP.main(["--root", str(repository)])
    assert (repository / "a.py").stat().st_mtime != before


def test_bytecode_from_one_checkout_validates_in_another(tmp_path: Path) -> None:
    files = {"module.py": "VALUE = 41\n"}
    first = _checkout(tmp_path / "one", files)
    second = _checkout(tmp_path / "two", files)
    for repository in (first, second):
        STAMP.main(["--root", str(repository)])
    cached = Path(py_compile.compile(str(first / "module.py"), doraise=True))
    other = Path(importlib.util.cache_from_source(str(second / "module.py")))
    other.parent.mkdir(exist_ok=True)
    other.write_bytes(cached.read_bytes())
    _, flags, mtime, size = struct.unpack("<4sIII", other.read_bytes()[:16])
    source = (second / "module.py").stat()
    assert flags == 0
    assert (mtime, size) == (int(source.st_mtime) & 0xFFFFFFFF, source.st_size)


def test_untracked_and_symlinked_files_are_left_alone(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"tracked.py": "a = 1\n"})
    (repository / "untracked.py").write_text("b = 2\n", encoding="utf-8")
    os.utime(repository / "untracked.py", (1_600_000_000, 1_600_000_000))
    (repository / "link.py").symlink_to("tracked.py")
    _git(repository, "add", "link.py")
    STAMP.main(["--root", str(repository)])
    assert (repository / "untracked.py").stat().st_mtime == 1_600_000_000
