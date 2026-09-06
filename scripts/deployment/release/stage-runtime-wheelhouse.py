#!/usr/bin/env python3
"""Stage host-compatible runtime wheels on a connected host, without release approval.

Only build/, requirements/, wheels/, and inventory.json are deliverables. The private
.work/ directory contains isolated build tooling, never an active service environment.
Failures retain partial artifacts for diagnosis but never publish a success inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import stat
import subprocess
import sys
import sysconfig
import time
import tomllib
import zipfile
from collections.abc import Callable, Mapping
from email.parser import BytesParser
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from scripts.deployment.release.secure_work_file import open_work_file, write_work_file
else:
    from secure_work_file import open_work_file, write_work_file

RUNTIME_PACKAGES = {
    "fdai-service-contracts": "packages/service-contracts",
    "fdai-core-control-plane": "services/core-control-plane",
    "fdai-operator-service": "services/operator-service",
    "fdai-document-ingestion-api": "services/document-ingestion-api",
    "fdai-document-processing-worker": "services/document-processing-worker",
    "fdai-isolated-executor-service": "services/isolated-executor",
}
SUPPORT_PACKAGES = {"fdai-github-app-auth": "packages/github-app-auth"}
STAGE_TIMEOUT = 600
TOTAL_TIMEOUT = 3600
_GUARD = runpy.run_path(str(Path(__file__).with_name("workdir-guard.py")))
CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class StagingError(RuntimeError):
    """Staging is incomplete; partial artifacts do not authorize installation."""


def _prepare_output(out: Path, repo: Path) -> None:
    if (
        not out.is_absolute()
        or ".." in out.parts
        or out in {Path("/"), Path.home(), repo}
        or out in repo.parents
    ):
        raise StagingError("--out-dir must be a safe absolute child directory")
    _GUARD["_require_nonreplaceable_parent_chain"](out)
    if not out.exists() and not out.is_symlink():
        out.mkdir(mode=0o700)
    descriptor = _GUARD["_open_owned_directory"](out)
    try:
        if os.listdir(descriptor):
            raise StagingError("--out-dir must be new or empty; existing files are never removed")
    finally:
        os.close(descriptor)


def _packages(repo: Path, lock: bytes) -> dict[str, dict[str, str]]:
    records = tomllib.loads(lock.decode())["package"]
    selected = dict(RUNTIME_PACKAGES)
    packages = {}
    pending = list(selected)
    while pending:
        name = pending.pop(0)
        project = tomllib.loads((repo / selected[name] / "pyproject.toml").read_text())["project"]
        version = project.get("version")
        if not isinstance(version, str) or re.fullmatch(r"[0-9A-Za-z.!+-]{1,128}", version) is None:
            raise StagingError("runtime version must be a single package-version token")
        matches = [entry for entry in records if entry["name"] == name]
        if (
            len(matches) != 1
            or project["name"] != name
            or matches[0]["version"] != project["version"]
            or matches[0]["source"] != {"editable": selected[name]}
        ):
            raise StagingError("runtime project metadata must match its workspace lock entry")
        packages[name] = {"version": project["version"], "project": selected[name]}
        for dependency in matches[0].get("dependencies", []):
            target = dependency["name"]
            local = [
                item
                for item in records
                if item["name"] == target and "editable" in item.get("source", {})
            ]
            if local and target not in selected:
                if target not in SUPPORT_PACKAGES:
                    raise StagingError("runtime closure contains an unsupported workspace package")
                selected[target] = SUPPORT_PACKAGES[target]
                pending.append(target)
    return packages


def _digest(path: Path, check_deadline: Callable[[], float]) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise StagingError("staged artifacts must be single-link regular files")
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            check_deadline()
            checksum.update(chunk)
    return checksum.hexdigest()


def _owned_wheel(directory: Path, name: str, version: str) -> Path:
    files = list(directory.glob("*.whl"))
    if (
        len(files) != 1
        or not stat.S_ISREG(files[0].lstat().st_mode)
        or any(path.name != ".gitignore" and path.suffix != ".whl" for path in directory.iterdir())
    ):
        raise StagingError("each runtime build must produce exactly one wheel")
    with zipfile.ZipFile(files[0]) as archive:
        metadata = [item for item in archive.namelist() if item.endswith(".dist-info/METADATA")]
        if len(metadata) != 1 or archive.getinfo(metadata[0]).file_size > 1024 * 1024:
            raise StagingError("built wheel metadata is missing or exceeds its bound")
        fields = BytesParser().parsebytes(archive.read(metadata[0]))
    if fields["Name"] != name or fields["Version"] != version:
        raise StagingError("built wheel identity must match the locked runtime package")
    return files[0]


def stage_runtime_wheelhouse(
    out_dir: Path,
    repo_root: Path | None = None,
    *,
    runner: CommandRunner | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Build six runtime roots and their required support wheels using committed locks.

    ``runner`` follows subprocess.run's keyword contract; ``clock`` is monotonic.
    Commands have a ten-minute cap within a one-hour total deadline. Outputs are
    exclusive and host-specific. This never signs, publishes, deploys, or grants
    production eligibility. A failed command raises StagingError without retry.
    """
    runner = runner or subprocess.run
    clock = clock or time.monotonic
    deadline = clock() + TOTAL_TIMEOUT

    def remaining() -> float:
        seconds = deadline - clock()
        if seconds <= 0:
            raise StagingError("runtime staging total deadline exceeded")
        return min(STAGE_TIMEOUT, seconds)

    def run(
        args: list[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stdout: int | BinaryIO = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        timeout = remaining()
        print(
            json.dumps({"stage": args[1], "status": "running"}),
            file=sys.stderr,
            flush=True,
        )
        try:
            result = runner(
                args,
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                check=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise StagingError(
                f"runtime staging {args[1]} exceeded its deadline; no inventory"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise StagingError(
                f"runtime staging {args[1]} failed with exit code {exc.returncode}; no inventory"
            ) from exc
        except OSError as exc:
            raise StagingError(f"runtime staging {args[0]} is unavailable; no inventory") from exc
        remaining()
        print(json.dumps({"stage": args[1], "status": "completed"}), file=sys.stderr, flush=True)
        return result

    if repo_root is None:
        result = run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd())
        repo_root = Path(result.stdout.decode().strip())
    repo = repo_root.resolve(strict=True)
    locks = {}
    for relative in ("uv.lock", "packages/deployment-cli/uv.lock"):
        committed = run(["git", "show", f"HEAD:{relative}"], cwd=repo).stdout
        if (repo / relative).read_bytes() != committed:
            raise StagingError("runtime and deployment CLI locks must match committed HEAD")
        locks[relative] = committed
    packages = _packages(repo, locks["uv.lock"])
    _prepare_output(out_dir, repo)
    for relative in ("build", "requirements", "wheels", ".work", ".work/scratch"):
        (out_dir / relative).mkdir(mode=0o700)
    allowed_environment = {
        "PATH",
        "HOME",
        "SYSTEMROOT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "UV_OFFLINE",
        "UV_DEFAULT_INDEX",
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_EXTRA_INDEX_URL",
        "UV_SYSTEM_CERTS",
        "UV_NATIVE_TLS",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed_environment}
    env.update(
        {
            "UV_PROJECT_ENVIRONMENT": str(out_dir / ".work/release-env"),
            "UV_CACHE_DIR": str(out_dir / ".work/uv-cache"),
            "PIP_CACHE_DIR": str(out_dir / ".work/pip-cache"),
            "TMPDIR": str(out_dir / ".work/scratch"),
            "UV_NO_PROGRESS": "1",
            "UV_HTTP_RETRIES": "0",
            "UV_HTTP_TIMEOUT": "30",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    for name, package in packages.items():
        requirements = out_dir / "requirements" / f"{name}.txt"
        build = out_dir / "build" / name
        wheels = out_dir / "wheels" / name
        build.mkdir(mode=0o700)
        wheels.mkdir(mode=0o700)
        with open_work_file(requirements, mode=0o600, replace=False) as output:
            run(
                [
                    "uv",
                    "export",
                    "--locked",
                    "--package",
                    name,
                    "--no-dev",
                    "--no-default-groups",
                    "--no-emit-workspace",
                    "--format",
                    "requirements-txt",
                    "--no-header",
                    "--no-annotate",
                ],
                cwd=repo,
                env=env,
                stdout=output,
            )
        run(
            [
                "uv",
                "build",
                "--wheel",
                "--package",
                name,
                "--out-dir",
                str(build),
                "--python",
                sys.executable,
            ],
            cwd=repo,
            env=env,
            stdout=subprocess.DEVNULL,
        )
        wheel = _owned_wheel(build, name, package["version"])
        run(
            [
                "uv",
                "run",
                "--project",
                "packages/deployment-cli",
                "--locked",
                "--no-dev",
                "--group",
                "release",
                "--python",
                sys.executable,
                "python",
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--require-hashes",
                "--dest",
                str(wheels),
                "--requirement",
                str(requirements),
                "--retries",
                "0",
                "--timeout",
                "30",
            ],
            cwd=repo,
            env=env,
            stdout=subprocess.DEVNULL,
        )
        downloaded = list(wheels.iterdir())
        has_requirements = any(
            line.strip() and not line.lstrip().startswith("#")
            for line in requirements.read_text().splitlines()
        )
        if not downloaded and has_requirements:
            raise StagingError("runtime dependency download produced no wheels")
        if any(path.suffix != ".whl" or not path.is_file() for path in downloaded):
            raise StagingError("dependency download produced a non-wheel artifact")
        package.update(
            {
                "requirements": requirements.relative_to(out_dir).as_posix(),
                "wheel": wheel.relative_to(out_dir).as_posix(),
                "dependency_wheels": wheels.relative_to(out_dir).as_posix(),
            }
        )
    for relative, committed in locks.items():
        if (repo / relative).read_bytes() != committed:
            raise StagingError("lock changed during runtime staging")
    support_requirements = out_dir / "requirements/support.txt"
    requirements_parts = ["# Locked dependencies for the deployment support interpreter.\n"]
    for name, package in packages.items():
        requirements_parts.append((out_dir / package["requirements"]).read_text() + "\n")
        wheel_digest = _digest(out_dir / package["wheel"], remaining)
        requirements_parts.append(f"{name}=={package['version']} --hash=sha256:{wheel_digest}\n")
    write_work_file(
        support_requirements,
        "".join(requirements_parts).encode(),
        mode=0o600,
        replace=False,
    )
    files = {}
    for directory in ("build", "requirements", "wheels"):
        for path in sorted((out_dir / directory).rglob("*")):
            if path.is_symlink():
                raise StagingError("staged artifacts must not contain symlinks")
            if not path.is_dir():
                files[path.relative_to(out_dir).as_posix()] = _digest(path, remaining)
    inventory = {
        "schema_version": "fdai.runtime-wheelhouse.v1",
        "status": "complete",
        "artifact_kind": "local-runtime-wheelhouse",
        "production_release_eligible": False,
        "compatibility": "staging-host-python-and-platform",
        "support_requirements": "requirements/support.txt",
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "platform": sysconfig.get_platform(),
        "packages": {name: packages[name] for name in RUNTIME_PACKAGES},
        "support_packages": {
            name: info for name, info in packages.items() if name not in RUNTIME_PACKAGES
        },
        "lock_sha256": {
            name: hashlib.sha256(content).hexdigest() for name, content in locks.items()
        },
        "files": files,
    }
    remaining()
    write_work_file(
        out_dir / "inventory.json",
        (json.dumps(inventory, indent=2, sort_keys=True) + "\n").encode(),
        mode=0o600,
        replace=False,
    )
    return inventory


def main(argv: list[str] | None = None) -> int:
    """Stage support artifacts only; return nonzero on incomplete or unsafe output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args(argv)
    try:
        stage_runtime_wheelhouse(args.out_dir, args.repo_root)
    except StagingError as exc:
        print(f"runtime wheelhouse staging incomplete: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        print("runtime wheelhouse staging incomplete; no release eligibility", file=sys.stderr)
        return 1
    print(json.dumps({"status": "complete", "production_release_eligible": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
