"""Install verified runtime support from one signed aggregate lock."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.offline_kit import _read_regular as _read_kit_regular
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.standalone_host_state import private_json as _private_json
from fdai_deployment_cli.support_install import (
    _validate_requirements as _validate_support_requirements,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")


def install_runtime_support(
    work_dir: Path, *, artifact_root: Path, kit_manifest_digest: str
) -> None:
    """Install the admitted hashed support lock and verify resumable completion."""

    if _DIGEST.fullmatch(kit_manifest_digest) is None:
        raise ValueError("runtime migration support kit binding is invalid")
    support = artifact_root / "support/python"
    inventory_path = support / "inventory.json"
    requirements = support / "requirements/support.txt"
    try:
        inventory_bytes = _read_kit_regular(inventory_path, 4 * 1024 * 1024)
        requirement_bytes = _read_kit_regular(requirements, 8 * 1024 * 1024)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("runtime migration support contract is unavailable") from exc
    inventory = load_json_object(
        inventory_bytes,
        label="runtime support inventory",
        max_bytes=4 * 1024 * 1024,
    )
    _validate_support_requirements(requirement_bytes)
    if (
        inventory.get("schema_version") != "fdai.runtime-wheelhouse.v1"
        or inventory.get("artifact_kind") != "local-runtime-wheelhouse"
        or inventory.get("status") != "complete"
        or inventory.get("support_requirements") != "requirements/support.txt"
    ):
        raise ValueError("runtime migration support inventory is incomplete")
    files = _mapping(inventory.get("files"), "runtime support file inventory")
    expected_versions: dict[str, str] = {}
    requirement_lines = set(requirement_bytes.decode("utf-8").splitlines())
    for field in ("packages", "support_packages"):
        records = _mapping(inventory.get(field), f"runtime support {field}")
        for name, item in records.items():
            record = _mapping(item, f"runtime support package {name}")
            version, wheel = record.get("version"), record.get("wheel")
            digest = files.get(wheel) if isinstance(wheel, str) else None
            normalized = re.sub(r"[-_.]+", "-", name.casefold())
            if (
                not normalized
                or not isinstance(version, str)
                or not isinstance(wheel, str)
                or not isinstance(digest, str)
                or _DIGEST.fullmatch(digest) is None
                or f"{name}=={version} --hash=sha256:{digest}" not in requirement_lines
                or normalized in expected_versions
            ):
                raise ValueError("runtime migration support package contract is invalid")
            expected_versions[normalized] = version
    wheels = sorted(support.rglob("*.whl"))
    if not wheels or any(not wheel.is_file() or wheel.is_symlink() for wheel in wheels):
        raise ValueError("runtime migration support wheelhouse is invalid")
    locations = sorted({wheel.parent for wheel in wheels}, key=str)
    if not 1 <= len(locations) <= 64:
        raise ValueError("runtime migration support wheel locations are invalid")

    environment = work_dir / "runtime-venv"
    receipt_path = work_dir / "runtime-support-installation.json"
    retained_environment = environment.exists() or environment.is_symlink()
    retained_receipt = receipt_path.exists() or receipt_path.is_symlink()
    if retained_environment or retained_receipt:
        if not retained_environment or not retained_receipt:
            raise ValueError("runtime migration support installation is incomplete")
        receipt = _private_json(receipt_path, "runtime support installation receipt")
        if (
            receipt.get("schema_version") != "fdai.runtime-support-installation.v1"
            or receipt.get("kit_manifest_digest") != kit_manifest_digest
            or receipt.get("inventory_digest") != hashlib.sha256(inventory_bytes).hexdigest()
            or receipt.get("requirements_digest") != hashlib.sha256(requirement_bytes).hexdigest()
            or receipt.get("dependencies_verified") is not True
        ):
            raise ValueError("runtime migration support receipt differs")
        readback_digest = _runtime_support_readback(
            environment, expected_versions=expected_versions, work_dir=work_dir
        )
        if receipt.get("package_readback_digest") != readback_digest:
            raise ValueError("runtime migration support package readback differs")
        return

    _run(
        (sys.executable, "-m", "venv", str(environment)),
        cwd=work_dir,
        timeout=120,
        reason="runtime migration environment creation failed",
    )
    links = tuple(
        argument for location in locations for argument in ("--find-links", str(location))
    )
    _run(
        (
            str(environment / "bin/pip"),
            "install",
            "--no-index",
            "--no-cache-dir",
            "--only-binary",
            ":all:",
            "--require-hashes",
            *links,
            "--requirement",
            str(requirements),
        ),
        cwd=work_dir,
        timeout=900,
        reason="runtime migration support installation failed",
    )
    readback_digest = _runtime_support_readback(
        environment, expected_versions=expected_versions, work_dir=work_dir
    )
    write_private_output(
        receipt_path,
        json.dumps(
            {
                "schema_version": "fdai.runtime-support-installation.v1",
                "kit_manifest_digest": kit_manifest_digest,
                "inventory_digest": hashlib.sha256(inventory_bytes).hexdigest(),
                "requirements_digest": hashlib.sha256(requirement_bytes).hexdigest(),
                "package_readback_digest": readback_digest,
                "dependencies_verified": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )


def _runtime_support_readback(
    environment: Path, *, expected_versions: dict[str, str], work_dir: Path
) -> str:
    pip = str(environment / "bin/pip")
    _run(
        (pip, "check"),
        cwd=work_dir,
        timeout=120,
        reason="runtime migration support dependency check failed",
    )
    try:
        entries = json.loads(
            _capture(
                (pip, "list", "--format=json"),
                cwd=work_dir,
                timeout=120,
                reason="runtime migration support package readback failed",
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError("runtime migration support package readback is invalid") from exc
    if not isinstance(entries, list):
        raise ValueError("runtime migration support package readback is invalid")
    observed: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("runtime migration support package readback is invalid")
        name, version = entry.get("name"), entry.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("runtime migration support package readback is invalid")
        normalized = re.sub(r"[-_.]+", "-", name.casefold())
        if normalized in observed:
            raise ValueError("runtime migration support package readback contains duplicates")
        observed[normalized] = version
    if any(observed.get(name) != version for name, version in expected_versions.items()):
        raise ValueError("runtime migration support packages differ from the signed inventory")
    return canonical_digest(observed)


def _run(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError(reason)


def _capture(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


__all__ = ["install_runtime_support"]
