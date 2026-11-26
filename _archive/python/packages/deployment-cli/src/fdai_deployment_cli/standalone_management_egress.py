"""Derive the AKS API server authorized range from the managed host's egress.

The AKS baseline keeps a public API server with authorized IP ranges. Only the managed deployment
host runs Terraform, ``kubectl``, and readback against it, and that host leaves the operations
network through its NAT gateway. The range is therefore the NAT gateway's single public address,
read back from Azure Resource Manager rather than from any external address-echo service.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path


def management_egress_cidrs(context: Mapping[str, object], *, cwd: Path) -> list[str]:
    """Return the one ``/32`` range of the operations NAT gateway, or fail closed."""

    ops_resource_group = str(context["state_resource_group"])
    subscription_id = str(context["subscription_id"])
    listed = _az(
        (
            "network",
            "nat",
            "gateway",
            "list",
            "--resource-group",
            ops_resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "[].publicIpAddresses[].id",
            "--output",
            "json",
        ),
        cwd,
    )
    try:
        addresses = json.loads(listed)
    except json.JSONDecodeError as exc:
        raise ValueError("management NAT gateway readback is invalid") from exc
    if not isinstance(addresses, list) or len(addresses) != 1 or not isinstance(addresses[0], str):
        raise ValueError("management egress requires exactly one NAT gateway public IP")
    raw = _az(
        (
            "network",
            "public-ip",
            "show",
            "--ids",
            addresses[0],
            "--query",
            "ipAddress",
            "--output",
            "tsv",
        ),
        cwd,
    ).strip()
    try:
        address = ipaddress.IPv4Address(raw)
    except ValueError as exc:
        raise ValueError("management NAT gateway public IP is invalid") from exc
    if not address.is_global:
        raise ValueError("management NAT gateway public IP is not globally routable")
    return [f"{address}/32"]


def _az(arguments: tuple[str, ...], cwd: Path) -> str:
    result = subprocess.run(
        ("az", *arguments, "--only-show-errors"),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise ValueError("management egress readback failed")
    return result.stdout


__all__ = ["management_egress_cidrs"]
