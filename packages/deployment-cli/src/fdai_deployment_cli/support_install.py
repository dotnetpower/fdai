"""Install an isolated deployment-support interpreter from authenticated local wheels."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.offline_kit import (
    _copy_verified_file,
    _read_regular,
    verify_offline_kit,
)
from fdai_deployment_cli.private_output import _open_private_parent, write_private_output

_PREFIX = "support/python/"
_REQUIREMENT = re.compile(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.!+-]+")
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
_RUNTIME_PACKAGES = {
    "fdai-service-contracts",
    "fdai-core-control-plane",
    "fdai-operator-service",
    "fdai-document-ingestion-api",
    "fdai-document-processing-worker",
    "fdai-isolated-executor-service",
}


class SupportInstallationError(ValueError):
    """An authenticated support payload cannot be installed or verified."""


def _package_versions(
    inventory: dict[str, object], requirements: bytes, digests: dict[str, str]
) -> dict[str, str]:
    runtime = inventory.get("packages")
    support = inventory.get("support_packages")
    if not isinstance(runtime, dict) or set(runtime) != _RUNTIME_PACKAGES:
        raise ValueError("support inventory MUST include every runtime distribution")
    if not isinstance(support, dict) or not set(support) <= {"fdai-github-app-auth"}:
        raise ValueError("support inventory contains unsupported workspace dependencies")
    lines = set(requirements.decode("utf-8").splitlines())
    versions: dict[str, str] = {}
    for name, record in {**runtime, **support}.items():
        if not isinstance(record, dict):
            raise SupportInstallationError("support package record is invalid")
        version, wheel = record.get("version"), record.get("wheel")
        if not isinstance(version, str) or not isinstance(wheel, str):
            raise SupportInstallationError("support package version and wheel MUST be declared")
        digest = digests.get(_PREFIX + wheel)
        if digest is None or f"{name}=={version} --hash=sha256:{digest}" not in lines:
            raise ValueError(
                "support requirements do not pin every owned wheel to its signed digest"
            )
        versions[name] = version
    return versions


def _verify_installed_packages(content: bytes, expected: dict[str, str]) -> None:
    if len(content) > 1024 * 1024:
        raise ValueError("installed package readback exceeds its size limit")
    entries = json.loads(content)
    if not isinstance(entries, list):
        raise SupportInstallationError("installed package readback is invalid")
    observed: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SupportInstallationError("installed package entry is invalid")
        name, version = entry.get("name"), entry.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise SupportInstallationError("installed package identity is invalid")
        normalized = re.sub(r"[-_.]+", "-", name.lower())
        if normalized in observed:
            raise ValueError("installed package readback contains duplicate distributions")
        observed[normalized] = version
    if any(observed.get(name) != version for name, version in expected.items()):
        raise ValueError("installed runtime packages do not match the signed inventory")


def _validate_requirements(content: bytes) -> None:
    """Refuse editable, source, index, local-path, and direct-URL requirements."""
    for raw in content.decode("utf-8").splitlines():
        line = raw.strip().rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        if _HASH.fullmatch(line):
            continue
        if (
            _REQUIREMENT.match(line) is None
            or "@" in line
            or "://" in line
            or re.search(r"--(?!hash=sha256:)", line)
        ):
            raise ValueError(
                "support requirements MUST contain only pinned hashed wheel requirements"
            )


def install_support(
    kit: Path,
    *,
    work_dir: Path,
    release_root_pem: bytes,
    cli_version: str,
    platform_tag: str,
) -> dict[str, object]:
    """Install support libraries, never runtime services, into a new private workdir.

    Keys come from the caller's independently trusted verification boundary.
    Installation disables index access, downloads, source builds and caches.
    A failed installation retains its private workspace without a success receipt;
    it is never resumed by reusing an existing environment or running Azure.
    """
    started = time.monotonic()
    parent = _open_private_parent(work_dir / "support-installation.json")
    os.close(parent)
    if any(work_dir.iterdir()):
        raise ValueError("support installation requires an empty private work directory")
    verification = verify_offline_kit(
        kit, release_root_pem=release_root_pem, cli_version=cli_version, platform_tag=platform_tag
    )
    digests = dict(verification.file_digests)
    sizes = dict(verification.file_sizes)
    inventory_path = _PREFIX + "inventory.json"
    requirements_path = _PREFIX + "requirements/support.txt"
    if inventory_path not in digests or requirements_path not in digests:
        raise ValueError("offline kit lacks the complete runtime support wheelhouse")
    wheels = work_dir / "wheelhouse"
    wheels.mkdir(mode=0o700)
    for relative in sorted(name for name in digests if name.startswith(_PREFIX)):
        if time.monotonic() - started > 600:
            raise ValueError("support installation preparation deadline exceeded")
        target = wheels / relative.removeprefix(_PREFIX)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _copy_verified_file(
            kit / relative, target, expected_digest=digests[relative], expected_size=sizes[relative]
        )
    inventory_bytes = _read_regular(wheels / "inventory.json", 4 * 1024 * 1024)
    inventory = load_json_object(
        inventory_bytes, label="support inventory", max_bytes=4 * 1024 * 1024
    )
    if (
        inventory.get("schema_version") != "fdai.runtime-wheelhouse.v1"
        or inventory.get("artifact_kind") != "local-runtime-wheelhouse"
        or inventory.get("status") != "complete"
        or inventory.get("support_requirements") != "requirements/support.txt"
    ):
        raise ValueError("unsupported or incomplete runtime support inventory")
    if inventory.get("files") != {
        name.removeprefix(_PREFIX): digest
        for name, digest in digests.items()
        if name.startswith(_PREFIX) and name != inventory_path
    }:
        raise ValueError("support inventory file map does not match the signed kit")
    requirements = wheels / "requirements/support.txt"
    requirement_bytes = _read_regular(requirements, 4 * 1024 * 1024)
    _validate_requirements(requirement_bytes)
    versions = _package_versions(inventory, requirement_bytes, digests)
    locations = sorted(
        {
            str((wheels / name.removeprefix(_PREFIX)).parent)
            for name in digests
            if name.startswith(_PREFIX) and name.endswith(".whl")
        }
    )
    if not 1 <= len(locations) <= 64:
        raise ValueError("runtime support inventory MUST contain 1 through 64 wheel directories")
    executable = shutil.which("uv")
    if executable is None:
        raise ValueError("a trusted preinstalled uv executable is required")
    environment = {
        key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT") if key in os.environ
    }
    environment.update({"UV_OFFLINE": "1", "UV_NO_CACHE": "1", "UV_PYTHON_DOWNLOADS": "never"})
    venv = work_dir / "support-env"

    def run(arguments: list[str], stage: str, *, capture: bool = False) -> bytes:
        remaining = 900 - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("support installation deadline exceeded")
        print(json.dumps({"stage": stage, "status": "running"}), file=sys.stderr, flush=True)
        try:
            completed = subprocess.run(
                [executable, *arguments],
                env=environment,
                cwd=work_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=min(300, remaining),
                umask=0o077,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"support installation {stage} timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                f"support installation {stage} failed with exit code {exc.returncode}"
            ) from exc
        if capture and not isinstance(completed.stdout, bytes):
            raise SupportInstallationError("support installation returned no package readback")
        print(json.dumps({"stage": stage, "status": "completed"}), file=sys.stderr, flush=True)
        return completed.stdout if capture else b""

    run(["venv", "--no-config", "--offline", "--python", sys.executable, str(venv)], "venv")
    python = str(venv / "bin/python")
    links = [argument for location in locations for argument in ("--find-links", location)]
    run(
        [
            "pip",
            "install",
            "--no-config",
            "--offline",
            "--no-cache",
            "--no-index",
            "--only-binary",
            ":all:",
            "--require-hashes",
            "--python",
            python,
            *links,
            "--requirements",
            str(requirements),
        ],
        "install",
    )
    run(["pip", "check", "--no-config", "--offline", "--python", python], "dependency-check")
    observed = run(
        ["pip", "list", "--no-config", "--offline", "--python", python, "--format", "json"],
        "package-readback",
        capture=True,
    )
    _verify_installed_packages(observed, versions)
    result = {
        "schema_version": "fdai.support-installation.v1",
        "offline_manifest_digest": verification.manifest_digest,
        "inventory_digest": hashlib.sha256(inventory_bytes).hexdigest(),
        "environment": "support-env",
        "dependencies_verified": True,
        "packages": versions,
        "services_started": False,
        "cloud_mutation_performed": False,
        "subscription_ready": False,
    }
    write_private_output(
        work_dir / "support-installation.json",
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return result
