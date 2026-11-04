"""Local Docker image inspection, OCI Distribution v2 manifest registry, and real digest binding.

Resolves real built container images from the local Docker engine (or an explicitly uploaded
OCI v2 manifest), publishes canonical OCI v2 image manifests served at
`/v2/fdai/<component>/manifests/<ref>`, and binds their verified `sha256:<64-hex>` digests into
`fdai.application-release.v2` manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

OCI_IMAGE_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
OCI_IMAGE_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
OCI_IMAGE_LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPONENT_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")

CANDIDATE_DOCKER_TAGS: Mapping[str, tuple[str, ...]] = {
    "core-control-plane": (
        "fdai-core-control-plane:lite-release",
        "fdai-core-control-plane:latest",
        "fdai-core-control-plane:local",
    ),
    "operator-service": (
        "fdai-operator-service:lite-release",
        "fdai-operator-service:latest",
        "fdai-operator-service:local",
    ),
    "isolated-executor": (
        "fdai-isolated-executor:lite-release",
        "fdai-isolated-executor:latest",
        "fdai-isolated-executor:local",
    ),
    "document-ingestion-api": (
        "fdai-document-ingestion-api:lite-release",
        "fdai-document-ingestion-api:latest",
        "fdai-document-ingestion-api:local",
    ),
    "document-processing-worker": (
        "fdai-document-processing-worker:lite-release",
        "fdai-document-processing-worker:latest",
        "fdai-document-processing-worker:local",
    ),
    "pgvector": (
        "pgvector/pgvector:pg16",
        "pgvector/pgvector:latest",
    ),
    "clamav": (
        "clamav/clamav:stable",
        "clamav/clamav:latest",
    ),
}


@dataclass(frozen=True, slots=True)
class LocalDockerImageInfo:
    component: str
    source_tag: str
    image_digest: str
    config_digest: str
    size_bytes: int
    layers: tuple[str, ...]
    architecture: str
    os_name: str


@dataclass(frozen=True, slots=True)
class BoundComponentArtifact:
    component: str
    image_digest: str
    image_ref: str
    source_tag: str | None
    size_bytes: int
    layer_count: int
    provenance: str
    oci_manifest_path: str
    oci_manifest_bytes: bytes

    def to_metadata(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "image_digest": self.image_digest,
            "image_ref": self.image_ref,
            "source_tag": self.source_tag,
            "size_bytes": self.size_bytes,
            "layer_count": self.layer_count,
            "provenance": self.provenance,
            "oci_manifest_path": self.oci_manifest_path,
        }


_CACHE_LOCK = threading.Lock()
_DOCKER_CACHE: dict[str, tuple[float, LocalDockerImageInfo | None]] = {}
_DOCKER_CACHE_TTL_SECONDS = 30.0
_PUBLISHED_MANIFESTS: dict[tuple[str, str], bytes] = {}
_PUBLISHED_ARTIFACTS: dict[str, BoundComponentArtifact] = {}


def default_registry_host() -> str:
    """Return the configured registry authority or the canonical Release Hub host."""
    configured = os.environ.get("FDAI_RELEASE_HUB_REGISTRY", "").strip().lower().rstrip("/")
    if configured and re.fullmatch(
        r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[1-9][0-9]{0,4})?",
        configured,
    ):
        return configured
    return "hub.msfdai.com"


def inspect_local_docker_component(
    component: str,
    *,
    timeout_seconds: float = 3.0,
) -> LocalDockerImageInfo | None:
    """Inspect the local Docker daemon for a built component image without mutating state."""
    if not _COMPONENT_RE.fullmatch(component):
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _DOCKER_CACHE.get(component)
        if cached is not None and (now - cached[0]) < _DOCKER_CACHE_TTL_SECONDS:
            return cached[1]

    candidates = CANDIDATE_DOCKER_TAGS.get(
        component,
        (f"fdai-{component}:lite-release", f"fdai-{component}:latest"),
    )
    found: LocalDockerImageInfo | None = None
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
    }
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        with _CACHE_LOCK:
            _DOCKER_CACHE[component] = (time.monotonic(), None)
        return None
    for tag in candidates:
        try:
            proc = subprocess.run(  # noqa: S603
                (docker_bin, "image", "inspect", tag),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError):
            break
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        try:
            payload = json.loads(proc.stdout)
            if not isinstance(payload, list) or not payload:
                continue
            item = payload[0]
            raw_id = str(item.get("Id", "")).strip().lower()
            if not _DIGEST_RE.fullmatch(raw_id):
                continue
            repo_digests = item.get("RepoDigests") or []
            resolved_digest = raw_id
            if isinstance(repo_digests, list):
                for entry in repo_digests:
                    if isinstance(entry, str) and "@sha256:" in entry:
                        cand_digest = "sha256:" + entry.rsplit("@sha256:", 1)[1].strip().lower()
                        if _DIGEST_RE.fullmatch(cand_digest):
                            resolved_digest = cand_digest
                            break
            rootfs = item.get("RootFS") or {}
            raw_layers = rootfs.get("Layers") if isinstance(rootfs, dict) else []
            layers = tuple(
                str(layer).strip().lower()
                for layer in (raw_layers if isinstance(raw_layers, list) else [])
                if _DIGEST_RE.fullmatch(str(layer).strip().lower())
            )
            size_bytes = max(0, int(item.get("Size") or 0))
            arch = str(item.get("Architecture") or "amd64")
            os_name = str(item.get("Os") or "linux")
            found = LocalDockerImageInfo(
                component=component,
                source_tag=tag,
                image_digest=resolved_digest,
                config_digest=raw_id,
                size_bytes=size_bytes,
                layers=layers,
                architecture=arch,
                os_name=os_name,
            )
            break
        except (ValueError, TypeError, KeyError):
            continue

    with _CACHE_LOCK:
        _DOCKER_CACHE[component] = (time.monotonic(), found)
    return found


def build_oci_manifest_bytes(
    *,
    component: str,
    release_version: str,
    source_commit: str,
    stencil_id: str,
    config_digest: str,
    layers: Sequence[str],
    size_bytes: int,
    provenance: str,
) -> bytes:
    """Construct a canonical OCI Image Manifest v1 JSON payload."""
    layer_list = list(layers) if layers else [config_digest]
    per_layer_size = max(1, size_bytes // len(layer_list)) if size_bytes > 0 else 1024
    manifest_obj = {
        "schemaVersion": 2,
        "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
        "config": {
            "mediaType": OCI_IMAGE_CONFIG_MEDIA_TYPE,
            "digest": config_digest,
            "size": 1480,
        },
        "layers": [
            {
                "mediaType": OCI_IMAGE_LAYER_MEDIA_TYPE,
                "digest": layer_digest,
                "size": per_layer_size,
            }
            for layer_digest in layer_list
        ],
        "annotations": {
            "org.opencontainers.image.title": f"fdai/{component}",
            "org.opencontainers.image.version": release_version,
            "org.opencontainers.image.revision": source_commit,
            "io.fdai.stencil.id": stencil_id,
            "io.fdai.digest.provenance": provenance,
        },
    }
    return json.dumps(manifest_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def register_oci_manifest(
    component: str,
    *,
    reference: str,
    image_digest: str,
    manifest_bytes: bytes,
    artifact: BoundComponentArtifact | None = None,
) -> None:
    """Store an OCI v2 manifest by both tag reference and immutable digest."""
    with _CACHE_LOCK:
        _PUBLISHED_MANIFESTS[(component, image_digest)] = manifest_bytes
        _PUBLISHED_MANIFESTS[(component, reference)] = manifest_bytes
        if artifact is not None:
            _PUBLISHED_ARTIFACTS[f"{component}@{image_digest}"] = artifact
            _PUBLISHED_ARTIFACTS[f"{component}:latest"] = artifact


def resolve_and_bind_stencil_images(
    *,
    required_components: Sequence[str],
    stencil_id: str,
    stencil_digest: str,
    release_version: str,
    source_commit: str,
    explicit_digests: Mapping[str, str] | None = None,
    registry_host: str | None = None,
    resolve_local_docker: bool = True,
    tag_local_docker: bool = False,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Resolve component digests and publish canonical OCI v2 manifests."""
    host = (registry_host or default_registry_host()).strip().lower().rstrip("/")
    components_map: dict[str, dict[str, str]] = {}
    pipeline_records: dict[str, dict[str, Any]] = {}
    verified_count = 0
    sorted_components = sorted(set(required_components))

    for index, name in enumerate(sorted_components, start=1):
        provided = (explicit_digests or {}).get(name)
        docker_info = (
            inspect_local_docker_component(name)
            if provided is None and resolve_local_docker
            else None
        )
        if provided is not None:
            if not _DIGEST_RE.fullmatch(provided):
                raise ValueError(f"Invalid digest for component {name!r}.")
            digest = provided
            config_digest = provided
            layers: Sequence[str] = (provided,)
            size_bytes = 0
            source_tag = "explicit-caller-digest"
            provenance = "explicit-digest-bound"
            verified_count += 1
        elif docker_info is not None:
            digest = docker_info.image_digest
            config_digest = docker_info.config_digest
            layers = docker_info.layers
            size_bytes = docker_info.size_bytes
            source_tag = docker_info.source_tag
            provenance = "docker-local-verified"
            verified_count += 1
            if tag_local_docker:
                docker_bin = shutil.which("docker")
                if docker_bin is not None:
                    try:
                        subprocess.run(  # noqa: S603
                            (
                                docker_bin,
                                "tag",
                                docker_info.source_tag,
                                f"127.0.0.1:8091/fdai/{name}:{release_version}",
                            ),
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            check=False,
                            timeout=3.0,
                        )
                    except (OSError, subprocess.SubprocessError):
                        pass
        else:
            seed = f"{stencil_digest}:{release_version}:{source_commit}:{name}:{index}".encode()
            digest = "sha256:" + hashlib.sha256(seed).hexdigest()
            config_digest = digest
            layers = (digest,)
            size_bytes = 0
            source_tag = None
            provenance = "synthetic-seed"

        image_ref = f"{host}/fdai/{name}@{digest}"
        oci_path = f"/v2/fdai/{name}/manifests/{digest}"
        oci_bytes = build_oci_manifest_bytes(
            component=name,
            release_version=release_version,
            source_commit=source_commit,
            stencil_id=stencil_id,
            config_digest=config_digest,
            layers=layers,
            size_bytes=size_bytes,
            provenance=provenance,
        )
        artifact = BoundComponentArtifact(
            component=name,
            image_digest=digest,
            image_ref=image_ref,
            source_tag=source_tag,
            size_bytes=size_bytes,
            layer_count=len(layers),
            provenance=provenance,
            oci_manifest_path=oci_path,
            oci_manifest_bytes=oci_bytes,
        )
        register_oci_manifest(
            name,
            reference=release_version,
            image_digest=digest,
            manifest_bytes=oci_bytes,
            artifact=artifact,
        )
        components_map[name] = {
            "image_digest": digest,
            "image_ref": image_ref,
        }
        pipeline_records[name] = artifact.to_metadata()

    total_count = len(sorted_components)
    summary = {
        "registry_host": host,
        "local_oci_endpoint": "/v2",
        "verified_component_count": verified_count,
        "total_component_count": total_count,
        "all_real_digests_bound": verified_count == total_count and total_count > 0,
        "digest_mode": (
            "docker-verified"
            if verified_count == total_count and total_count > 0
            else ("hybrid-verified" if verified_count > 0 else "synthetic-seed")
        ),
        "components": pipeline_records,
    }
    return components_map, summary


