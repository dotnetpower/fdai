#!/usr/bin/env python3
"""Derive secret-free, target-bound Foundation inputs for Azure Genesis."""

from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest

_AZURE_ROUTE_SERVICE_TAGS = frozenset({"AzureLoadBalancer", "Internet", "None", "VirtualNetwork"})


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
    execution_transport: str = "github-actions",
) -> dict[str, object]:
    """Resolve independent exact image, unique name, and network inputs concurrently."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        version_future = executor.submit(
            _capture,
            (
                "/usr/bin/az",
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
        network_future = executor.submit(
            network_layout, repository_root, subscription_id=subscription_id
        )
        version = version_future.result()
        account_name = account_future.result()
        ops, runner, endpoint, bastion, build, firewall, firewall_management = (
            network_future.result()
        )
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) is None:
        raise ValueError("Azure Marketplace image version is not exact")
    toolchain_path = repository_root / "infra/genesis-runner-image/toolchain.json"
    try:
        toolchain_raw = toolchain_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("runner image toolchain object is unavailable") from exc
    if toolchain_path.is_symlink() or not toolchain_path.is_file():
        raise ValueError("runner image toolchain object is unavailable")
    toolchain = json.loads(toolchain_raw)
    if not isinstance(toolchain, dict):
        raise ValueError("runner image toolchain object is invalid")
    manifest = {
        "schema_version": "fdai.genesis-runner-image.v1",
        "source_commit": source_commit,
        "source_image_version": version,
        **{key: value for key, value in toolchain.items() if key != "schema_version"},
    }
    if execution_transport == "manual":
        manifest["execution_transport"] = "manual"
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
        "build_address_space": str(build),
        "build_subnet_prefix": str(next(build.subnets(new_prefix=26))),
        "firewall_subnet_prefix": str(firewall),
        "firewall_management_subnet_prefix": str(firewall_management),
        "runner_source_image_id": (
            f"/subscriptions/{subscription_id}/resourceGroups/rg-fdai-image-pending/"
            "providers/Microsoft.Compute/images/fdai-runner-pending"
        ),
        "runner_image_toolchain_digest": toolchain_digest,
        "runner_vm_size": "Standard_D4ds_v5",
        "source_commit": source_commit,
        "run_digest": run_binding,
        "execution_transport": execution_transport,
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
                "/usr/bin/az",
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
    repository_root: Path, *, subscription_id: str
) -> tuple[
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
    ipaddress.IPv4Network,
]:
    """Select disjoint reviewed operations and build CIDRs from complete network evidence.

    Default routes describe forwarding, not address-space ownership. Exclude them only from
    route evidence; declared VNet, peer, and gateway ranges remain overlap constraints.
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        vnets_future = executor.submit(
            _capture,
            (
                "/usr/bin/az",
                "network",
                "vnet",
                "list",
                "--subscription",
                subscription_id,
                "--query",
                "[].{local:addressSpace.addressPrefixes,peers:virtualNetworkPeerings[].{state:peeringState,prefixes:remoteAddressSpace.addressPrefixes}}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
        routes_future = executor.submit(
            _capture,
            ("/usr/sbin/ip", "-j", "-4", "route", "show", "table", "all"),
            cwd=repository_root,
        )
        route_tables_future = executor.submit(
            _subscription_resource_values,
            repository_root=repository_root,
            subscription_id=subscription_id,
            resource_type="Microsoft.Network/routeTables",
            query="properties.routes[].{name:name,prefix:properties.addressPrefix}",
            list_result=True,
        )
        local_gateways_future = executor.submit(
            _subscription_resource_values,
            repository_root=repository_root,
            subscription_id=subscription_id,
            resource_type="Microsoft.Network/localNetworkGateways",
            query="{name:name,prefixes:properties.localNetworkAddressSpace.addressPrefixes}",
            list_result=False,
        )
        vnets = json.loads(vnets_future.result())
        routes = json.loads(routes_future.result())
        route_tables = route_tables_future.result()
        local_gateways = local_gateways_future.result()
    used: list[ipaddress.IPv4Network] = []
    _require_complete_network_evidence(vnets, route_tables, local_gateways, routes)
    for payload in (vnets, local_gateways):
        used.extend(_ipv4_networks(payload))
    route_networks = _ipv4_networks(route_tables)
    route_networks.extend(_ipv4_networks([row["dst"] for row in routes]))
    used.extend(network for network in route_networks if network.prefixlen != 0)
    candidates = (
        "172.29.0.0/16",
        "172.30.0.0/16",
        "172.27.0.0/16",
        "172.28.0.0/16",
        "10.237.0.0/16",
        "10.238.0.0/16",
        "192.168.240.0/20",
    )
    available = [
        ipaddress.IPv4Network(candidate)
        for candidate in candidates
        if not any(ipaddress.IPv4Network(candidate).overlaps(current) for current in used)
    ]
    if len(available) < 2:
        raise ValueError(
            "no non-overlapping reviewed operations and build networks are available "
            f"(available={len(available)}, required=2); "
            "review VNet, peering, gateway, and non-default route reservations before retrying"
        )
    ops, build = available[:2]
    subnets = list(ops.subnets(new_prefix=24))
    build_subnets = list(build.subnets(new_prefix=26))
    return (
        ops,
        subnets[1],
        subnets[2],
        next(subnets[3].subnets(new_prefix=26)),
        build,
        build_subnets[1],
        build_subnets[2],
    )


def _subscription_resource_values(
    *,
    repository_root: Path,
    subscription_id: str,
    resource_type: str,
    query: str,
    list_result: bool,
) -> list[object]:
    """Read bounded resource properties across a subscription without requiring RG input."""

    raw_ids = json.loads(
        _capture(
            (
                "/usr/bin/az",
                "resource",
                "list",
                "--subscription",
                subscription_id,
                "--resource-type",
                resource_type,
                "--query",
                "[].id",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
    )
    if (
        not isinstance(raw_ids, list)
        or len(raw_ids) > 256
        or any(not isinstance(resource_id, str) or not resource_id for resource_id in raw_ids)
    ):
        raise ValueError("Azure network resource inventory is invalid or exceeds its bound")
    resource_ids = sorted(raw_ids, key=str.casefold)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                _capture,
                (
                    "/usr/bin/az",
                    "resource",
                    "show",
                    "--ids",
                    resource_id,
                    "--query",
                    query,
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                cwd=repository_root,
            )
            for resource_id in resource_ids
        ]
        values = [json.loads(future.result()) for future in futures]
    if list_result:
        if any(not isinstance(value, list) for value in values):
            raise ValueError("Azure network resource properties are incomplete")
        return [item for value in values for item in value]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError("Azure network resource properties are incomplete")
    return values


def _ipv4_networks(value: object) -> list[ipaddress.IPv4Network]:
    if isinstance(value, dict):
        return [network for item in value.values() for network in _ipv4_networks(item)]
    if isinstance(value, list):
        return [network for item in value for network in _ipv4_networks(item)]
    if not isinstance(value, str) or value == "default":
        return []
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return []
    return [network] if isinstance(network, ipaddress.IPv4Network) else []


def _require_complete_network_evidence(
    vnets: object, route_tables: object, local_gateways: object, local_routes: object
) -> None:
    if (
        not isinstance(vnets, list)
        or not isinstance(route_tables, list)
        or not isinstance(local_gateways, list)
        or not isinstance(local_routes, list)
    ):
        raise ValueError("Azure network evidence is incomplete")
    for vnet in vnets:
        if not isinstance(vnet, dict):
            raise ValueError("Azure VNet evidence is incomplete")
        _require_prefix_list(vnet.get("local"), label="Azure VNet")
        peers = vnet.get("peers")
        if not isinstance(peers, list):
            raise ValueError("Azure peering evidence is incomplete")
        for peer in peers:
            if not isinstance(peer, dict) or peer.get("state") not in {"Connected", "Initiated"}:
                raise ValueError("Azure peering evidence is incomplete")
            _require_prefix_list(peer.get("prefixes"), label="Azure peering")
    for route in route_tables:
        if not isinstance(route, dict) or not isinstance(route.get("prefix"), str):
            raise ValueError("Azure route-table evidence is incomplete")
        prefix = route["prefix"]
        if prefix not in _AZURE_ROUTE_SERVICE_TAGS and not _canonical_ipv4_prefix(prefix):
            raise ValueError("Azure route-table evidence contains an invalid prefix")
    for gateway in local_gateways:
        if not isinstance(gateway, dict) or not isinstance(gateway.get("name"), str):
            raise ValueError("Azure local-network-gateway evidence is incomplete")
        _require_prefix_list(gateway.get("prefixes"), label="Azure local-network-gateway")
    for route in local_routes:
        if not isinstance(route, dict) or not isinstance(route.get("dst"), str):
            raise ValueError("local route evidence is incomplete")
        destination = route["dst"]
        if destination != "default":
            try:
                if "/" in destination:
                    network = ipaddress.ip_network(destination)
                    valid = (
                        isinstance(network, ipaddress.IPv4Network) and str(network) == destination
                    )
                else:
                    valid = isinstance(ipaddress.ip_address(destination), ipaddress.IPv4Address)
            except ValueError:
                raise ValueError("local route evidence contains an invalid prefix") from None
            if not valid:
                raise ValueError("local route evidence contains an invalid prefix")


def _require_prefix_list(value: object, *, label: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not _canonical_ipv4_prefix(item) for item in value)
    ):
        raise ValueError(f"{label} evidence is incomplete or invalid")


def _canonical_ipv4_prefix(value: str) -> bool:
    try:
        network = ipaddress.IPv4Network(value)
    except ValueError:
        return False
    return str(network) == value


def _capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
    environment: dict[str, str] | None = None
    if arguments and arguments[0] == "/usr/bin/az":
        azure_config = Path(
            os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))
        ).resolve(strict=True)
        if not azure_config.is_dir() or azure_config.stat().st_mode & 0o022:
            raise ValueError("Azure CLI configuration directory is not trusted")
        environment = {
            "AZURE_CONFIG_DIR": str(azure_config),
            "HOME": str(azure_config.parent),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError("Genesis input discovery command failed")
    return completed.stdout.strip()
