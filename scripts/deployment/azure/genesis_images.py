#!/usr/bin/env python3
"""Resolve exact attested GHCR image digests for one protected source revision."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Protocol

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGES = (
    "fdai-core-control-plane",
    "fdai-operator-service",
    "fdai-document-ingestion-api",
)
_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class RegistryHeaders(Protocol):
    """Case-insensitive registry response headers."""

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return one response header."""
        ...


class RegistryResponse(Protocol):
    """Minimum bounded response surface used by registry resolution."""

    headers: RegistryHeaders

    def read(self, size: int = -1) -> bytes:
        """Read at most the requested response bytes."""
        ...


ResponseOpener = Callable[[urllib.request.Request], RegistryResponse]


def resolve_exact_images(
    repository: str,
    source_commit: str,
    *,
    opener: ResponseOpener = urllib.request.urlopen,
) -> dict[str, str]:
    """Return digest-pinned GHCR references without exposing provider credentials."""

    if _REPOSITORY.fullmatch(repository) is None or _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("container image source context is invalid")
    token = _github_token()
    owner, name = repository.casefold().split("/", 1)
    images = {
        image: _resolve_image(
            owner=owner,
            repository=name,
            image=image,
            source_commit=source_commit,
            token=token,
            opener=opener,
        )
        for image in _IMAGES
    }
    for reference in images.values():
        _verify_attestation(repository, source_commit, reference)
    return images


def _resolve_image(
    *,
    owner: str,
    repository: str,
    image: str,
    source_commit: str,
    token: str,
    opener: ResponseOpener,
) -> str:
    image_path = f"{owner}/{repository}/{image}"
    scope = urllib.parse.quote(f"repository:{image_path}:pull", safe=":/")
    basic = base64.b64encode(f"{owner}:{token}".encode()).decode("ascii")
    token_request = urllib.request.Request(
        f"https://ghcr.io/token?scope={scope}",
        headers={"Authorization": f"Basic {basic}"},
    )
    try:
        token_response = opener(token_request)
        registry_token = _response_json(token_response).get("token")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise ValueError("GHCR image token acquisition failed") from exc
    if not isinstance(registry_token, str) or not registry_token:
        raise ValueError("GHCR image token response is invalid")
    manifest_request = urllib.request.Request(
        f"https://ghcr.io/v2/{image_path}/manifests/sha-{source_commit}",
        method="HEAD",
        headers={"Authorization": f"Bearer {registry_token}", "Accept": _ACCEPT},
    )
    try:
        manifest_response = opener(manifest_request)
        digest = manifest_response.headers.get("Docker-Content-Digest")
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("exact GHCR image manifest is unavailable") from exc
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("exact GHCR image digest is invalid")
    return f"ghcr.io/{image_path}@{digest}"


def _github_token() -> str:
    completed = subprocess.run(
        ["gh", "auth", "token"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token or any(character in token for character in "\r\n"):
        raise ValueError("GitHub provider-hosted authentication is unavailable")
    return token


def _verify_attestation(repository: str, source_commit: str, reference: str) -> None:
    """Require registry-hosted SLSA provenance from the fixed workflow signer."""

    completed = subprocess.run(
        [
            "gh",
            "attestation",
            "verify",
            f"oci://{reference}",
            "--bundle-from-oci",
            "--repo",
            repository,
            "--source-digest",
            source_commit,
            "--predicate-type",
            "https://slsa.dev/provenance/v1",
            "--signer-workflow",
            f"{repository}/.github/workflows/container-supply-chain.yml",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
    )
    if completed.returncode != 0:
        raise ValueError("exact GHCR image attestation verification failed")


def _response_json(response: RegistryResponse) -> dict[str, object]:
    raw = response.read(65_537)
    if not isinstance(raw, bytes) or len(raw) > 65_536:
        raise ValueError("GHCR response exceeds its bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("GHCR response is invalid")
    return value
