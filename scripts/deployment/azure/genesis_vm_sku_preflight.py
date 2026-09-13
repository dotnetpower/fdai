"""Bind actual VM discovery to new Foundation inputs and exact host preflight."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from genesis_checks import CheckError
from genesis_runner_image_sku_probe import read_vm_skus, read_vm_usage
from genesis_runner_image_skus import EVIDENCE_INVALID
from genesis_subprocess import run_with_heartbeat
from genesis_vm_image_requirements import image_requirements
from genesis_vm_sku_catalog import read_vm_catalog
from genesis_vm_sku_choice import catalog_options, choose_deployment_vms, require_foundation_vm
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
    """Read the hardware policy from the caller-authenticated source or signed bundle."""
    path = repository_root / "infra/genesis-runner-image" / POLICY_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
        raise CheckError(EVIDENCE_INVALID, 3)
    return parse_vm_policy(path.read_bytes())


def discover_foundation_vm_size(
    *,
    repository_root: Path,
    subscription_id: str,
    region: str,
    evidence_directory: Path | None,
    source_commit: str,
    target_binding: str,
    capture: Callable[..., str] | None = None,
) -> str:
    """Choose all three new roles before other discovery; persist only private replay evidence.

    Only the host value enters Foundation variables. Image planning freshly selects its pair
    while preserving this host, binding all three roles to the image approval review.
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
    rows = read_vm_catalog(**context)
    usages = read_vm_usage(**context)
    folder: Path | None = None
    if evidence_directory is not None:
        folder = Path(tempfile.mkdtemp(prefix="vm-discovery-", dir=evidence_directory))
        write_plan_input(folder / "skus.json", {"rows": rows})
        write_plan_input(folder / "quota.json", {"rows": usages})
    try:
        selected = choose_deployment_vms(policy, region=region, rows=rows, usages=usages)
    except CheckError as exc:
        if folder is not None:
            try:
                options = catalog_options(policy, region=region, rows=rows)
            except CheckError:
                options = None
            write_plan_input(
                folder / "result.json",
                {
                    "schema_version": "fdai.deployment-vm-discovery.v1",
                    "state": "blocked",
                    "reason_code": exc.reason_code,
                    "catalog_count": len(rows),
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
                    "sku_evidence_digest": canonical_digest({"rows": rows}),
                    "quota_evidence_digest": canonical_digest({"rows": usages}),
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
                "runner_vm_size": selected.foundation.size,
                "build_vm_size": selected.builder.size,
                "verify_vm_size": selected.verifier.size,
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
    return selected.foundation.size


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


def capture_vm_metadata(
    command: list[str], *, cwd: Path, env: Mapping[str, str], timeout: int, reason: str
) -> str:
    """Run a bounded fixed read command with no provider-error values in failures."""
    try:
        result = run_with_heartbeat(
            command, cwd=cwd, env=env, timeout=timeout, capture_output=True, umask=0o077
        )
    except (OSError, subprocess.SubprocessError):
        raise CheckError(reason, 3) from None
    if result.returncode != 0:
        raise CheckError(reason, 3)
    return result.stdout


def _environment() -> dict[str, str]:
    azure = Path(os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))).resolve(
        strict=True
    )
    if not azure.is_dir() or azure.stat().st_mode & 0o022:
        raise CheckError(EVIDENCE_INVALID, 3)
    return {
        "AZURE_CONFIG_DIR": str(azure),
        "HOME": str(azure.parent),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