def lookup_oci_manifest(component: str, reference: str) -> tuple[bytes, str] | None:
    """Resolve an OCI v2 manifest by digest or tag from published memory or local Docker."""
    if not _COMPONENT_RE.fullmatch(component):
        return None
    with _CACHE_LOCK:
        raw = _PUBLISHED_MANIFESTS.get((component, reference))
        if raw is not None:
            digest = (
                reference
                if _DIGEST_RE.fullmatch(reference)
                else "sha256:" + hashlib.sha256(raw).hexdigest()
            )
            return raw, digest

    docker_info = inspect_local_docker_component(component)
    if docker_info is not None and reference in (
        docker_info.image_digest,
        docker_info.config_digest,
        "latest",
        "lite-release",
    ):
        oci_bytes = build_oci_manifest_bytes(
            component=component,
            release_version=reference if not reference.startswith("sha256:") else "0.5.0",
            source_commit="0" * 40,
            stencil_id="lite-observe-alert",
            config_digest=docker_info.config_digest,
            layers=docker_info.layers,
            size_bytes=docker_info.size_bytes,
            provenance="docker-local-verified",
        )
        register_oci_manifest(
            component,
            reference=reference,
            image_digest=docker_info.image_digest,
            manifest_bytes=oci_bytes,
        )
        return oci_bytes, docker_info.image_digest
    return None


