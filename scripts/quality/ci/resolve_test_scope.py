"""Classify a Git diff for expensive CI test jobs."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_PYTHON_PREFIXES = (
    "packages/",
    "services/",
    "src/",
    "tests/",
    "scripts/",
    "alembic/",
    "config/",
    "examples/",
    "extensions/",
    "mocks/",
    "policies/",
    "rule-catalog/",
    "tools/",
)
_PYTHON_FILES = frozenset(
    {
        "alembic.ini",
        "Dockerfile",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
    }
)


def classify_paths(paths: list[str]) -> tuple[bool, bool]:
    python = any(path.startswith(_PYTHON_PREFIXES) or path in _PYTHON_FILES for path in paths)
    docs = any(path.startswith("docs/") or path in {"README.md", "README-ko.md"} for path in paths)
    return python, docs


def _changed_paths(diff_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", diff_range],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", required=True, dest="diff_range")
    args = parser.parse_args()
    python, docs = classify_paths(_changed_paths(args.diff_range))
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as stream:
        stream.write(f"python={str(python).lower()}\n")
        stream.write(f"docs={str(docs).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
