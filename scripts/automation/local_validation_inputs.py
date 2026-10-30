"""Content identities for local-only, isolated structural validation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path

from scripts.automation.sdlc_rust_accelerator import (
    rust_installed_files,
    rust_verify_snapshot,
)

TOOLS = (
    "uv",
    "python3",
    "bash",
    "git",
    "grep",
    "sed",
    "awk",
    "find",
    "sort",
    "wc",
    "dirname",
    "cat",
    "cut",
    "head",
    "tr",
    "timeout",
    "env",
    "setsid",
    "sleep",
)
GATE_ENVIRONMENT = (
    "FILE_LOC_WARN",
    "FILE_LOC_FAIL",
    "FILE_LOC_MODE",
    "SUBSYSTEM_FANOUT_WARN",
    "SUBSYSTEM_FANOUT_FAIL",
    "SUBSYSTEM_FANOUT_MODE",
)
TRANSPORT_ENVIRONMENT = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
)


def digest(value: object) -> str:
    """Hash canonical JSON without persisting potentially private input values."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def git(root: Path, *arguments: str) -> bytes:
    """Read local Git plumbing with a bounded deadline and no inherited hook pointers."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.check_output(
        ["git", *arguments],
        cwd=root,
        env=environment,
        timeout=60,
        stderr=subprocess.PIPE,
    )


def tracked_snapshot(root: Path) -> tuple[str, dict[str, str]]:
    """Verify materialized bytes and modes against HEAD, including symlink contents.

    Git stat caches, assume-unchanged, and skip-worktree flags are not evidence.
    Submodules and symlinks escaping the checkout cannot certify a local snapshot.
    """
    tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    algorithm = git(root, "rev-parse", "--show-object-format").decode().strip()
    ls_tree_bytes = git(root, "ls-tree", "-rz", "--full-tree", tree)
    accelerated = rust_verify_snapshot(root, algorithm, ls_tree_bytes)
    if accelerated is not None:
        return tree, accelerated
    files: dict[str, str] = {}
    for entry in ls_tree_bytes.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, expected = metadata.decode().split()
        relative = os.fsdecode(raw_path)
        path = root / relative
        if kind != "blob" or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("snapshot contains an unsupported external input")
        attributes = path.lstat()
        if mode == "120000" and stat.S_ISLNK(attributes.st_mode):
            data = os.fsencode(os.readlink(path))
        elif mode in {"100644", "100755"} and stat.S_ISREG(attributes.st_mode):
            if bool(attributes.st_mode & stat.S_IXUSR) != (mode == "100755"):
                raise ValueError("snapshot executable mode differs from committed content")
            data = path.read_bytes()
        else:
            raise ValueError("snapshot file type differs from committed content")
        actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data)
        if actual.hexdigest() != expected:
            raise ValueError("snapshot bytes differ from committed content")
        files[relative] = expected
    return tree, files


def dependency_digest(files: dict[str, str]) -> str:
    """Bind frozen, non-workspace installation to every tracked uv project input."""
    required = {"pyproject.toml", "uv.lock"}
    if not required.issubset(files):
        raise ValueError("locked project dependency inputs are missing")
    return digest(
        {
            "files": {
                path: value
                for path, value in files.items()
                if Path(path).name in {"pyproject.toml", "uv.lock", "uv.toml", ".python-version"}
            },
            "arguments": [
                "--frozen",
                "--extra",
                "dev",
                "--no-install-workspace",
                "--python",
                "3.13",
            ],
        }
    )


def installed_digest(root: Path, *, skip_bytecode: bool = False) -> str:
    """Hash actual installed bytes, interpreter targets, modes, and file membership.

    ``skip_bytecode`` omits ``__pycache__`` entries, which the interpreter writes
    while tests run in a shared development environment.
    """
    if not (root / "bin/python").is_file():
        raise ValueError("validation Python environment is missing")
    accelerated = rust_installed_files(root, skip_bytecode=skip_bytecode)
    if accelerated is not None:
        return digest(accelerated)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("installed directory escapes the verified environment")
            continue
        if skip_bytecode and "__pycache__" in path.relative_to(root).parts:
            continue
        files[path.relative_to(root).as_posix()] = (
            stat.S_IMODE(path.stat().st_mode),
            os.readlink(path) if path.is_symlink() else "",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return digest(files)


def execution_environment(state: Path) -> tuple[dict[str, str], str]:
    """Use the same explicit tool/environment inputs in either local entry point.

    Caller Python paths, queue database settings, uv overrides and Git hook
    pointers never enter structural execution or its cache identity.
    Existing proxy and CA transport settings are retained and fingerprinted;
    their values and certificate bytes are not persisted in receipts.
    """
    search_path = os.pathsep.join(
        part
        for part in os.environ.get("PATH", os.defpath).split(os.pathsep)
        if part
        and Path(part).is_absolute()
        and not (Path(part).name == "bin" and Path(part).parent.name in {".venv", "venv"})
    )
    tool_paths = {}
    for name in TOOLS:
        path = shutil.which(name, path=search_path)
        if path is None:
            raise ValueError(f"required local validation tool is missing: {name}")
        tool_paths[name] = str(Path(path).resolve())
    environment = {
        "PATH": search_path,
        "HOME": os.environ.get("HOME", str(state)),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_NO_CONFIG": "1",
        "UV_PYTHON": "3.13",
        "UV_PROJECT_ENVIRONMENT": str(state / "venv"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.excludesFile",
        "GIT_CONFIG_VALUE_0": os.devnull,
    }
    environment.update(
        {
            name: os.environ[name]
            for name in (*GATE_ENVIRONMENT, *TRANSPORT_ENVIRONMENT)
            if name in os.environ
        }
    )
    for name, ceiling in (
        ("FDAI_STRUCTURAL_JOBS", 64),
        ("FDAI_STRUCTURAL_TIMEOUT_SECONDS", 3600),
    ):
        value = os.environ.get(name)
        if value is None:
            continue
        if (
            not value.isascii()
            or not value.isdecimal()
            or len(value) > 4
            or value.startswith("0")
            or not 1 <= int(value) <= ceiling
        ):
            raise ValueError(f"{name} must be an integer from 1 to {ceiling}")
        environment[name] = value
    certificate_digest = None
    if certificate_file := environment.get("SSL_CERT_FILE"):
        certificate_path = Path(certificate_file).resolve()
        environment["SSL_CERT_FILE"] = str(certificate_path)
        certificate_digest = hashlib.sha256(certificate_path.read_bytes()).hexdigest()
    tool_identity = {
        name: (path, hashlib.sha256(Path(path).read_bytes()).hexdigest())
        for name, path in tool_paths.items()
    }
    return environment, digest(
        {
            "tools": tool_identity,
            "platform": platform.platform(),
            "environment": environment,
            "certificate": certificate_digest,
        }
    )
