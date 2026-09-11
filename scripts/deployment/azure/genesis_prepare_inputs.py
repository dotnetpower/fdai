#!/usr/bin/env python3
"""Derive secret-free, target-bound Foundation inputs for Azure Genesis."""

from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import re
import subprocess
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest


def foundation_values(
    *,
    repository_root: Path,
    source_commit: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    target_binding: str,
    run_binding: str,
    ssh_public_key: str,
) -> dict[str, object]:
    """Resolve independent exact image, unique name, and network inputs concurrently."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        version_future = executor.submit(
            _capture,
            (
                "az",
                "vm",
                "image",
                "show",
                "--location",
                region,
                "--urn",
                "Canonical:ubuntu-24_04-lts:server:latest",
                "--query",
                "name",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
        account_future = executor.submit(
            state_account_name,
            repository_root=repository_root,
            target_binding=target_binding,
            source_commit=source_commit,
        )
        network_future = executor.submit(network_layout, repository_root)
        version = version_future.result()
        account_name = account_future.result()
        ops, runner, endpoint, bastion = network_future.result()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) is None:
        raise ValueError("Azure Marketplace image version is not exact")
    toolchain = json.loads(
        (repository_root / "infra/genesis-runner-image/toolchain.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "fdai.genesis-runner-image.v1",
        "source_commit": source_commit,
        "source_image_version": version,
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    toolchain_digest = canonical_digest(manifest)
    context_digest = canonical_digest(
        {
            "target_binding": target_binding,
            "source_commit": source_commit,
            "region": region,
            "environment": "dev",
            "run_digest": run_binding,
        }
    )
    return {
        "tenant_id": tenant_id,
        "subscription_id": subscription_id,
        "target_binding": target_binding,
        "workload": "fdai",
        "region": region,
        "region_short": region[:3],
        "state_storage_account_name": account_name,
        "state_retention_days": 30,
        "ops_address_space": str(ops),
        "runner_subnet_prefix": str(runner),
        "pe_subnet_prefix": str(endpoint),
        "enable_bastion": True,
        "bastion_subnet_prefix": str(bastion),
        "enable_public_egress": True,
        "runner_ssh_public_key": ssh_public_key,
        "runner_parallelism": 1,
        "runner_source_image_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-fdai-image-pending/"
            "providers/Microsoft.Compute/images/fdai-runner-pending"
        ),
        "runner_image_toolchain_digest": toolchain_digest,
        "runner_vm_size": "Standard_D4ds_v5",
        "source_commit": source_commit,
        "run_digest": run_binding,
        "foundation_context_digest": context_digest,
    }


def state_account_name(*, repository_root: Path, target_binding: str, source_commit: str) -> str:
    """Select one deterministic globally available state-account name."""

    for index in range(32):
        candidate = (
            "stfdai"
            + hashlib.sha256(f"{target_binding}:{source_commit}:{index}".encode()).hexdigest()[:18]
        )[:24]
        available = _capture(
            (
                "az",
                "storage",
                "account",
                "check-name",
                "--name",
                candidate,
                "--query",
                "nameAvailable",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
        if available.casefold() == "true":
            return candidate
    raise ValueError("no deterministic Foundation state account name is available")


def network_layout(
    repository_root: Path,
) -> tuple[
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
]:
    """Select a reviewed operations CIDR from concurrent Azure and local route reads."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        vnets_future = executor.submit(
            _capture,
            (
                "az",
                "network",
                "vnet",
                "list",
                "--query",
                "[].addressSpace.addressPrefixes",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
        routes_future = executor.submit(
            _capture,
            ("ip", "-j", "-4", "route", "show"),
            cwd=repository_root,
        )
        vnets = json.loads(vnets_future.result())
        routes = json.loads(routes_future.result())
    used: list[ipaddress.IPv4Network] = []
    for group in vnets:
        for value in group or []:
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError:
                continue
            if isinstance(network, ipaddress.IPv4Network):
                used.append(network)
    for row in routes:
        value = row.get("dst") if isinstance(row, dict) else None
        if value and value != "default":
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError:
                continue
            if isinstance(network, ipaddress.IPv4Network):
                used.append(network)
    candidates = (
        "172.29.0.0/16",
        "172.30.0.0/16",
        "10.237.0.0/16",
        "10.238.0.0/16",
    )
    ops: ipaddress.IPv4Network | None = next(
        (
            ipaddress.ip_network(candidate)
            for candidate in candidates
            if not any(ipaddress.ip_network(candidate).overlaps(current) for current in used)
        ),
        None,
    )
    if ops is None:
        raise ValueError("no non-overlapping reviewed operations network is available")
    subnets = list(ops.subnets(new_prefix=24))
    return ops, subnets[1], subnets[2], next(subnets[3].subnets(new_prefix=26))


def _capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError("Genesis input discovery command failed")
    return completed.stdout.strip()
