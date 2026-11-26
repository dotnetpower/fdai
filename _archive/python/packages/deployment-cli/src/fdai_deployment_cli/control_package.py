"""Verify one signed deployment-control wheelhouse for managed-host execution.

The complete kit keeps its signed runtime payload: images, Terraform bundle, toolchain, and
Console. A control package replaces only the managed-host ``fdai-deployment-cli`` installation,
so a deployment-control repair needs a new signed wheelhouse instead of a new complete kit.
The only package guarantee is one detached Ed25519 signature over ``SHA256SUMS``.
"""

from __future__ import annotations

import hashlib
import re
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from fdai_deployment_cli.trust_roots import deployment_release_root_pem

PACKAGE_ROOT = "package"
_SUMS = "SHA256SUMS"
_SIGNATURE = "SHA256SUMS.sig"
_REQUIREMENTS = "requirements.txt"
_SUM_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*)")
_REQUIREMENT = re.compile(r"fdai-deployment-cli==([0-9]+\.[0-9]+\.[0-9]+)\n")
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ControlPackage:
    """A locally verified signed wheelhouse and the digests that bind it to one run."""

    archive: Path
    archive_digest: str
    sums_digest: str
    version: str


def verify_control_package(archive: Path, *, public_key_pem: bytes | None = None) -> ControlPackage:
    """Verify signature, exact file set, and digests of one control-package archive.

    Raises ``ValueError`` without secret or path values when the archive is not a regular
    file, contains links or unsafe paths, lacks a valid signature, lists a different file set,
    or does not install exactly one pinned ``fdai-deployment-cli`` version.
    """

    try:
        details = archive.lstat()
    except OSError as exc:
        raise ValueError("control package archive is unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_ARCHIVE_BYTES:
        raise ValueError("control package archive must be a bounded regular file")
    payload = archive.read_bytes()
    files = _read_members(archive)
    sums = files.pop(_SUMS, None)
    signature = files.pop(_SIGNATURE, None)
    if sums is None or signature is None:
        raise ValueError("control package signature files are missing")
    key = load_pem_public_key(public_key_pem or deployment_release_root_pem())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("control package trust root must be Ed25519")
    try:
        key.verify(signature, sums)
    except InvalidSignature as exc:
        raise ValueError("control package signature is invalid") from exc
    listed = _parse_sums(sums)
    if set(listed) != set(files):
        raise ValueError("control package file set differs from SHA256SUMS")
    for relative, expected in listed.items():
        if hashlib.sha256(files[relative]).hexdigest() != expected:
            raise ValueError("control package file digest differs from SHA256SUMS")
    requirement = _REQUIREMENT.fullmatch(files.get(_REQUIREMENTS, b"").decode("ascii", "replace"))
    if requirement is None:
        raise ValueError("control package must pin exactly fdai-deployment-cli")
    version = requirement.group(1)
    cli_wheels = [
        name
        for name in files
        if name.startswith("wheels/fdai_deployment_cli-") and name.endswith(".whl")
    ]
    if cli_wheels != [f"wheels/fdai_deployment_cli-{version}-py3-none-any.whl"]:
        raise ValueError("control package must contain exactly the pinned CLI wheel")
    return ControlPackage(
        archive=archive,
        archive_digest=hashlib.sha256(payload).hexdigest(),
        sums_digest=hashlib.sha256(sums).hexdigest(),
        version=version,
    )


def _read_members(archive: Path) -> dict[str, bytes]:
    """Read regular package members, rejecting links, devices, and escaping paths."""

    files: dict[str, bytes] = {}
    try:
        with tarfile.open(archive, mode="r:gz") as bundle:
            for member in bundle:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise ValueError("control package member path is unsafe")
                if path.parts[0] != PACKAGE_ROOT:
                    raise ValueError("control package member is outside the package root")
                if member.isdir():
                    continue
                if not member.isreg() or member.size > _MAX_MEMBER_BYTES:
                    raise ValueError("control package member must be a bounded regular file")
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                if relative in files or relative == ".":
                    raise ValueError("control package member is duplicated")
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise ValueError("control package member is unreadable")
                files[relative] = extracted.read()
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ValueError("control package archive is unreadable") from exc
    return files


def _parse_sums(sums: bytes) -> dict[str, str]:
    try:
        text = sums.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("control package SHA256SUMS is not ASCII") from exc
    listed: dict[str, str] = {}
    for line in text.splitlines():
        match = _SUM_LINE.fullmatch(line)
        if match is None or match.group(2) in listed:
            raise ValueError("control package SHA256SUMS is malformed")
        listed[match.group(2)] = match.group(1)
    if not listed:
        raise ValueError("control package SHA256SUMS is empty")
    return listed


__all__ = ["PACKAGE_ROOT", "ControlPackage", "verify_control_package"]
