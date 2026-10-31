#!/usr/bin/env python3
"""Compile-on-demand bridge for the zero-dependency Rust SDLC accelerator with Python fallback."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CRATE_DIR = REPO_ROOT / "tools" / "fdai-sdlc-rs"
MAIN_RS = CRATE_DIR / "src" / "main.rs"
LIB_RS = CRATE_DIR / "src" / "lib.rs"
_MEMOIZED_DEFAULT_BIN_DIR: Path | None = None
_MEMOIZED_SOURCE_DIGEST: tuple[tuple[int, int, int, int], str] | None = None


def is_disabled() -> bool:
    """Return whether the caller explicitly disabled the Rust accelerator."""
    return os.environ.get("FDAI_DISABLE_RUST_ACCELERATOR", "").lower() in {"1", "true", "yes"}


def _clean_subprocess_env() -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", tempfile.gettempdir()),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if "TMPDIR" in os.environ:
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


def _is_secure_owner_path(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return (
        not stat.S_ISLNK(st.st_mode)
        and (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode))
        and st.st_uid == os.getuid()
        and (st.st_mode & 0o022) == 0
    )


def _is_secure_owner_dir(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return (
        not stat.S_ISLNK(st.st_mode)
        and stat.S_ISDIR(st.st_mode)
        and st.st_uid == os.getuid()
        and (st.st_mode & 0o022) == 0
    )


def source_digest() -> str | None:
    """Compute the SHA-256 digest of the Rust accelerator sources with stat memoization."""
    global _MEMOIZED_SOURCE_DIGEST
    if not _is_secure_owner_path(MAIN_RS) or not _is_secure_owner_path(LIB_RS):
        return None
    try:
        lib_st = LIB_RS.lstat()
        main_st = MAIN_RS.lstat()
    except OSError:
        return None
    sig = (lib_st.st_mtime_ns, lib_st.st_size, main_st.st_mtime_ns, main_st.st_size)
    if _MEMOIZED_SOURCE_DIGEST is not None and _MEMOIZED_SOURCE_DIGEST[0] == sig:
        return _MEMOIZED_SOURCE_DIGEST[1]
    hasher = hashlib.sha256()
    for path in (LIB_RS, MAIN_RS):
        hasher.update(path.name.encode("utf-8") + b"\0")
        hasher.update(path.read_bytes() + b"\0")
    digest = hasher.hexdigest()
    _MEMOIZED_SOURCE_DIGEST = (sig, digest)
    return digest


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    stdin_bytes: bytes | None = None,
    timeout: int = 60,
) -> tuple[int, bytes, bytes]:
    with subprocess.Popen(  # noqa: S603 - fixed compiler or verified cached repository binary.
        cmd,
        cwd=cwd,
        env=_clean_subprocess_env(),
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        return proc.returncode, stdout, stderr


def _cache_bin_dir() -> Path:
    global _MEMOIZED_DEFAULT_BIN_DIR
    if _MEMOIZED_DEFAULT_BIN_DIR is not None and not _MEMOIZED_DEFAULT_BIN_DIR.is_symlink():
        return _MEMOIZED_DEFAULT_BIN_DIR
    rc, out, _err = _run_subprocess(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=REPO_ROOT,
        timeout=10,
    )
    if rc == 0 and out.strip():
        common = Path(out.decode("utf-8", errors="replace").strip())
        resolved_common = (
            common.resolve() if common.is_absolute() else (REPO_ROOT / common).resolve()
        )
        candidate = resolved_common / "fdai-local-validation" / "bin"
        if not candidate.is_symlink() and not candidate.parent.is_symlink():
            _MEMOIZED_DEFAULT_BIN_DIR = candidate
            return candidate
    return Path(tempfile.gettempdir()) / f"fdai-sdlc-rs-{os.getuid()}"


def _ready_binary(path: Path) -> bool:
    return path.is_file() and _is_secure_owner_path(path) and os.access(path, os.X_OK)


def ensure_binary(_root: Path | None = None) -> Path | None:
    """Return the verified cached Rust binary, compiling once if `rustc` is available."""
    if is_disabled():
        return None
    digest = source_digest()
    if digest is None:
        return None
    bin_dir = _cache_bin_dir()
    if not bin_dir.exists():
        bin_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(bin_dir, 0o700)
    if not _is_secure_owner_dir(bin_dir):
        return None
    binary_path = bin_dir / f"fdai-sdlc-rs-{digest[:16]}"
    if _ready_binary(binary_path):
        return binary_path
    rustc = shutil.which("rustc")
    lock_path = bin_dir / "compile.lock"
    if (
        rustc is None
        or Path(rustc).name != "rustc"
        or not os.access(rustc, os.X_OK)
        or lock_path.is_symlink()
    ):
        return None
    try:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if _ready_binary(binary_path):
                return binary_path
            tmp_bin = bin_dir / f".fdai-sdlc-rs-{digest[:16]}.{os.getpid()}.tmp"
            try:
                rc, _out, _err = _run_subprocess(
                    [
                        rustc,
                        "--edition",
                        "2021",
                        "-O",
                        str(MAIN_RS),
                        "-o",
                        str(tmp_bin),
                    ],
                    cwd=CRATE_DIR,
                    timeout=60,
                )
                if rc != 0 or not tmp_bin.is_file():
                    return None
                os.chmod(tmp_bin, 0o700)
                tmp_bin.replace(binary_path)
                for stale in bin_dir.glob("fdai-sdlc-rs-*"):
                    if stale != binary_path:
                        stale.unlink(missing_ok=True)
                return binary_path if _ready_binary(binary_path) else None
            finally:
                tmp_bin.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError):
        return None


def _raise_mapped_error(stderr: str) -> None:
    line = stderr.strip().splitlines()[-1] if stderr.strip() else "Rust accelerator failed"
    if line.startswith("OSError: "):
        raise OSError(line.removeprefix("OSError: "))
    if line.startswith("ValueError: "):
        raise ValueError(line.removeprefix("ValueError: "))
    raise ValueError(line)


def rust_verify_snapshot(
    root: Path,
    algorithm: str,
    ls_tree_bytes: bytes,
) -> dict[str, str] | None:
    """Verify `git ls-tree -rz` bytes in parallel via Rust; return None when unavailable."""
    binary = ensure_binary(root)
    if binary is None:
        return None
    try:
        rc, _out, err = _run_subprocess(
            [str(binary), "verify-snapshot", "--root", str(root), "--algorithm", algorithm],
            stdin_bytes=ls_tree_bytes,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if rc != 0:
        _raise_mapped_error(err.decode("utf-8", errors="replace"))
    files: dict[str, str] = {}
    for entry in ls_tree_bytes.split(b"\0"):
        if not entry:
            continue
        if b"\t" not in entry:
            raise ValueError("malformed ls-tree entry")
        metadata, raw_path = entry.split(b"\t", 1)
        tokens = metadata.decode("utf-8", errors="replace").split()
        if len(tokens) < 3:
            raise ValueError("malformed ls-tree metadata")
        files[os.fsdecode(raw_path)] = tokens[2]
    return files


def rust_worktree_digests(
    root: Path,
    excluded: tuple[Path, ...],
    listed_bytes: bytes,
) -> tuple[str, str] | None:
    """Compute `(content_hex, status_hex)` for `worktree_digests` in parallel via Rust."""
    binary = ensure_binary(root)
    if binary is None:
        return None
    cmd = [str(binary), "worktree-digests", "--root", str(root)]
    for prefix in excluded:
        cmd.extend(["--exclude", str(prefix)])
    try:
        rc, out, err = _run_subprocess(cmd, stdin_bytes=listed_bytes, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if rc != 0:
        _raise_mapped_error(err.decode("utf-8", errors="replace"))
    tokens = out.decode("ascii", errors="replace").strip().split()
    if len(tokens) != 2:
        return None
    return tokens[0], tokens[1]


def rust_installed_files(
    root: Path,
    *,
    skip_bytecode: bool = False,
) -> dict[str, tuple[int, str, str]] | None:
    """Hash installed virtualenv files in parallel via Rust; return None when unavailable."""
    binary = ensure_binary()
    if binary is None:
        return None
    cmd = [str(binary), "installed-digest", "--root", str(root)]
    if skip_bytecode:
        cmd.append("--skip-bytecode")
    try:
        rc, out, err = _run_subprocess(cmd, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if rc != 0:
        _raise_mapped_error(err.decode("utf-8", errors="replace"))
    parts = out.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    if len(parts) % 4 != 0:
        return None
    files: dict[str, tuple[int, str, str]] = {}
    for index in range(0, len(parts), 4):
        rel = parts[index].decode("utf-8")
        imode = int(parts[index + 1].decode("ascii"))
        link = parts[index + 2].decode("utf-8")
        sha256_hex = parts[index + 3].decode("ascii")
        files[rel] = (imode, link, sha256_hex)
    return files


def run_check_translations(
    root: Path, english_docs: list[str], korean_docs: list[str]
) -> int | None:
    """Run parallel translation verification via Rust; return None when unavailable."""
    binary = ensure_binary(root)
    if binary is None:
        return None
    lines = [*(f"EN\t{path}" for path in english_docs), *(f"KO\t{path}" for path in korean_docs)]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        rc, out, err = _run_subprocess(
            [str(binary), "check-translations", "--root", str(root)],
            stdin_bytes=payload,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    if err:
        sys.stderr.buffer.write(err)
        sys.stderr.buffer.flush()
    return rc


def main(argv: list[str] | None = None) -> int:
    """CLI bridge for shell gates such as `check-translations.sh`."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    tr_parser = subparsers.add_parser("check-translations")
    tr_parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.command == "check-translations":
        raw = sys.stdin.read().splitlines()
        en_docs = [line[3:] for line in raw if line.startswith("EN\t") and len(line) > 3]
        ko_docs = [line[3:] for line in raw if line.startswith("KO\t") and len(line) > 3]
        rc = run_check_translations(args.root.resolve(), en_docs, ko_docs)
        return 125 if rc is None else rc
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
