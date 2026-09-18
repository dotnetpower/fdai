"""Build a deterministic Console update artifact from protected Git source."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.console_config import MANUAL_STUDIO_PLACEHOLDER_URL
from fdai_deployment_cli.console_update import _regular_digest
from fdai_deployment_cli.private_output import _open_private_parent, write_private_output

_COMMIT = re.compile(r"[0-9a-f]{40}")


def build_console_update_artifact(
    *,
    source_root: Path,
    revision: str,
    output_dir: Path,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Build one preconfigured-placeholder Console archive without Azure access."""

    if not 60 <= timeout_seconds <= 1800:
        raise ValueError("Console artifact timeout MUST be between 60 and 1800 seconds")
    if not source_root.is_absolute() or not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("Console artifact source MUST be an absolute regular directory")
    if not output_dir.is_absolute() or output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Console artifact output MUST be a new absolute directory")
    parent = _open_private_parent(output_dir)
    os.close(parent)
    source_commit = _resolve_revision(source_root, revision, timeout_seconds=60)
    epoch = _git(
        source_root,
        "show",
        "-s",
        "--format=%ct",
        source_commit,
        timeout_seconds=60,
    ).stdout.strip()
    if not epoch.isdigit():
        raise ValueError("Console artifact source timestamp is invalid")

    with TemporaryDirectory(prefix=".console-artifact-", dir=output_dir.parent) as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        snapshot_archive = temporary_root / "source.tar"
        snapshot = temporary_root / "source"
        snapshot.mkdir(mode=0o700)
        _run(
            (
                "git",
                "-C",
                str(source_root),
                "archive",
                "--format=tar",
                f"--output={snapshot_archive}",
                source_commit,
            ),
            timeout_seconds=120,
        )
        _run(("tar", "-xf", str(snapshot_archive), "-C", str(snapshot)), timeout_seconds=120)
        _run(
            (
                "npm",
                "--prefix",
                str(snapshot / "console"),
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ),
            timeout_seconds=min(timeout_seconds, 600),
        )
        _run(
            ("npm", "--prefix", str(snapshot / "console"), "run", "build:offline"),
            timeout_seconds=timeout_seconds,
        )
        offline = snapshot / "console/dist/offline"
        _run(
            (
                sys.executable,
                str(snapshot / "scripts/deployment/azure/build_manual_studio_artifact.py"),
                str(offline / "manuals"),
                "--base-url",
                MANUAL_STUDIO_PLACEHOLDER_URL,
                "--repo-root",
                str(snapshot),
            ),
            timeout_seconds=timeout_seconds,
        )
        if not (offline / "index.html").is_file() or not (offline / "fdai-config.js").is_file():
            raise ValueError("Console artifact build output is incomplete")
        if not all(
            (offline / "manuals" / name).is_file()
            for name in ("catalog.json", "library.html", "target-architecture.html")
        ):
            raise ValueError("Console Manual Studio artifact build output is incomplete")
        staging = temporary_root / "artifact"
        staging.mkdir(mode=0o700)
        archive = staging / "console.tar.gz"
        _run(
            (
                "tar",
                "--sort=name",
                f"--mtime=@{epoch}",
                "--owner=0",
                "--group=0",
                "--numeric-owner",
                "--transform=s,^offline,dist,",
                "-czf",
                str(archive),
                "-C",
                str(snapshot / "console/dist"),
                "offline",
            ),
            timeout_seconds=120,
        )
        archive.chmod(0o600)
        archive_digest = _regular_digest(archive)
        manifest = {
            "schema_version": "fdai.console-update-artifact.v1",
            "source_commit": source_commit,
            "archive_sha256": archive_digest,
        }
        write_private_output(
            staging / "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        )
        os.rename(staging, output_dir)

    return {
        "schema_version": "fdai.console-update-artifact-build.v1",
        "source_commit": source_commit,
        "archive_sha256": archive_digest,
        "artifact_directory": str(output_dir),
        "azure_mutation_performed": False,
    }


def _resolve_revision(source_root: Path, revision: str, *, timeout_seconds: int) -> str:
    source_commit = _git(
        source_root,
        "rev-parse",
        "--verify",
        f"{revision}^{{commit}}",
        timeout_seconds=timeout_seconds,
    ).stdout.strip()
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("Console artifact revision is invalid")
    protected_head = _git(
        source_root,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main^{commit}",
        timeout_seconds=timeout_seconds,
    ).stdout.strip()
    if _COMMIT.fullmatch(protected_head) is None:
        raise ValueError("protected origin/main revision is unavailable")
    _git(
        source_root,
        "merge-base",
        "--is-ancestor",
        source_commit,
        protected_head,
        timeout_seconds=timeout_seconds,
    )
    return source_commit


def _git(
    source_root: Path, *arguments: str, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", "-C", str(source_root), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError("Console artifact source could not be verified")
    return completed


def _run(command: tuple[str, ...], *, timeout_seconds: int) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError("Console artifact build command failed")
