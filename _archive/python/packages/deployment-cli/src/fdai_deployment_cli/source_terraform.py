"""Acquire the committed Terraform release for a source deployment."""

from __future__ import annotations

import hashlib
import http.client
import io
import platform
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import write_private_bytes

_RELEASES = "https://releases.hashicorp.com/terraform"
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_BINARY_BYTES = 128 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Terraform release redirects are not supported")


def download_pinned_terraform(
    *, toolchain: dict[str, Any], destination: Path, timeout_seconds: int = 300
) -> Path:
    """Fetch the pinned release once and keep it only when both committed digests match.

    The archive digest and the extracted binary digest both come from the source
    snapshot's toolchain record, so the public release host is never trusted.
    """
    version = toolchain.get("terraform_version")
    archive_digest = toolchain.get("terraform_sha256")
    binary_digest = toolchain.get("terraform_binary_sha256")
    if (
        not isinstance(version, str)
        or re.fullmatch(r"\d+\.\d+\.\d+", version) is None
        or not isinstance(archive_digest, str)
        or _DIGEST.fullmatch(archive_digest) is None
        or not isinstance(binary_digest, str)
        or _DIGEST.fullmatch(binary_digest) is None
    ):
        raise ValueError("source toolchain does not pin a Terraform release")
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError(
            f"install Terraform {version} on PATH; the committed digests cover linux_amd64 only"
        )
    deadline = DeploymentDeadline(timeout_seconds)
    url = f"{_RELEASES}/{version}/terraform_{version}_linux_amd64.zip"
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(url, timeout=deadline.remaining(60)) as response:
            chunks = bytearray()
            while len(chunks) <= _MAX_ARCHIVE_BYTES:
                deadline.remaining()
                chunk = response.read1(min(1024 * 1024, _MAX_ARCHIVE_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        raise ValueError(
            f"Terraform {version} download unavailable; install it on PATH or retry"
        ) from None
    archive = bytes(chunks)
    if len(archive) > _MAX_ARCHIVE_BYTES or hashlib.sha256(archive).hexdigest() != archive_digest:
        raise ValueError("downloaded Terraform archive does not match the committed digest")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            member = bundle.getinfo("terraform")
            if not 0 < member.file_size <= _MAX_BINARY_BYTES:
                raise ValueError("downloaded Terraform binary exceeds its bound")
            binary = bundle.read(member)
    except (KeyError, zipfile.BadZipFile):
        raise ValueError("downloaded Terraform archive has no terraform binary") from None
    if hashlib.sha256(binary).hexdigest() != binary_digest:
        raise ValueError("downloaded Terraform binary does not match the committed digest")
    write_private_bytes(destination, binary)
    destination.chmod(0o700)
    return destination
