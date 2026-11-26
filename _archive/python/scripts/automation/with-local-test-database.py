#!/usr/bin/env python3
"""Run a command with FDAI_DATABASE_URL bound to the local Docker validation PostgreSQL.

Usage:
    python3 scripts/automation/with-local-test-database.py uv run pytest <selectors>

Local tests that need ``FDAI_DATABASE_URL`` use the isolated loopback Docker PostgreSQL cluster
that full-stack preparation records as ``FDAI_VALIDATION_DATABASE_URL`` in the primary
checkout's ignored ``.fdai/local-runtime.env``. That cluster runs on port 5433, apart from the
runtime database on 5432, because migration tests change cluster-global roles. The script reads
only that one key, refuses a non-loopback host or the runtime port, never prints the DSN, and
replaces itself with the given command. An explicit ``FDAI_VALIDATION_DATABASE_URL`` in the
environment wins over the file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

_KEY = "FDAI_VALIDATION_DATABASE_URL"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_RUNTIME_PORT = 5432


class LocalTestDatabaseError(RuntimeError):
    """The local validation database URL is missing or unsafe for tests."""


def primary_checkout(start: Path) -> Path:
    """Return the primary checkout that owns ``.fdai/`` for a checkout or linked worktree."""

    completed = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise LocalTestDatabaseError("not inside a Git checkout")
    return Path(completed.stdout.strip()).parent


def local_test_database_url(environment: Mapping[str, str], env_file: Path) -> str:
    """Return the validated loopback validation-cluster URL."""

    value = environment.get(_KEY, "").strip()
    if not value and env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, candidate = raw_line.strip().partition("=")
            if separator and key == _KEY:
                value = candidate.strip().strip("'\"")
    if not value:
        raise LocalTestDatabaseError(
            f"{_KEY} is not configured; run the full-stack preparation to start the "
            "validation PostgreSQL cluster"
        )
    parts = urlsplit(value)
    if not parts.scheme.startswith("postgresql"):
        raise LocalTestDatabaseError(f"{_KEY} MUST be a PostgreSQL URL")
    if parts.hostname not in _LOOPBACK:
        raise LocalTestDatabaseError(f"{_KEY} MUST point at loopback Docker PostgreSQL")
    if parts.port in (None, _RUNTIME_PORT):
        raise LocalTestDatabaseError(f"{_KEY} MUST use the isolated validation cluster port")
    return value


def main(argv: Sequence[str]) -> int:
    if not argv:
        print("usage: with-local-test-database.py <command> [args...]", file=sys.stderr)
        return 64
    try:
        url = local_test_database_url(
            os.environ, primary_checkout(Path.cwd()) / ".fdai" / "local-runtime.env"
        )
    except LocalTestDatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    environment = dict(os.environ, FDAI_DATABASE_URL=url)
    os.execvpe(argv[0], list(argv), environment)  # noqa: S606 - the caller chooses the command


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
