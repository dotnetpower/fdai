#!/usr/bin/env python3
"""Print the next automatic FDAI patch version from repository tags."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable

INITIAL_VERSION = (0, 1, 1)
VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def next_version(tags: Iterable[str]) -> str:
    """Return the next patch version, starting at 0.1.1."""
    versions = [
        tuple(int(part) for part in match.groups())
        for tag in tags
        if (match := VERSION_TAG.fullmatch(tag)) is not None
    ]
    if not versions:
        return ".".join(str(part) for part in INITIAL_VERSION)

    major, minor, patch = max(versions)
    return f"{major}.{minor}.{patch + 1}"


def repository_tags() -> list[str]:
    """Read tags from the current Git repository."""
    completed = subprocess.run(
        ["git", "tag", "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


if __name__ == "__main__":
    print(next_version(repository_tags()))
