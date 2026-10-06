"""Install source-deployment runtime support from the committed workspace lock.

A signed kit carries a prebuilt runtime wheelhouse. A source deployment has no such artifact, so
the workstation exports the committed ``uv.lock`` closure as one hashed requirements file and the
managed host installs exactly that closure before it adds the snapshot's workspace packages.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.standalone_host_state import private_json as _private_json

# Kept equal to the runtime and support package sets of
# scripts/deployment/release/stage-runtime-wheelhouse.py by a consistency test.
WORKSPACE_PACKAGES = {
    "fdai-service-contracts": "packages/service-contracts",
    "fdai-core-control-plane": "services/core-control-plane",
    "fdai-operator-service": "services/operator-service",
    "fdai-document-ingestion-api": "services/document-ingestion-api",
    "fdai-document-processing-worker": "services/document-processing-worker",
    "fdai-isolated-executor-service": "services/isolated-executor",
    "fdai-github-app-auth": "packages/github-app-auth",
    "fdai-runtime-diagnostics": "packages/runtime-diagnostics",
}
REQUIREMENTS_NAME = "source-runtime-requirements.txt"
_RECEIPT = "runtime-support-installation.json"
_SCHEMA = "fdai.source-runtime-support-installation.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_REQUIREMENTS = 4 * 1024 * 1024


def export_runtime_requirements(source_root: Path, destination: Path) -> str:
    """Export the locked third-party closure of every runtime workspace package."""
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise ValueError("source deployment requires uv to export the locked runtime closure")
    packages = tuple(argument for name in WORKSPACE_PACKAGES for argument in ("--package", name))
    cache = destination.parent / ".runtime-requirements-uv-cache"
    try:
        result = subprocess.run(
            (
                uv,
                "export",
                "--directory",
                str(source_root),
                "--locked",
                "--offline",
                *packages,
                "--no-dev",
                "--no-default-groups",
                "--no-emit-workspace",
                "--format",
                "requirements-txt",
                "--no-header",
                "--no-annotate",
                "--quiet",
            ),
            check=False,
            capture_output=True,
            timeout=120,
            env={**os.environ, "UV_CACHE_DIR": str(cache), "UV_NO_PROGRESS": "1"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("locked runtime closure export failed") from exc
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    content = result.stdout
    if result.returncode != 0 or not content or len(content) > _MAX_REQUIREMENTS:
        raise ValueError("locked runtime closure export failed")
    _validate_requirements(content)
    destination.unlink(missing_ok=True)
    write_private_output(destination, content.decode("utf-8"))
    return hashlib.sha256(content).hexdigest()


def install_source_runtime_support(
    work_dir: Path,
    *,
    source_root: Path,
    requirements: Path,
    requirements_digest: str,
    snapshot_digest: str,
) -> None:
    """Install the hashed lock closure, then the snapshot packages, and verify the result."""
    if _DIGEST.fullmatch(requirements_digest) is None or _DIGEST.fullmatch(snapshot_digest) is None:
        raise ValueError("source runtime support binding is invalid")
    content = read_private_bytes(requirements, max_bytes=_MAX_REQUIREMENTS)
    if hashlib.sha256(content).hexdigest() != requirements_digest:
        raise ValueError("source runtime requirements differ from the transferred digest")
    _validate_requirements(content)
    expected = _workspace_versions(source_root)
    environment = work_dir / "runtime-venv"
    receipt_path = work_dir / _RECEIPT
    if _retained_matches(
        environment,
        receipt_path,
        snapshot_digest=snapshot_digest,
        requirements_digest=requirements_digest,
        expected=expected,
        work_dir=work_dir,
    ):
        return
    # The environment is disposable tooling; any partial or stale one is rebuilt.
    receipt_path.unlink(missing_ok=True)
    if environment.is_symlink() or environment.is_file():
        environment.unlink()
    elif environment.exists():
        shutil.rmtree(environment)
    _run((sys.executable, "-m", "venv", str(environment)), work_dir, 120, "environment creation")
    pip = str(environment / "bin/pip")
    _run(
        (
            pip,
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--requirement",
            str(requirements),
        ),
        work_dir,
        1200,
        "locked dependency installation",
    )
    _run(
        (
            pip,
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "--no-deps",
            *(str(source_root / path) for path in WORKSPACE_PACKAGES.values()),
        ),
        work_dir,
        900,
        "workspace package installation",
    )
    write_private_output(
        receipt_path,
        json.dumps(
            {
                "schema_version": _SCHEMA,
                "snapshot_digest": snapshot_digest,
                "requirements_digest": requirements_digest,
                "package_readback_digest": _readback(
                    environment, expected=expected, work_dir=work_dir
                ),
                "dependencies_verified": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )


def _retained_matches(
    environment: Path,
    receipt_path: Path,
    *,
    snapshot_digest: str,
    requirements_digest: str,
    expected: dict[str, str],
    work_dir: Path,
) -> bool:
    if not receipt_path.is_file() or environment.is_symlink() or not environment.is_dir():
        return False
    try:
        receipt = _private_json(receipt_path, "source runtime support receipt")
        return (
            receipt.get("schema_version") == _SCHEMA
            and receipt.get("snapshot_digest") == snapshot_digest
            and receipt.get("requirements_digest") == requirements_digest
            and receipt.get("dependencies_verified") is True
            and receipt.get("package_readback_digest")
            == _readback(environment, expected=expected, work_dir=work_dir)
        )
    except (OSError, ValueError):
        return False


def _validate_requirements(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source runtime requirements are not UTF-8") from exc
    entries = [line for line in text.splitlines() if line and not line.startswith((" ", "#"))]
    if not entries or any(
        line.startswith(("-", ".", "/")) or "://" in line or "==" not in line for line in entries
    ):
        raise ValueError("source runtime requirements must pin index packages only")
    if "--hash=sha256:" not in text:
        raise ValueError("source runtime requirements must carry hashes")


def _workspace_versions(source_root: Path) -> dict[str, str]:
    versions = {}
    for name, path in WORKSPACE_PACKAGES.items():
        try:
            project = tomllib.loads((source_root / path / "pyproject.toml").read_text("utf-8"))[
                "project"
            ]
        except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
            raise ValueError("source runtime workspace package is unavailable") from exc
        if project.get("name") != name or not isinstance(project.get("version"), str):
            raise ValueError("source runtime workspace package metadata is invalid")
        versions[name] = project["version"]
    return versions


def _readback(environment: Path, *, expected: dict[str, str], work_dir: Path) -> str:
    pip = str(environment / "bin/pip")
    _run((pip, "check"), work_dir, 120, "dependency check")
    try:
        result = subprocess.run(
            (pip, "list", "--format=json", "--disable-pip-version-check"),
            cwd=work_dir,
            check=False,
            capture_output=True,
            timeout=120,
        )
        entries = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        entries = None
    if not isinstance(entries, list):
        raise ValueError("source runtime support package readback failed")
    observed: dict[str, str] = {}
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        version = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("source runtime support package readback is invalid")
        observed[re.sub(r"[-_.]+", "-", name.casefold())] = version
    if any(observed.get(name) != version for name, version in expected.items()):
        raise ValueError("source runtime workspace packages differ from the snapshot")
    return canonical_digest(observed)


def _run(command: tuple[str, ...], work_dir: Path, timeout: int, step: str) -> None:
    try:
        result = subprocess.run(
            command, cwd=work_dir, check=False, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"source runtime support {step} failed") from exc
    if result.returncode != 0:
        raise ValueError(f"source runtime support {step} failed")
