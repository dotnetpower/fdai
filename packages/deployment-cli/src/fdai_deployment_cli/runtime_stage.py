"""Stage local runtime release bytes before the enclosing kit is signed."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.offline_kit import (
    _MAX_FILE_BYTES,
    MANIFEST_NAME,
    SIGNATURE_NAME,
    _copy_verified_file,
    _scan_tree,
    _sha256_nofollow,
)
from fdai_deployment_cli.private_output import _open_private_parent
from fdai_deployment_cli.runtime_release import load_runtime_release, validate_runtime_images


def stage_runtime_release(
    source: Path,
    kit: Path,
    *,
    deployment_bundle: Path,
    source_commit: str,
    platform_tag: str,
) -> str:
    """Copy a complete local inventory without registry access or image execution.

    V2 inventories also require valid service and ClamAV OCI content. Legacy v1
    remains stageable for inspection, not complete preparation. This is release
    assembly, not a signature or production-eligibility check. The caller supplies
    a private kit directory and signs it after staging.
    """
    directory = _open_private_parent(kit / "runtime")
    os.close(directory)
    if any(
        (kit / name).exists() or (kit / name).is_symlink()
        for name in (MANIFEST_NAME, SIGNATURE_NAME)
    ):
        raise ValueError("runtime staging requires an unsigned kit")
    release = load_runtime_release(
        source,
        expected_source_commit=source_commit,
        expected_platform_tag=platform_tag,
    )
    bundle_details = deployment_bundle.lstat()
    if bundle_details.st_size > _MAX_FILE_BYTES:
        raise ValueError("deployment bundle exceeds the offline kit file size limit")
    if release.deployment_bundle_sha256 != _sha256_nofollow(
        deployment_bundle, expected=bundle_details
    ):
        raise ValueError("runtime inventory does not match the deployment bundle")
    destination = kit / "runtime"
    if destination.exists() or destination.is_symlink():
        raise ValueError("runtime release destination already exists")
    digests, sizes, _total = _scan_tree(source / "runtime")
    with TemporaryDirectory(prefix=".runtime-", dir=kit) as temporary:
        staging = Path(temporary)
        payload = staging / "runtime"
        payload.mkdir(mode=0o700)
        for relative, digest in digests.items():
            target = payload / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _copy_verified_file(
                source / "runtime" / relative,
                target,
                expected_digest=digest,
                expected_size=sizes[relative],
            )
        copied = load_runtime_release(
            staging,
            expected_source_commit=source_commit,
            expected_platform_tag=platform_tag,
        )
        if copied.digest != release.digest:
            raise ValueError("runtime inventory changed during staging")
        if copied.schema_version == "fdai.runtime-release.v2":
            validate_runtime_images(staging, copied)
        payload.rename(destination)
    return copied.digest
