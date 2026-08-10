#!/usr/bin/env python3
"""Compare exact service deployment controls while ignoring release-only versions."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

STRICT_INPUTS = (
    ".github/workflows/service-deploy.yml",
    "scripts/deployment/service",
    "infra/services",
    "alembic",
    "alembic.ini",
    "service-migrations",
)
STRICT_EXCLUSIONS = (
    # This helper mutates only an isolated container-supply-chain build checkout. It is
    # not invoked by service-deploy and cannot change a saved plan or its apply behavior.
    ":(exclude)scripts/deployment/service/apply_image_build_override.py",
)
SEMANTIC_INPUTS = ("pyproject.toml", "uv.lock")


class DeploymentInputError(ValueError):
    """Report changed or unreadable deployment-control inputs."""


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _require_commit(repository: Path, revision: str) -> str:
    completed = _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if completed.returncode != 0:
        raise DeploymentInputError("deployment input revision is not a commit")
    return completed.stdout.strip()


def _text_at(repository: Path, revision: str, path: str) -> str:
    completed = _git(repository, "show", f"{revision}:{path}")
    if completed.returncode != 0:
        raise DeploymentInputError(f"cannot read deployment input {path}")
    return completed.stdout


def _normalized_pyproject(value: str) -> str:
    match = re.search(r"(?ms)^\[project\]\s*$.*?(?=^\[|\Z)", value)
    if match is None:
        raise DeploymentInputError("pyproject.toml must declare [project]")
    project = match.group(0)
    normalized_project, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"\s*$',
        'version = "<release-version>"',
        project,
    )
    if count != 1:
        raise DeploymentInputError("pyproject.toml must declare project.version")
    return value[: match.start()] + normalized_project + value[match.end() :]


def _normalized_lock(value: str) -> str:
    blocks = re.split(r"(?=^\[\[package\]\]\s*$)", value, flags=re.MULTILINE)
    matches = [
        index
        for index, block in enumerate(blocks)
        if re.search(r'(?m)^name\s*=\s*"fdai"\s*$', block)
        and re.search(r'(?m)^source\s*=\s*\{\s*virtual\s*=\s*"\."\s*\}\s*$', block)
    ]
    if len(matches) != 1:
        raise DeploymentInputError("uv.lock must contain one virtual fdai package")
    index = matches[0]
    normalized_block, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"\s*$',
        'version = "<release-version>"',
        blocks[index],
    )
    if count != 1:
        raise DeploymentInputError("uv.lock virtual fdai package must declare one version")
    blocks[index] = normalized_block
    return "".join(blocks)


def verify_unchanged(repository: Path, before: str, after: str) -> None:
    """Reject changed deployment controls except root release version metadata."""
    before_commit = _require_commit(repository, before)
    after_commit = _require_commit(repository, after)
    changed = _git(
        repository,
        "diff",
        "--quiet",
        before_commit,
        after_commit,
        "--",
        *STRICT_INPUTS,
        *STRICT_EXCLUSIONS,
    )
    if changed.returncode not in {0, 1}:
        raise DeploymentInputError("cannot compare strict deployment inputs")
    if changed.returncode == 1:
        raise DeploymentInputError("strict deployment inputs changed after plan creation")

    normalizers = {
        "pyproject.toml": _normalized_pyproject,
        "uv.lock": _normalized_lock,
    }
    for path in SEMANTIC_INPUTS:
        normalize = normalizers[path]
        if normalize(_text_at(repository, before_commit, path)) != normalize(
            _text_at(repository, after_commit, path)
        ):
            raise DeploymentInputError(f"semantic deployment input changed: {path}")


def main() -> int:
    """Compare two protected revisions and fail closed on deployment drift."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    try:
        verify_unchanged(args.repository, args.before, args.after)
    except DeploymentInputError as exc:
        parser.error(str(exc))
    print("deployment-inputs: unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
