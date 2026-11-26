"""Acquire the pinned Kubernetes client tools on a source-deployment managed host.

A signed kit ships ``kubectl`` and ``kubelogin`` in its ``bin`` directory. A source deployment
downloads the same pinned releases on the connected managed host and keeps them only when the
digests committed here match. A consistency test keeps these pins equal to the kit build script.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import platform
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)

KUBECTL_VERSION = "1.31.14"
KUBECTL_SHA256 = "8791ec7c8966b61420d55103a5fb948de9f0ca3d7306d789734975ad9704bdb0"
KUBELOGIN_VERSION = "0.2.19"
KUBELOGIN_ARCHIVE_SHA256 = "ebaeff02aa899c5cae6a2b954b64fc02738185319df2570f7dc053451efa4b2f"
_KUBECTL_URL = f"https://dl.k8s.io/release/v{KUBECTL_VERSION}/bin/linux/amd64/kubectl"
_KUBELOGIN_URL = (
    "https://github.com/Azure/kubelogin/releases/download/"
    f"v{KUBELOGIN_VERSION}/kubelogin-linux-amd64.zip"
)
_MAX_BYTES = 256 * 1024 * 1024
_RECEIPT = "kubernetes-tools.json"
_SCHEMA = "fdai.source-kubernetes-tools.v1"


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(
        self, request: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("Kubernetes tool downloads accept HTTPS redirects only")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def install_kubernetes_tools(directory: Path, *, timeout_seconds: int = 600) -> Path:
    """Return a private directory holding verified ``kubectl`` and ``kubelogin``.

    The release hosts are not trusted: each download is kept only when its committed digest
    matches. A rerun reuses the tools when their recorded binary digests still match.
    """
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("source Kubernetes tool pins cover linux_amd64 only")
    directory.mkdir(mode=0o700, exist_ok=True)
    details = directory.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o700:
        raise ValueError("source Kubernetes tool directory must be a private directory")
    receipt_path = directory / _RECEIPT
    if receipt_path.exists() and _retained_tools_match(directory, receipt_path):
        return directory
    deadline = DeploymentDeadline(timeout_seconds)
    kubectl = _download(_KUBECTL_URL, deadline)
    if hashlib.sha256(kubectl).hexdigest() != KUBECTL_SHA256:
        raise ValueError("downloaded kubectl does not match the committed digest")
    archive = _download(_KUBELOGIN_URL, deadline)
    if hashlib.sha256(archive).hexdigest() != KUBELOGIN_ARCHIVE_SHA256:
        raise ValueError("downloaded kubelogin archive does not match the committed digest")
    kubelogin = _kubelogin_binary(archive)
    binaries = {"kubectl": kubectl, "kubelogin": kubelogin}
    for name, content in binaries.items():
        path = directory / name
        path.unlink(missing_ok=True)
        write_private_bytes(path, content)
        path.chmod(0o700)
    receipt_path.unlink(missing_ok=True)
    write_private_output(
        receipt_path,
        json.dumps(
            {
                "schema_version": _SCHEMA,
                "kubectl_version": KUBECTL_VERSION,
                "kubelogin_version": KUBELOGIN_VERSION,
                "binary_sha256": {
                    name: hashlib.sha256(content).hexdigest()
                    for name, content in sorted(binaries.items())
                },
            },
            sort_keys=True,
        )
        + "\n",
    )
    return directory


def _retained_tools_match(directory: Path, receipt_path: Path) -> bool:
    try:
        receipt = json.loads(read_private_bytes(receipt_path, max_bytes=4096))
        digests = receipt["binary_sha256"]
        return (
            receipt.get("schema_version") == _SCHEMA
            and receipt.get("kubectl_version") == KUBECTL_VERSION
            and receipt.get("kubelogin_version") == KUBELOGIN_VERSION
            and digests.get("kubectl") == KUBECTL_SHA256
            and all(
                _binary_digest(directory / name) == digests.get(name)
                for name in ("kubectl", "kubelogin")
            )
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _binary_digest(path: Path) -> str:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or not 0 < details.st_size <= _MAX_BYTES
    ):
        raise ValueError("retained Kubernetes tool is not a private executable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(url: str, deadline: DeploymentDeadline) -> bytes:
    opener = urllib.request.build_opener(_HttpsOnlyRedirect())
    chunks = bytearray()
    try:
        with opener.open(url, timeout=deadline.remaining(60)) as response:
            while len(chunks) <= _MAX_BYTES:
                deadline.remaining()
                chunk = response.read1(min(1024 * 1024, _MAX_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        raise ValueError("pinned Kubernetes tool download is unavailable") from None
    if len(chunks) > _MAX_BYTES:
        raise ValueError("pinned Kubernetes tool download exceeds its bound")
    return bytes(chunks)


def _kubelogin_binary(archive: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = [item for item in bundle.infolist() if not item.is_dir()]
            if (
                len(members) != 1
                or PurePosixPath(members[0].filename).name != "kubelogin"
                or not 0 < members[0].file_size <= _MAX_BYTES
            ):
                raise ValueError("kubelogin archive member set is invalid")
            return bundle.read(members[0])
    except zipfile.BadZipFile:
        raise ValueError("kubelogin archive is invalid") from None
