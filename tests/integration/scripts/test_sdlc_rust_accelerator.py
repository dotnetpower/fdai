"""Parity and fail-closed hardening tests for the Rust SDLC accelerator and Python fallback."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
from pathlib import Path

import pytest
from scripts.automation import local_validation_inputs as inputs
from scripts.automation import sdlc_rust_accelerator as accel


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed Git arguments against a temporary repository.
        ["git", *arguments],  # noqa: S607 - Git is the fixed test executable.
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.name", "Example User")
    _git(root, "config", "user.email", "user@example.com")
    return root


def test_rust_binary_compiles_and_matches_python_snapshot_and_venv_digests(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_DISABLE_RUST_ACCELERATOR", raising=False)
    binary = accel.ensure_binary(repo)
    assert binary is not None and binary.is_file()

    # Create files across SHA-1/SHA-256 block boundaries plus executable and symlink entries.
    for length in (0, 1, 55, 56, 64, 1000):
        (repo / f"file_{length}.txt").write_bytes(b"x" * length)
    script = repo / "run.sh"
    script.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    script.chmod(0o755)
    (repo / "link.txt").symlink_to("file_55.txt")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "initial")

    tree_rust, files_rust = inputs.tracked_snapshot(repo)
    monkeypatch.setenv("FDAI_DISABLE_RUST_ACCELERATOR", "1")
    tree_py, files_py = inputs.tracked_snapshot(repo)
    assert tree_rust == tree_py
    assert files_rust == files_py

    # Also verify installed_digest parity with and without skip_bytecode.
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_bytes(b"interpreter")
    (venv / "pkg.py").write_bytes(b"print('hello')\n")
    (venv / "__pycache__").mkdir()
    (venv / "__pycache__" / "pkg.cpython-313.pyc").write_bytes(b"\x00\x01\x02")
    (venv / "bin" / "python3").symlink_to("python")

    monkeypatch.delenv("FDAI_DISABLE_RUST_ACCELERATOR", raising=False)
    digest_rust_all = inputs.installed_digest(venv, skip_bytecode=False)
    digest_rust_no_bc = inputs.installed_digest(venv, skip_bytecode=True)

    monkeypatch.setenv("FDAI_DISABLE_RUST_ACCELERATOR", "1")
    digest_py_all = inputs.installed_digest(venv, skip_bytecode=False)
    digest_py_no_bc = inputs.installed_digest(venv, skip_bytecode=True)

    assert digest_rust_all == digest_py_all
    assert digest_rust_no_bc == digest_py_no_bc
    assert digest_rust_all != digest_rust_no_bc


def test_rust_verify_snapshot_enforces_all_fail_closed_boundaries(
    repo: Path,
    tmp_path: Path,
) -> None:
    (repo / "source.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "source.py")
    _git(repo, "commit", "--quiet", "-m", "initial")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    ls_tree = inputs.git(repo, "ls-tree", "-rz", "--full-tree", tree)

    # 1. Byte modification -> ValueError("bytes differ").
    (repo / "source.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bytes differ"):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 2. Executable mode mismatch -> ValueError("executable mode differs").
    (repo / "source.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "source.py").chmod(0o755)
    with pytest.raises(ValueError, match="executable mode differs"):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 3. File type mismatch (replaced file with symlink to inside repo).
    (repo / "other.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "source.py").unlink()
    (repo / "source.py").symlink_to("other.py")
    with pytest.raises(ValueError, match="file type differs"):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 4. Chained symlink escaping checkout root -> ValueError("external input").
    (repo / "hop.py").symlink_to(tmp_path / "nonexistent_outside.py")
    (repo / "source.py").unlink()
    (repo / "source.py").symlink_to("hop.py")
    with pytest.raises(ValueError, match="external input"):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 5. Symlink loop -> OSError.
    (repo / "hop.py").unlink()
    (repo / "hop.py").symlink_to("source.py")
    with pytest.raises(OSError, match="symlink loop"):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 6. Missing file -> OSError.
    (repo / "hop.py").unlink()
    (repo / "source.py").unlink()
    with pytest.raises(OSError):
        accel.rust_verify_snapshot(repo, "sha1", ls_tree)

    # 7. Non-blob entry (commit/submodule) -> ValueError("external input").
    submodule_ls_tree = b"160000 commit " + (b"a" * 40) + b"\tsubmodule\0"
    with pytest.raises(ValueError, match="external input"):
        accel.rust_verify_snapshot(repo, "sha1", submodule_ls_tree)


def test_rust_installed_files_rejects_escaping_symlink_directory(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_bytes(b"interpreter")
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (venv / "escape").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="installed directory escapes"):
        accel.rust_installed_files(venv)


def test_rust_check_translations_enforces_all_four_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    en = docs / "guide.md"
    en.write_text("# Guide\n", encoding="utf-8")
    en_bytes = en.read_bytes()
    en_sha = hashlib.sha1(f"blob {len(en_bytes)}\0".encode() + en_bytes).hexdigest()  # noqa: S324 - Git SHA-1 blob calculation for test fixture.
    ko = docs / "guide-ko.md"
    ko.write_text(
        f"---\ntranslation_of: guide.md\ntranslation_source_sha: {en_sha}\n---\n# 가이드\n",
        encoding="utf-8",
    )

    assert accel.run_check_translations(tmp_path, ["docs/guide.md"], ["docs/guide-ko.md"]) == 0
    assert "OK (1 English docs, 1 translations verified)" in capsys.readouterr().out

    # Stale SHA fails.
    en.write_text("# Guide updated\n", encoding="utf-8")
    assert accel.run_check_translations(tmp_path, ["docs/guide.md"], ["docs/guide-ko.md"]) == 1
    assert "stale translation" in capsys.readouterr().err

    # Orphan and out-of-scope Korean docs fail.
    orphan = docs / "orphan-ko.md"
    orphan.write_text(
        "---\ntranslation_of: orphan.md\ntranslation_source_sha: 0\n---\n", encoding="utf-8"
    )
    assert accel.run_check_translations(tmp_path, [], ["docs/orphan-ko.md"]) == 1
    assert "orphan translation" in capsys.readouterr().err

    # CLI entry point and fallback exit code 125 when disabled.
    monkeypatch.setattr("sys.stdin", io.StringIO("EN\tdocs/guide.md\nKO\tdocs/guide-ko.md\n"))
    assert accel.main(["check-translations", "--root", str(tmp_path)]) == 1
    capsys.readouterr()

    monkeypatch.setenv("FDAI_DISABLE_RUST_ACCELERATOR", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("EN\tdocs/guide.md\n"))
    assert accel.main(["check-translations", "--root", str(tmp_path)]) == 125
    assert accel.ensure_binary(tmp_path) is None
    assert accel.rust_verify_snapshot(tmp_path, "sha1", b"") is None
    assert accel.rust_installed_files(tmp_path) is None
    assert accel.run_check_translations(tmp_path, [], []) is None


def test_secure_owner_path_rejects_symlinks_and_world_writable_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secure = tmp_path / "secure"
    secure.mkdir(mode=0o700)
    os.chmod(secure, 0o700)
    assert accel._is_secure_owner_path(secure)

    link = tmp_path / "link"
    link.symlink_to(secure)
    assert not accel._is_secure_owner_path(link)

    writable = tmp_path / "writable"
    writable.mkdir(mode=0o777)
    os.chmod(writable, 0o777)  # noqa: S103 - intentional world-writable fixture for security guard test.
    assert not accel._is_secure_owner_path(writable)
    assert not accel._is_secure_owner_path(tmp_path / "missing")

    # When rustc is absent on PATH, ensure_binary returns None cleanly.
    monkeypatch.setattr(accel.shutil, "which", lambda _name: None)
    monkeypatch.setattr(accel, "_cache_bin_dir", lambda: tmp_path / "empty-bin")
    assert accel.ensure_binary() is None


def test_cold_compile_prunes_stale_binaries_and_handles_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_cache_bin_dir = accel._cache_bin_dir
    fresh_bin = tmp_path / "fresh-bin"
    fresh_bin.mkdir(mode=0o700)
    os.chmod(fresh_bin, 0o700)
    stale = fresh_bin / "fdai-sdlc-rs-0000000000000000"
    stale.write_bytes(b"stale")
    monkeypatch.setattr(accel, "_cache_bin_dir", lambda: fresh_bin)

    compiled = accel.ensure_binary()
    assert compiled is not None and compiled.is_file()
    assert not stale.exists()
    # Second call hits cached binary immediately.
    assert accel.ensure_binary() == compiled

    # Subprocess timeout kills child and raises TimeoutExpired.
    with pytest.raises(subprocess.TimeoutExpired):
        accel._run_subprocess(["sleep", "5"], timeout=0)

    # _raise_mapped_error default ValueError branch.
    with pytest.raises(ValueError, match="custom failure"):
        accel._raise_mapped_error("custom failure")

    # Insecure bin_dir and failed rustc compilation return None cleanly.
    bad_dir = tmp_path / "bad-bin"
    bad_dir.mkdir(mode=0o777)
    os.chmod(bad_dir, 0o777)  # noqa: S103 - intentional world-writable fixture for security guard test.
    monkeypatch.setattr(accel, "_cache_bin_dir", lambda: bad_dir)
    assert accel.ensure_binary() is None

    fail_bin = tmp_path / "fail-bin"
    monkeypatch.setattr(accel, "_cache_bin_dir", lambda: fail_bin)
    monkeypatch.setattr(accel, "_run_subprocess", lambda *_a, **_kw: (1, b"", b"compile failed"))
    assert accel.ensure_binary() is None
    monkeypatch.setattr(accel, "_cache_bin_dir", real_cache_bin_dir)
    assert accel._cache_bin_dir().name.startswith("fdai-sdlc-rs-")
