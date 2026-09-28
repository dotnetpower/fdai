"""Retain repository-safe AKS Store Demo readback evidence after an approved apply.

The evidence records the exact public DNS resolution, the Kubernetes and Azure Load Balancer
addresses, the HTTP health result, workload readiness, and the digest of every running image. It
also proves Store Admin stays private. The document contains no credentials or kubeconfig data.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import runpy
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAMESPACE = "fdai-sre-demo"
COMMAND_TIMEOUT_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 15
PUBLIC_ATTEMPTS = 6
PUBLIC_RETRY_SECONDS = 10
DNS_LABEL_ANNOTATION = "service.beta.kubernetes.io/azure-dns-label-name"
PUBLIC_SERVICE = "store-front"
PRIVATE_SERVICE = "store-admin"
EXPECTED_WORKLOADS = {
    ("StatefulSet", "documentdb"): 1,
    ("StatefulSet", "rabbitmq"): 1,
    ("Deployment", "order-service"): 3,
    ("Deployment", "makeline-service"): 1,
    ("Deployment", "product-service"): 1,
    ("Deployment", "store-front"): 1,
    ("Deployment", "store-admin"): 1,
    ("Deployment", "virtual-customer"): 1,
    ("Deployment", "virtual-worker"): 1,
}
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RESOURCE_NAME = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@(sha256:[0-9a-f]{64})$")

CommandRunner = Callable[[Sequence[str]], Any]


def pinned_images() -> frozenset[str]:
    """Return the reviewed digest references from the Store Demo renderer."""

    renderer = runpy.run_path(str(Path(__file__).with_name("render_aks_store_demo.py")))
    replacements = renderer["IMAGE_REPLACEMENTS"]
    return frozenset(str(value) for value in replacements.values())


def _digest(reference: object) -> str | None:
    if not isinstance(reference, str):
        return None
    match = DIGEST.search(reference)
    return match.group(1) if match else None


def _int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _items(kube: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    items = kube.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping) and item.get("kind") == kind]


def _name(item: Mapping[str, Any]) -> str:
    metadata = item.get("metadata")
    return str(metadata.get("name", "")) if isinstance(metadata, Mapping) else ""


def _workloads(kube: Mapping[str, Any], failures: list[str]) -> list[dict[str, Any]]:
    observed = {
        (kind, _name(item)): item
        for kind in ("Deployment", "StatefulSet")
        for item in _items(kube, kind)
    }
    for kind, name in sorted(set(observed) - set(EXPECTED_WORKLOADS)):
        failures.append(f"unexpected_workload:{kind}/{name}")
    workloads: list[dict[str, Any]] = []
    for (kind, name), expected in sorted(EXPECTED_WORKLOADS.items()):
        item = observed.get((kind, name))
        if item is None:
            failures.append(f"workload_missing:{kind}/{name}")
            continue
        spec = item.get("spec") if isinstance(item.get("spec"), Mapping) else {}
        status = item.get("status") if isinstance(item.get("status"), Mapping) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        desired = _int(spec.get("replicas"), 1)
        ready = _int(status.get("readyReplicas"))
        available = _int(status.get("availableReplicas"), ready)
        updated = _int(status.get("updatedReplicas"))
        current = _int(status.get("observedGeneration")) >= _int(metadata.get("generation"), 1)
        if not (desired == expected == ready == available == updated and current):
            failures.append(f"workload_not_ready:{kind}/{name}")
        workloads.append(
            {
                "kind": kind,
                "name": name,
                "expected_replicas": expected,
                "desired_replicas": desired,
                "ready_replicas": ready,
                "available_replicas": available,
                "updated_replicas": updated,
                "generation_observed": current,
            }
        )
    return workloads


def _services(
    kube: Mapping[str, Any], dns_label: str, failures: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    services = {_name(item): item for item in _items(kube, "Service")}
    for name, item in sorted(services.items()):
        spec = item.get("spec") if isinstance(item.get("spec"), Mapping) else {}
        if name != PUBLIC_SERVICE and spec.get("type") in {"LoadBalancer", "NodePort"}:
            failures.append(f"unexpected_exposed_service:{name}")

    def ingress(item: Mapping[str, Any] | None) -> list[str]:
        status = item.get("status") if isinstance(item, Mapping) else None
        balancer = status.get("loadBalancer") if isinstance(status, Mapping) else None
        entries = balancer.get("ingress") if isinstance(balancer, Mapping) else None
        if not isinstance(entries, list):
            return []
        return [
            str(entry.get("ip") or entry.get("hostname"))
            for entry in entries
            if isinstance(entry, Mapping) and (entry.get("ip") or entry.get("hostname"))
        ]

    public = services.get(PUBLIC_SERVICE)
    public_spec = public.get("spec") if isinstance(public, Mapping) else None
    public_metadata = public.get("metadata") if isinstance(public, Mapping) else None
    annotations = (
        public_metadata.get("annotations") if isinstance(public_metadata, Mapping) else None
    )
    public_ingress = ingress(public)
    front = {
        "service_type": public_spec.get("type") if isinstance(public_spec, Mapping) else None,
        "dns_label_annotation": (
            annotations.get(DNS_LABEL_ANNOTATION) if isinstance(annotations, Mapping) else None
        ),
        "load_balancer_ip": public_ingress[0] if len(public_ingress) == 1 else None,
    }
    if front["service_type"] != "LoadBalancer" or front["dns_label_annotation"] != dns_label:
        failures.append("store_front_service_invalid")
    try:
        ipaddress.ip_address(str(front["load_balancer_ip"]))
    except ValueError:
        failures.append("store_front_load_balancer_ip_invalid")

    private = services.get(PRIVATE_SERVICE)
    private_spec = private.get("spec") if isinstance(private, Mapping) else None
    admin = {
        "service_type": private_spec.get("type") if isinstance(private_spec, Mapping) else None,
        "external_ingress": ingress(private),
    }
    if admin["service_type"] != "ClusterIP" or admin["external_ingress"]:
        failures.append("store_admin_not_private")
    return front, admin


def _images(
    kube: Mapping[str, Any], pinned: frozenset[str], failures: list[str]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str | None], int] = {}
    for pod in _items(kube, "Pod"):
        metadata = pod.get("metadata") if isinstance(pod.get("metadata"), Mapping) else {}
        status = pod.get("status") if isinstance(pod.get("status"), Mapping) else {}
        if metadata.get("deletionTimestamp") or status.get("phase") != "Running":
            continue
        labels = metadata.get("labels") if isinstance(metadata.get("labels"), Mapping) else {}
        workload = str(labels.get("app", _name(pod)))
        spec = pod.get("spec") if isinstance(pod.get("spec"), Mapping) else {}
        observed_ids: dict[str, object] = {}
        for key in ("initContainerStatuses", "containerStatuses"):
            for entry in status.get(key) or ():
                if isinstance(entry, Mapping):
                    observed_ids[str(entry.get("name"))] = entry.get("imageID")
        for key in ("initContainers", "containers"):
            for container in spec.get(key) or ():
                if not isinstance(container, Mapping):
                    continue
                name = str(container.get("name"))
                image = str(container.get("image"))
                observed_digest = _digest(observed_ids.get(name))
                if image not in pinned:
                    failures.append(f"unpinned_image:{workload}/{name}")
                elif observed_digest != _digest(image):
                    failures.append(f"image_digest_mismatch:{workload}/{name}")
                group = (workload, name, image, observed_digest)
                grouped[group] = grouped.get(group, 0) + 1
    if not grouped:
        failures.append("running_images_missing")
    return [
        {
            "workload": workload,
            "container": container,
            "image": image,
            "running_digest": digest,
            "pods": count,
        }
        for (workload, container, image, digest), count in sorted(
            grouped.items(), key=lambda entry: (entry[0][0], entry[0][1], entry[0][2])
        )
    ]


def evaluate(
    *,
    kube: Mapping[str, Any],
    public_ips: Iterable[Mapping[str, Any]],
    dns_addresses: Sequence[str],
    http_status: int | None,
    hostname: str,
    dns_label: str,
    pinned: frozenset[str],
) -> tuple[dict[str, Any], list[str]]:
    """Build the evidence document and the list of failed readback checks."""

    failures: list[str] = []
    workloads = _workloads(kube, failures)
    front, admin = _services(kube, dns_label, failures)
    images = _images(kube, pinned, failures)
    azure_matches = [
        {"ip_address": entry.get("ipAddress"), "fqdn": entry.get("fqdn")}
        for entry in public_ips
        if isinstance(entry, Mapping)
    ]
    azure_public_ip = azure_matches[0] if len(azure_matches) == 1 else None
    load_balancer_ip = front["load_balancer_ip"]
    if (
        azure_public_ip is None
        or azure_public_ip["ip_address"] != load_balancer_ip
        or azure_public_ip["fqdn"] != hostname
    ):
        failures.append("azure_public_ip_mismatch")
    dns_matches = load_balancer_ip is not None and load_balancer_ip in dns_addresses
    if not dns_matches:
        failures.append("dns_does_not_resolve_to_load_balancer")
    if http_status != 200:
        failures.append("store_front_health_failed")
    store_front = {
        "hostname": hostname,
        **front,
        "azure_public_ip": azure_public_ip,
        "dns_addresses": sorted(dns_addresses),
        "dns_matches_load_balancer": dns_matches,
        "http_health_path": "/health",
        "http_health_status": http_status,
    }
    return (
        {
            "store_front": store_front,
            "store_admin": admin,
            "workloads": workloads,
            "images": images,
        },
        failures,
    )


def run_json(command: Sequence[str]) -> Any:
    """Run one bounded read-only command and parse its JSON output."""

    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{command[0]} readback exceeded its deadline") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"{command[0]} readback failed")
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command[0]} readback returned invalid JSON") from exc


def resolve(hostname: str) -> list[str]:
    try:
        entries = socket.getaddrinfo(hostname, 80, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({str(entry[4][0]) for entry in entries})


def probe_health(hostname: str) -> int | None:
    request = urllib.request.Request(  # noqa: S310 - the caller validates the fixed HTTP host.
        f"http://{hostname}/health",
        headers={"User-Agent": "fdai-scenario-lab-readback"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = getattr(response, "status", None)
            return status if isinstance(status, int) else None
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def _public_observation(
    hostname: str,
    load_balancer_ip: str | None,
    resolver: Callable[[str], list[str]],
    prober: Callable[[str], int | None],
    sleep: Callable[[float], None],
) -> tuple[list[str], int | None]:
    addresses: list[str] = []
    status: int | None = None
    for attempt in range(PUBLIC_ATTEMPTS):
        addresses = resolver(hostname)
        status = prober(hostname)
        if load_balancer_ip in addresses and status == 200:
            break
        if attempt + 1 < PUBLIC_ATTEMPTS:
            sleep(PUBLIC_RETRY_SECONDS)
    return addresses, status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store-front-url", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    return parser


def main(
    argv: Sequence[str],
    *,
    run: CommandRunner = run_json,
    resolver: Callable[[str], list[str]] = resolve,
    prober: Callable[[str], int | None] = probe_health,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _parser().parse_args(argv)
    hostname = args.store_front_url.removeprefix("http://").rstrip("/")
    dns_label = hostname.split(".", 1)[0]
    if (
        not hostname.endswith(".cloudapp.azure.com")
        or hostname != hostname.lower()
        or DNS_LABEL.fullmatch(dns_label) is None
        or RESOURCE_NAME.fullmatch(args.resource_group) is None
        or RESOURCE_NAME.fullmatch(args.cluster_name) is None
        or COMMIT.fullmatch(args.source_commit) is None
        or not args.run_id.isdigit()
        or not args.run_attempt.isdigit()
    ):
        print("readback_store_demo: invalid readback scope", file=sys.stderr)
        return 2
    try:
        kube = run(
            [
                "kubectl",
                "--namespace",
                NAMESPACE,
                "get",
                "deployments,statefulsets,services,pods",
                "--output",
                "json",
            ]
        )
        node_resource_group = run(
            [
                "az",
                "aks",
                "show",
                "--resource-group",
                args.resource_group,
                "--name",
                args.cluster_name,
                "--query",
                "nodeResourceGroup",
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        if not isinstance(node_resource_group, str) or not RESOURCE_NAME.fullmatch(
            node_resource_group
        ):
            raise RuntimeError("az readback returned an invalid node resource group")
        public_ips = run(
            [
                "az",
                "network",
                "public-ip",
                "list",
                "--resource-group",
                node_resource_group,
                "--query",
                f"[?dnsSettings.domainNameLabel=='{dns_label}']"
                ".{ipAddress: ipAddress, fqdn: dnsSettings.fqdn}",
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
    except RuntimeError as exc:
        print(f"readback_store_demo: {exc}", file=sys.stderr)
        return 1
    if not isinstance(kube, Mapping) or not isinstance(public_ips, list):
        print("readback_store_demo: readback returned an unexpected shape", file=sys.stderr)
        return 1

    pinned = pinned_images()
    preliminary, _ = evaluate(
        kube=kube,
        public_ips=public_ips,
        dns_addresses=[],
        http_status=None,
        hostname=hostname,
        dns_label=dns_label,
        pinned=pinned,
    )
    addresses, status = _public_observation(
        hostname,
        preliminary["store_front"]["load_balancer_ip"],
        resolver,
        prober,
        sleep,
    )
    evidence, failures = evaluate(
        kube=kube,
        public_ips=public_ips,
        dns_addresses=addresses,
        http_status=status,
        hostname=hostname,
        dns_label=dns_label,
        pinned=pinned,
    )
    document = {
        "schema_version": 1,
        "kind": "fdai.scenario_lab.store_demo_readback",
        "source_commit": args.source_commit,
        "workflow_run_id": args.run_id,
        "workflow_run_attempt": args.run_attempt,
        "observed_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "namespace": NAMESPACE,
        "verdict": "verified" if not failures else "failed",
        "failures": sorted(set(failures)),
        **evidence,
    }
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        print(
            "readback_store_demo: Store Demo readback failed: " + ", ".join(sorted(set(failures))),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
