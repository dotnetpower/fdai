"""Render the pinned AKS Store Demo manifest for the private scenario lab."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

SOURCE_COMMIT = "61b033448904a930f01d497ce7139aca87a1b12d"
SOURCE_URL = (
    "https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/"
    f"{SOURCE_COMMIT}/aks-store-all-in-one.yaml"
)
SOURCE_SHA256 = "c290390edb7e26396a498dd5cbcf7ace94115fe4be813cd80f4fda69d6cbcfee"
MAX_MANIFEST_BYTES = 1_000_000

IMAGE_REPLACEMENTS = {
    "ghcr.io/documentdb/documentdb/documentdb-local:pg17-0.112.0": (
        "ghcr.io/documentdb/documentdb/documentdb-local"
        "@sha256:6aafe73e0d4594655c33b982898de277b58787cce7079bb3c2b69cd93a6353d8"
    ),
    "rabbitmq:4.3.2-management-alpine": (
        "rabbitmq@sha256:0753b75ce99094c385483d89449d532a0544fb85e4942a478b21cc497ab66d33"
    ),
    "busybox:1.37.0": (
        "busybox@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"
    ),
    "ghcr.io/azure-samples/aks-store-demo/order-service:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/order-service"
        "@sha256:c44632ea9eaa847de390ff3cf5c99c203951720b8373480038b9a0f22d802ee9"
    ),
    "ghcr.io/azure-samples/aks-store-demo/makeline-service:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/makeline-service"
        "@sha256:807f651de8a294d5288d49c8f0b3332f1241be292335056aa3215925a35d37de"
    ),
    "ghcr.io/azure-samples/aks-store-demo/product-service:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/product-service"
        "@sha256:4843934ec03808540fd73b5e94628eac4a0c21d216528c6b14aab9b4b17ac13b"
    ),
    "ghcr.io/azure-samples/aks-store-demo/store-front:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/store-front"
        "@sha256:90b5ffc221df78403e3e118f4b05fa58809b583c30f339c3a0d9aa65b38d5ea8"
    ),
    "ghcr.io/azure-samples/aks-store-demo/store-admin:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/store-admin"
        "@sha256:180c15a7a5291629254916cdfb23a344fbf4eecd2ed9265accbc7c3157fbce8e"
    ),
    "ghcr.io/azure-samples/aks-store-demo/virtual-customer:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/virtual-customer"
        "@sha256:02d4385ec1669b0afd14576c16db57dad149d7b3695e968a934da720812cead8"
    ),
    "ghcr.io/azure-samples/aks-store-demo/virtual-worker:2.2.0": (
        "ghcr.io/azure-samples/aks-store-demo/virtual-worker"
        "@sha256:2c07e7fdadc2806c44016ec1e90a0d006727b406a4f64b36c07bc14fa764072b"
    ),
}

ORDER_SERVICE_REPLICA_SOURCE = """kind: Deployment
metadata:
  name: order-service
spec:
  replicas: 1
"""
ORDER_SERVICE_REPLICA_TARGET = ORDER_SERVICE_REPLICA_SOURCE.replace(
    "replicas: 1",
    "replicas: 3",
)


def render_manifest(source: str) -> str:
    """Pin images and apply the private three-replica lab overlay."""
    rendered = source
    for tagged_image, digest_image in IMAGE_REPLACEMENTS.items():
        source_line = f"image: {tagged_image}"
        if rendered.count(source_line) != 1:
            raise ValueError(f"expected exactly one upstream image reference: {tagged_image}")
        rendered = rendered.replace(source_line, f"image: {digest_image}")

    if rendered.count(ORDER_SERVICE_REPLICA_SOURCE) != 1:
        raise ValueError("expected exactly one upstream order-service replica declaration")
    rendered = rendered.replace(
        ORDER_SERVICE_REPLICA_SOURCE,
        ORDER_SERVICE_REPLICA_TARGET,
    )

    if rendered.count("type: LoadBalancer") != 2:
        raise ValueError("expected exactly two upstream public LoadBalancer services")
    return rendered.replace("type: LoadBalancer", "type: ClusterIP")


def download_source() -> bytes:
    """Download one bounded manifest from the immutable upstream commit."""
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS URL.
        SOURCE_URL,
        headers={"User-Agent": "fdai-scenario-lab"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed HTTPS URL.
        source = response.read(MAX_MANIFEST_BYTES + 1)
    if len(source) > MAX_MANIFEST_BYTES:
        raise ValueError("AKS Store Demo manifest exceeds the one-megabyte limit")
    digest = hashlib.sha256(source).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("AKS Store Demo manifest does not match the pinned SHA-256")
    return source


def main(argv: list[str]) -> int:
    """Download, verify, render, and write one owner-only manifest."""
    if len(argv) != 2:
        print("usage: render_aks_store_demo.py <output-path>", file=sys.stderr)
        return 2

    output_path = Path(argv[1])
    if not output_path.is_absolute() or output_path == Path("/"):
        print(
            "render_aks_store_demo: an absolute non-root output path is required.", file=sys.stderr
        )
        return 2
    if not output_path.parent.is_dir():
        print("render_aks_store_demo: the output directory must exist.", file=sys.stderr)
        return 2

    try:
        source = download_source().decode("utf-8")
        rendered = render_manifest(source)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"render_aks_store_demo: {exc}", file=sys.stderr)
        return 1

    output_path.write_text(rendered, encoding="utf-8")
    output_path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
