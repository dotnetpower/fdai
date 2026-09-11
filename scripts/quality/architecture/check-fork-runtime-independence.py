#!/usr/bin/env python3
"""Reject fork-mode detection from runtime, deployment, and committed config paths."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SELF_PATH = Path("scripts/quality/architecture/check-fork-runtime-independence.py")


def _git_executable() -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git is required to evaluate tracked runtime files")
    return executable


GIT = _git_executable()

RUNTIME_ROOTS = (
    ".github/actions",
    ".github/workflows",
    ".vscode",
    "alembic",
    "benchmarks",
    "services",
    "packages",
    "console",
    "cli",
    "config",
    "delivery",
    "eval",
    "evaluation-sdk",
    "examples",
    "extensions",
    "fork",
    "infra",
    "mocks",
    "provider-schema-catalog",
    "rule-catalog",
    "policies",
    "security",
    "service-migrations",
    "src",
    "site",
    "tools",
    "ui",
    "scripts/agent",
    "scripts/automation",
    "scripts/benchmarking",
    "scripts/catalog",
    "scripts/deployment",
    "scripts/evaluation",
    "scripts/governance",
    "scripts/operations",
    "scripts/quality",
)
RUNTIME_FILES = (
    "Makefile",
    "alembic.ini",
    "azure.yaml",
    "docs/internals/sregym-absorption-ledger.json",
    "index.html",
    "pyproject.toml",
    "scripts/verify.sh",
    "uv.lock",
)
RUNTIME_PATHS = RUNTIME_ROOTS + RUNTIME_FILES
TOKENS = ("FDAI_FORK", ".fdai-fork", "fdai.fork")
TEXT_ENCODINGS = (
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
    "latin-1",
)


def _has_symlink_component(repo_root: Path, relative_path: Path) -> bool:
    current = repo_root
    for part in relative_path.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _candidate_files(repo_root: Path) -> list[Path]:
    completed = subprocess.run(  # noqa: S603 - resolved git executable and fixed arguments
        [
            GIT,
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *RUNTIME_PATHS,
        ],
        check=True,
        capture_output=True,
    )
    candidates: list[Path] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = Path(raw_path.decode("utf-8"))
        path = repo_root / relative_path
        if (
            relative_path == SELF_PATH
            or _has_symlink_component(repo_root, relative_path)
            or not path.is_file()
        ):
            continue
        candidates.append(path)
    return candidates


def violations(repo_root: Path = REPO_ROOT) -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for path in _candidate_files(repo_root):
        content = path.read_bytes()
        lines: list[str] = []
        for encoding in TEXT_ENCODINGS:
            try:
                decoded = content.decode(encoding)
            except UnicodeDecodeError:
                continue
            if any(token in decoded for token in TOKENS):
                lines = decoded.splitlines()
                break
        for line_number, line in enumerate(lines, start=1):
            if any(token in line for token in TOKENS):
                found.append((path.relative_to(repo_root), line_number, line.strip()))
    return found


def main() -> int:
    found = violations()
    if found:
        print(
            "fork-runtime-independence: ERROR: fork markers are repository-integrity signals "
            "and MUST NOT control runtime behavior",
            file=sys.stderr,
        )
        for path, line_number, line in found:
            print(f"  {path}:{line_number}: {line}", file=sys.stderr)
        return 1
    print("fork-runtime-independence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
