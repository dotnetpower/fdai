"""Bind actual VM discovery to new Foundation inputs and exact host preflight."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from genesis_checks import CheckError, trusted_tool
from genesis_runner_image_sku_probe import read_vm_skus, read_vm_usage
from genesis_runner_image_skus import EVIDENCE_INVALID, load_sku_json
from genesis_subprocess import run_with_heartbeat
from genesis_vm_image_requirements import image_requirements
from genesis_vm_sku_catalog import read_vm_catalog
from genesis_vm_sku_choice import (
    catalog_options,
    choose_deployment_vms,
    choose_foundation_vm,
    require_foundation_vm,
)
from genesis_vm_sku_policy import VmPolicy, parse_vm_policy

POLICY_NAME = "vm-sku-policy.json"


class VmReadContext(TypedDict):
    """The exact target and trusted capture shared by bounded catalog and quota reads."""

    subscription_id: str
    region: str
    azure_cli: Path
    capture: Callable[..., str]
    cwd: Path
    environment: Mapping[str, str]


def load_vm_policy(repository_root: Path) -> VmPolicy:
    """Read a bounded, stable policy descriptor from caller-authenticated source or bundle.

    No-follow and nonblocking open prevent check/open replacement from following links or
    waiting on a special file. This checks file integrity, not source-signing authority.
    """
    path = repository_root / "infra/genesis-runner-image" / POLICY_NAME
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_mode & 0o022
                or not 0 < before.st_size <= 16_384
            ):
                raise CheckError(EVIDENCE_INVALID, 3)
            raw = stream.read(16_385)
            after = os.fstat(stream.fileno())
            if (
                len(raw) != before.st_size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                raise CheckError(EVIDENCE_INVALID, 3)
    except OSError:
        raise CheckError(EVIDENCE_INVALID, 3) from None
    return parse_vm_policy(raw)


def discover_foundation_vm_size(
    *,
    repository_root: Path,
    subscription_id: str,
    region: str,
    evidence_directory: Path | None,
    source_commit: str,
    target_binding: str,
    capture: Callable[..., str] | None = None,
    create_runner_image: bool = True,
) -> str:
    """Choose required deployment hosts before other discovery and retain private evidence.

    Connected deployment selects only the Foundation host. Offline image creation also reserves
    compatible builder and verifier choices before its separate approval review.
    """
    policy = load_vm_policy(repository_root)
    context: VmReadContext = {
        "subscription_id": subscription_id,
        "region": region,
        "azure_cli": Path("/usr/bin/az"),
        "capture": capture or capture_vm_metadata,
        "cwd": repository_root,
        "environment": _environment(),
    }
    folder: Path | None = None
    if evidence_directory is not None:
        folder = Path(tempfile.mkdtemp(prefix="vm-discovery-", dir=evidence_directory))
    rows: list[object] | None = None
    usages: list[object] | None = None
    stage = "catalog"
    try:
        rows = read_vm_catalog(**context)
        if folder is not None:
            write_plan_input(folder / "skus.json", {"rows": rows})
        stage = "quota"
        usages = read_vm_usage(**context)
        if folder is not None:
            write_plan_input(folder / "quota.json", {"rows": usages})
        stage = "selection"
        if create_runner_image:
            selected = choose_deployment_vms(policy, region=region, rows=rows, usages=usages)
            runner_vm_size = selected.foundation.size
            build_vm_size: str | None = selected.builder.size
            verify_vm_size: str | None = selected.verifier.size
        else:
            host = choose_foundation_vm(policy, region=region, rows=rows, usages=usages)
            runner_vm_size = host.size
            build_vm_size = None
            verify_vm_size = None
    except CheckError as exc:
        if folder is not None:
            try:
                options = catalog_options(policy, region=region, rows=rows) if rows else None
            except CheckError:
                options = None
            write_plan_input(
                folder / "result.json",
                {
                    "schema_version": "fdai.deployment-vm-discovery.v1",
                    "state": "blocked",
                    "reason_code": exc.reason_code,
                    "failed_stage": stage,
                    "catalog_count": len(rows) if rows is not None else None,
                    "restricted_count": options.restricted if options else None,
                    "excluded_count": options.excluded if options else None,
                    "role_candidate_counts": (
                        {
                            "builder": len(options.builder),
                            "verifier": len(options.verifier),
                            "foundation": len(options.foundation),
                        }
                        if options
                        else None
                    ),
                    "source_commit": source_commit,
                    "target_binding": target_binding,
                    "region": region,
                    "policy_digest": policy.digest,
                    "sku_evidence_digest": (
                        canonical_digest({"rows": rows}) if rows is not None else None
                    ),
                    "quota_evidence_digest": (
                        canonical_digest({"rows": usages}) if usages is not None else None
                    ),
                    "checked_at": datetime.now(
                        timezone.utc  # noqa: UP017 - Python 3.10 entrypoint
                    ).isoformat(),
                    "mutation_performed": False,
                    "capacity_reserved": False,
                },
            )
        raise
    if folder is not None:
        write_plan_input(
            folder / "result.json",
            {
                "schema_version": "fdai.deployment-vm-discovery.v1",
                "state": "selected",
                "source_commit": source_commit,
                "target_binding": target_binding,
                "region": region,
                "runner_vm_size": runner_vm_size,
                "build_vm_size": build_vm_size,
                "verify_vm_size": verify_vm_size,
                "runner_image_creation": create_runner_image,
                "policy_digest": policy.digest,
                "sku_evidence_digest": canonical_digest({"rows": rows}),
                "quota_evidence_digest": canonical_digest({"rows": usages}),
                "checked_at": datetime.now(
                    timezone.utc  # noqa: UP017 - Python 3.10 entrypoint
                ).isoformat(),
                "mutation_performed": False,
                "capacity_reserved": False,
            },
        )
    return str(runner_vm_size)


def recheck_foundation_vm(
    *,
    repository_root: Path,
    variables_file: Path,
    evidence_directory: Path,
    capture: Callable[..., str] | None = None,
) -> None:
    """Recheck a sealed host and actual image disk before a new plan or claim.

    Never invoke for an already-claimed effect. Managed images and exact gallery versions need
    independent metadata; a missing size or unsupported shape cannot mean the default 64 GiB.
    """
    policy = load_vm_policy(repository_root)
    values = read_plan_input(variables_file)
    region, subscription = str(values.get("region", "")), str(values.get("subscription_id", ""))
    size = values.get("runner_vm_size")
    image = values.get("runner_source_image_id")
    mode = values.get("runner_bootstrap_mode", "offline")
    version = values.get("runner_marketplace_image_version", "")
    if not isinstance(size, str) or not isinstance(image, str):
        raise CheckError(EVIDENCE_INVALID, 3)
    reader = capture or capture_vm_metadata
    environment = _environment()
    context: VmReadContext = {
        "subscription_id": subscription,
        "region": region,
        "azure_cli": Path("/usr/bin/az"),
        "capture": reader,
        "cwd": repository_root,
        "environment": environment,
    }
    rows = read_vm_skus((size,), **context)
    usages = read_vm_usage(**context)
    if mode == "online":
        observed = _marketplace_image_requirements(
            version=version,
            region=region,
            capture=reader,
            cwd=repository_root,
            environment=environment,
        )
        disk = policy.os_disk_gib
    else:
        observed = image_requirements(
            image=image,
            subscription_id=subscription,
            region=region,
            capture=reader,
            cwd=repository_root,
            environment=environment,
        )
        disk = observed.get("diskSizeGB")
        if type(disk) is not int:
            raise CheckError(EVIDENCE_INVALID, 3)
    require_foundation_vm(
        policy, region=region, rows=rows, usages=usages, size=size, image_disk_gib=disk
    )
    folder = Path(tempfile.mkdtemp(prefix="host-sku-check-", dir=evidence_directory))
    write_plan_input(
        folder / "evidence.json",
        {
            "rows": rows,
            "quota_rows": usages,
            "image_requirements": observed,
            "policy_digest": policy.digest,
            "checked_at": datetime.now(
                timezone.utc  # noqa: UP017 - Python 3.10 entrypoint
            ).isoformat(),
            "runner_vm_size": size,
            "mutation_performed": False,
            "capacity_reserved": False,
        },
    )


def _marketplace_image_requirements(
    *,
    version: object,
    region: str,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> dict[str, object]:
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) is None:
        raise CheckError(EVIDENCE_INVALID, 3)
    raw = capture(
        [
            "/usr/bin/az",
            "vm",
            "image",
            "show",
            "--location",
            region,
            "--urn",
            f"Canonical:ubuntu-24_04-lts:server:{version}",
            "--query",
            (
                "{version:name,location:location,"
                "osType:osDiskImage.operatingSystem,"
                "hyperVGeneration:hyperVGeneration}"
            ),
            "--output",
            "json",
            "--only-show-errors",
        ],
        cwd=cwd,
        env=environment,
        timeout=30,
        reason=EVIDENCE_INVALID,
    )
    observed = load_sku_json(raw.encode("utf-8"), max_bytes=65_536)
    if (
        observed.get("version") != version
        or str(observed.get("location", "")).casefold() != region.casefold()
        or observed.get("osType") != "Linux"
        or observed.get("hyperVGeneration") != "V2"
    ):
        raise CheckError(EVIDENCE_INVALID, 3)
    return {
        "marketplaceVersion": version,
        "location": region,
        "osType": "Linux",
        "hyperVGeneration": "V2",
    }


def capture_vm_metadata(
    command: list[str], *, cwd: Path, env: Mapping[str, str], timeout: int, reason: str
) -> str:
    """Run a bounded fixed read command with no provider-error values in failures."""
    if command and command[0] == "/usr/bin/az":
        command = [trusted_tool("az"), *command[1:]]
    try:
        result = run_with_heartbeat(
            command, cwd=cwd, env=env, timeout=timeout, capture_output=True, umask=0o077
        )
    except (OSError, subprocess.SubprocessError):
        raise CheckError(reason, 3) from None
    if result.returncode != 0:
        raise CheckError(reason, 3)
    return str(result.stdout)


def _environment() -> dict[str, str]:
    """Resolve the selected CLI context without exposing private paths on read failure."""
    try:
        azure = Path(os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))).resolve(
            strict=True
        )
        if not azure.is_dir() or azure.stat().st_mode & 0o022:
            raise CheckError(EVIDENCE_INVALID, 3)
    except OSError:
        raise CheckError(EVIDENCE_INVALID, 3) from None
    return {
        "AZURE_CONFIG_DIR": str(azure),
        "HOME": str(azure.parent),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
