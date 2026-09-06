"""Prepare signed offline inputs without executing a deployment or granting trust."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.bundle import extract_bundle_archive, verify_bundle
from fdai_deployment_cli.compiler import compile_manifest
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.offline_kit import (
    materialize_verified_artifacts,
    verify_offline_kit,
)
from fdai_deployment_cli.private_output import _open_private_parent, write_private_output
from fdai_deployment_cli.runtime_release import load_runtime_release, validate_runtime_images


def prepare_offline_release(
    kit: Path,
    *,
    work_dir: Path,
    profile: ProvisionProfile,
    source_commit: str,
    release_root_pem: bytes,
    bundle_public_key_pem: bytes,
    cli_version: str,
    platform_tag: str,
) -> dict[str, object]:
    """Publish a verified snapshot in an existing, private, empty work directory.

    The caller supplies independently obtained verification keys, not keys trusted
    because they arrived in the kit. Complete v2 runtime inventory and OCI content
    are required, including the ClamAV sidecar. Preparation proves artifact integrity
    only: it neither establishes production release eligibility nor verifies Azure
    permissions, cost, foundation state, Console access, or resource discovery.
    """
    if profile.connectivity != "offline":
        raise ValueError("offline preparation requires an offline profile")
    if profile.monthly_cost_ceiling <= 0:
        raise ValueError("offline preparation requires an explicit positive monthly cost ceiling")
    directory = _open_private_parent(work_dir / "preparation.json")
    os.close(directory)
    manifest = compile_manifest(profile, source_commit=source_commit)
    verification = verify_offline_kit(
        kit,
        release_root_pem=release_root_pem,
        cli_version=cli_version,
        platform_tag=platform_tag,
    )
    if "runtime/release.json" not in dict(verification.file_digests):
        raise ValueError("toolchain-only kit: a signed runtime release inventory is required")
    destination = work_dir / "prepared"
    if destination.exists() or destination.is_symlink():
        raise ValueError("offline preparation destination already exists")
    with TemporaryDirectory(prefix=".prepare-", dir=work_dir) as temporary:
        staging = Path(temporary)
        artifacts = materialize_verified_artifacts(
            kit, verification, staging / "artifacts", include_all=True
        )
        runtime = load_runtime_release(
            staging / "artifacts",
            expected_source_commit=source_commit,
            expected_platform_tag=platform_tag,
        )
        if runtime.deployment_bundle_sha256 != dict(verification.file_digests).get(
            verification.deployment_bundle
        ):
            raise ValueError("runtime inventory does not match the signed deployment bundle")
        image_digests = validate_runtime_images(staging / "artifacts", runtime)
        bundle_root = extract_bundle_archive(artifacts.deployment_bundle, staging / "bundle")
        bundle = verify_bundle(
            bundle_root, public_key_pem=bundle_public_key_pem, cli_version=cli_version
        )
        if bundle.bundle_version != verification.bundle_version:
            raise ValueError("offline kit and deployment bundle versions do not match")
        if not (bundle_root / "infra").is_dir():
            raise ValueError("verified deployment bundle does not contain infra")
        binding = {
            "source_commit": source_commit,
            "profile_digest": canonical_digest(profile.to_mapping()),
            "target_binding": profile.target_binding,
            "monthly_cost_ceiling": profile.monthly_cost_ceiling,
            "offline_manifest_digest": verification.manifest_digest,
            "runtime_release_digest": runtime.digest,
            "deployment_bundle_digest": bundle.manifest_digest,
            "genesis_manifest_digest": manifest.digest,
            "image_content_digests": image_digests,
        }
        result: dict[str, object] = {
            "schema_version": "fdai.offline-preparation.v2",
            "state": "prepared",
            "subscription_ready": False,
            "mutation_performed": False,
            "production_release_eligibility": "unverified",
            "binding": binding,
            "preparation_digest": canonical_digest(binding),
            "stage_order": [entry.entry_id for entry in manifest.entries],
            "next_action": "review-foundation-plan",
            "required_checkpoints": [
                "production-release-eligibility",
                "foundation-plan-and-approval",
                "private-execution-host-and-state-handoff",
                "application-plan-and-approval",
                "database-and-semantic-readback",
                "model-readback",
                "authenticated-console-readback",
                "initial-inventory-readback",
                "system-verification",
                "second-run-no-change",
            ],
        }
        write_private_output(
            staging / "preparation.json",
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        )
        staging.rename(destination)
    return result
