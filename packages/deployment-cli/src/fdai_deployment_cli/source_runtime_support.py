"""Install source-deployment runtime support from the committed workspace lock.

A signed kit carries a prebuilt runtime wheelhouse. A source deployment has no such artifact, so
the workstation builds the snapshot's pure-Python workspace wheels, exports the committed
``uv.lock`` closure as hashed requirements, and transfers both as one digest-bound archive. The
managed host installs the third-party closure by hash and then the workspace wheels by hash
without any index or build step, so no unpinned build backend ever runs on the host.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)
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
INPUT_NAME = "source-runtime-support.tar"
_RECEIPT = "runtime-support-installation.json"
_SCHEMA = "fdai.source-runtime-support-installation.v2"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_REQUIREMENTS = 4 * 1024 * 1024
_MAX_ARCHIVE = 256 * 1024 * 1024
_WHEEL = re.compile(r"(?P<name>[A-Za-z0-9_.]+)-(?P<version>[^-]+)-py3-none-any\.whl")


def prepare_runtime_support_input(source_tree: Path, prepared_root: Path) -> str:
    """Write the digest-bound runtime support archive and return its SHA-256 digest."""
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise ValueError("source deployment requires uv to prepare runtime support")
    versions = _workspace_versions(source_tree)
    with tempfile.TemporaryDirectory(prefix=".runtime-support-", dir=prepared_root) as scratch:
        root = Path(scratch)
        requirements = _export_requirements(uv, source_tree, root / "uv-cache")
        # Build from a private copy so the verified snapshot is never written.
        tree = root / "tree"
        shutil.copytree(source_tree, tree, symlinks=True)
        wheels = root / "wheels"
        wheels.mkdir(mode=0o700)
        members: dict[str, bytes] = {"requirements.txt": requirements}
        pins = []
        for name in WORKSPACE_PACKAGES:
            _run(
                (uv, "build", "--wheel", "--package", name, "--out-dir", str(wheels), "--quiet"),
                tree,
                600,
                "workspace wheel build",
            )
        for name, version in versions.items():
            wheel = _single_wheel(wheels, name, version)
            content = wheel.read_bytes()
            members[f"wheels/{wheel.name}"] = content
            pins.append(f"{name}=={version} --hash=sha256:{hashlib.sha256(content).hexdigest()}")
        members["workspace.txt"] = ("\n".join(pins) + "\n").encode()
        archive = _deterministic_tar(members)
    destination = prepared_root / INPUT_NAME
    destination.unlink(missing_ok=True)
    write_private_bytes(destination, archive)
    return hashlib.sha256(archive).hexdigest()


def _export_requirements(uv: str, source_tree: Path, cache: Path) -> bytes:
    packages = tuple(argument for name in WORKSPACE_PACKAGES for argument in ("--package", name))
    try:
        result = subprocess.run(
            (
                uv,
                "export",
                "--directory",
                str(source_tree),
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
    content = result.stdout
    if result.returncode != 0 or not content or len(content) > _MAX_REQUIREMENTS:
        raise ValueError("locked runtime closure export failed")
    _validate_requirements(content)
    return content


def _single_wheel(directory: Path, name: str, version: str) -> Path:
    normalized = name.replace("-", "_")
    matches = [
        path
        for path in directory.iterdir()
        if (match := _WHEEL.fullmatch(path.name)) is not None
        and match["name"] == normalized
        and match["version"] == version
    ]
    if len(matches) != 1 or not matches[0].is_file() or matches[0].is_symlink():
        raise ValueError(f"workspace package {name} did not build one pure-Python wheel")
    return matches[0]


def _deterministic_tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(members[name])
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(members[name]))
    return buffer.getvalue()


def _read_input(archive: Path, digest: str) -> dict[str, bytes]:
    content = read_private_bytes(archive, max_bytes=_MAX_ARCHIVE)
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("source runtime support input differs from the transferred digest")
    members: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as bundle:
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                allowed = path.as_posix() in {"requirements.txt", "workspace.txt"} or (
                    len(path.parts) == 2
                    and path.parts[0] == "wheels"
                    and _WHEEL.fullmatch(path.parts[1]) is not None
                )
                if not member.isreg() or not allowed or member.name in members:
                    raise ValueError("source runtime support input member is invalid")
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise ValueError("source runtime support input member is invalid")
                members[member.name] = extracted.read()
    except tarfile.TarError as exc:
        raise ValueError("source runtime support input is invalid") from exc
    if "requirements.txt" not in members or "workspace.txt" not in members:
        raise ValueError("source runtime support input is incomplete")
    return members


def _validate_pins(content: bytes, members: dict[str, bytes], expected: dict[str, str]) -> None:
    lines = content.decode("utf-8").splitlines()
    pins = {}
    for line in lines:
        match = re.fullmatch(r"([a-z0-9-]+)==(\S+) --hash=sha256:([0-9a-f]{64})", line)
        if match is None or match[1] in pins:
            raise ValueError("source runtime workspace pins are invalid")
        pins[match[1]] = (match[2], match[3])
    wheel_digests = {
        hashlib.sha256(value).hexdigest()
        for name, value in members.items()
        if name != "workspace.txt"
    }
    if {name: version for name, (version, _) in pins.items()} != expected or any(
        digest not in wheel_digests for _, digest in pins.values()
    ):
        raise ValueError("source runtime workspace pins differ from the snapshot")


def install_source_runtime_support(
    work_dir: Path,
    *,
    source_root: Path,
    archive: Path,
    archive_digest: str,
    snapshot_digest: str,
) -> None:
    """Install the hashed lock closure, then the hashed workspace wheels, and verify them."""
    if _DIGEST.fullmatch(archive_digest) is None or _DIGEST.fullmatch(snapshot_digest) is None:
        raise ValueError("source runtime support binding is invalid")
    members = _read_input(archive, archive_digest)
    _validate_requirements(members["requirements.txt"])
    expected = _workspace_versions(source_root)
    _validate_pins(members["workspace.txt"], members, expected)
    environment = work_dir / "runtime-venv"
    receipt_path = work_dir / _RECEIPT
    if _retained_matches(
        environment,
        receipt_path,
        snapshot_digest=snapshot_digest,
        input_digest=archive_digest,
        expected=expected,
        work_dir=work_dir,
    ):
        return
    # The environment is disposable tooling; any partial or stale one is rebuilt.
    receipt_path.unlink(missing_ok=True)
    for stale in (environment, work_dir / "runtime-support-input"):
        if stale.is_symlink() or stale.is_file():
            stale.unlink()
        elif stale.exists():
            shutil.rmtree(stale)
    unpacked = work_dir / "runtime-support-input"
    (unpacked / "wheels").mkdir(mode=0o700, parents=True)
    unpacked.chmod(0o700)
    for name, content in members.items():
        write_private_bytes(unpacked / name, content)
    _run((sys.executable, "-m", "venv", str(environment)), work_dir, 120, "environment creation")
    pip = str(environment / "bin/pip")
    base = (pip, "install", "--no-cache-dir", "--disable-pip-version-check", "--require-hashes")
    _run(
        (*base, "--only-binary", ":all:", "--requirement", str(unpacked / "requirements.txt")),
        work_dir,
        1200,
        "locked dependency installation",
    )
    _run(
        (
            *base,
            "--no-index",
            "--no-deps",
            "--only-binary",
            ":all:",
            "--find-links",
            str(unpacked / "wheels"),
            "--requirement",
            str(unpacked / "workspace.txt"),
        ),
        work_dir,
        600,
        "workspace package installation",
    )
    write_private_output(
        receipt_path,
        json.dumps(
            {
                "schema_version": _SCHEMA,
                "snapshot_digest": snapshot_digest,
                "input_digest": archive_digest,
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
    input_digest: str,
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
            and receipt.get("input_digest") == input_digest
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