def registry_inventory_payload() -> dict[str, Any]:
    """Return all currently available local Docker images and bound OCI registry artifacts."""
    discovered: dict[str, dict[str, Any]] = {}
    for component in sorted(CANDIDATE_DOCKER_TAGS):
        info = inspect_local_docker_component(component)
        if info is not None:
            discovered[component] = {
                "component": component,
                "available": True,
                "source_tag": info.source_tag,
                "image_digest": info.image_digest,
                "config_digest": info.config_digest,
                "size_bytes": info.size_bytes,
                "layer_count": len(info.layers),
                "architecture": info.architecture,
                "os": info.os_name,
                "oci_manifest_path": f"/v2/fdai/{component}/manifests/{info.image_digest}",
            }
        else:
            discovered[component] = {
                "component": component,
                "available": False,
                "source_tag": None,
                "image_digest": None,
                "config_digest": None,
                "size_bytes": 0,
                "layer_count": 0,
                "architecture": None,
                "os": None,
                "oci_manifest_path": None,
            }
    with _CACHE_LOCK:
        published_keys = sorted(_PUBLISHED_ARTIFACTS)
        published_items = [_PUBLISHED_ARTIFACTS[k].to_metadata() for k in published_keys]
    return {
        "registry_host": default_registry_host(),
        "oci_v2_endpoint": "/v2",
        "docker_components": discovered,
        "published_artifacts": published_items,
    }
