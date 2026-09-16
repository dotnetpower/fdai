"""Verify source-bound runtime content without release trust or execution authority."""

from __future__ import annotations

import re
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.runtime_build import _regular_digest
from fdai_deployment_cli.runtime_release import load_runtime_release, validate_runtime_images
from fdai_deployment_cli.source_snapshot import verify_source_snapshot


def verify_source_runtime(
    *,
    snapshot: Path,
    snapshot_digest: str,
    runtime_root: Path,
    runtime_digest: str,
    deployment_bundle: Path,
    bundle_digest: str,
    platform_tag: str,
) -> dict[str, object]:
    """Return no-authority content evidence for independently pinned local inputs.

    This read-only check rejects changed snapshots, catalogs, payloads, revision,
    platform or bundle bytes. OCI validation checks all service images and ClamAV;
    other payloads remain opaque. No signature, bundle-source correspondence,
    toolchain, support semantics, host identity or execution eligibility is proved.
    Callers must preserve exclusive ownership and reverify inputs before later use.
    """
    for digest in (snapshot_digest, runtime_digest, bundle_digest):
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("source runtime requires independently pinned SHA-256 digests")
    if any(not path.is_absolute() for path in (snapshot, runtime_root, deployment_bundle)):
        raise ValueError("source runtime paths must be absolute")
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    commit = source.get("source_commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("source runtime source commit is invalid")
    release = load_runtime_release(
        runtime_root, expected_source_commit=commit, expected_platform_tag=platform_tag
    )
    if release.digest != runtime_digest:
        raise ValueError("source runtime catalog differs from the retained digest")
    if (
        release.deployment_bundle_sha256 != bundle_digest
        or _regular_digest(deployment_bundle, label="source deployment bundle") != bundle_digest
    ):
        raise ValueError("source runtime deployment bundle differs from the retained digest")
    images = validate_runtime_images(runtime_root, release)
    observed = load_runtime_release(
        runtime_root, expected_source_commit=commit, expected_platform_tag=platform_tag
    )
    if (
        observed.digest != runtime_digest
        or verify_source_snapshot(snapshot, expected_digest=snapshot_digest) != source
        or _regular_digest(deployment_bundle, label="source deployment bundle") != bundle_digest
    ):
        raise ValueError("source runtime inputs changed during verification")
    result: dict[str, object] = {
        "schema_version": "fdai.source-runtime-content.v1",
        "state": "content-verified",
        "source_commit": commit,
        "source_snapshot_digest": snapshot_digest,
        "runtime_release_digest": runtime_digest,
        "deployment_bundle_sha256": bundle_digest,
        "platform_tag": platform_tag,
        "artifact_count": len(release.artifact_paths),
        "image_content_digests": images,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "bundle_source_verified": False,
        "support_contents_verified": False,
        "registry_published": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result
